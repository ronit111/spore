"""SQLite index for fast local discovery of findings.

The index is a local cache — it can always be rebuilt from the YAML manifests
in .spore/. It provides full-text search, metric filtering, and lineage queries
without parsing YAML on every discovery request.
"""

from __future__ import annotations

import math
import sqlite3
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from spore.models import Finding

# Delimiter for storing lists in SQLite text columns.
# Using a unit separator (ASCII 31) instead of comma to avoid
# corruption when list items contain commas.
_LIST_SEP = "\x1f"


def compute_earned_significance(self_reported: float, adoption_count: int) -> float:
    """Compute earned significance from self-reported score and adoption count.

    New findings start at their self-reported significance. As other agents
    adopt (build on) a finding, its earned significance grows logarithmically.
    A finding can never drop below its self-reported score.

    Formula: min(1.0, self_reported + 0.1 * log2(1 + adoption_count))
    """
    if adoption_count <= 0:
        return self_reported
    bonus = 0.1 * math.log2(1 + adoption_count)
    return min(1.0, self_reported + bonus)


class SporeIndex:
    """SQLite-backed index for finding discovery."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._create_tables()
        return self._conn

    def _create_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS findings (
                id TEXT PRIMARY KEY,
                experiment_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                direction TEXT NOT NULL,
                claim TEXT NOT NULL,
                hypothesis TEXT,
                significance REAL DEFAULT 0.5,
                status TEXT DEFAULT 'published',
                builds_on TEXT DEFAULT '',
                applicability TEXT DEFAULT '',
                source_branch TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS finding_metrics (
                finding_id TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                PRIMARY KEY (finding_id, metric_name),
                FOREIGN KEY (finding_id) REFERENCES findings(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_findings_direction
                ON findings(direction);
            CREATE INDEX IF NOT EXISTS idx_findings_agent
                ON findings(agent_id);
            CREATE INDEX IF NOT EXISTS idx_findings_status
                ON findings(status);
            CREATE INDEX IF NOT EXISTS idx_finding_metrics_name
                ON finding_metrics(metric_name);

            CREATE VIRTUAL TABLE IF NOT EXISTS findings_fts USING fts5(
                id,
                claim,
                hypothesis,
                direction,
                applicability,
                content='findings',
                content_rowid='rowid'
            );

            CREATE TRIGGER IF NOT EXISTS findings_ai AFTER INSERT ON findings BEGIN
                INSERT INTO findings_fts(id, claim, hypothesis, direction, applicability)
                VALUES (new.id, new.claim, new.hypothesis, new.direction, new.applicability);
            END;

            CREATE TRIGGER IF NOT EXISTS findings_ad AFTER DELETE ON findings
            BEGIN
                INSERT INTO findings_fts(
                    findings_fts, id, claim, hypothesis,
                    direction, applicability
                ) VALUES (
                    'delete', old.id, old.claim, old.hypothesis,
                    old.direction, old.applicability
                );
            END;
        """)

    def add_finding(self, finding: Finding, source_branch: str = "") -> None:
        """Add or update a finding in the index."""
        self.conn.execute(
            """INSERT OR REPLACE INTO findings
               (id, experiment_id, agent_id, timestamp, direction, claim,
                hypothesis, significance, status, builds_on, applicability, source_branch)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                finding.id,
                finding.experiment_id,
                finding.agent_id,
                finding.timestamp.isoformat(),
                finding.direction,
                finding.claim,
                finding.hypothesis,
                finding.significance,
                finding.status.value,
                _LIST_SEP.join(finding.builds_on),
                _LIST_SEP.join(finding.applicability),
                source_branch,
            ),
        )
        # Index metrics
        self.conn.execute("DELETE FROM finding_metrics WHERE finding_id = ?", (finding.id,))
        for name, value in finding.evidence.metrics.items():
            self.conn.execute(
                "INSERT INTO finding_metrics"
                " (finding_id, metric_name, metric_value)"
                " VALUES (?, ?, ?)",
                (finding.id, name, value),
            )
        self.conn.commit()

    def remove_finding(self, finding_id: str) -> None:
        """Remove a finding from the index."""
        self.conn.execute("DELETE FROM findings WHERE id = ?", (finding_id,))
        self.conn.commit()

    def search(
        self,
        query: str | None = None,
        direction: str | None = None,
        agent_id: str | None = None,
        metric_name: str | None = None,
        metric_max: float | None = None,
        metric_min: float | None = None,
        min_significance: float | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search findings with filters.

        Args:
            query: Full-text search across claim, hypothesis, direction.
            direction: Filter by research direction (substring match).
            agent_id: Filter by agent.
            metric_name: Filter by metric name.
            metric_max: Maximum metric value (requires metric_name).
            metric_min: Minimum metric value (requires metric_name).
            min_significance: Minimum significance score.
            limit: Maximum results to return.

        Returns:
            List of finding dicts with metrics attached.
        """
        if query:
            return self._enrich_with_earned_significance(self._fts_search(query, direction, limit))

        conditions: list[str] = ["f.status = 'published'"]
        params: list[Any] = []

        if direction:
            conditions.append("f.direction LIKE ?")
            params.append(f"%{direction}%")

        if agent_id:
            conditions.append("f.agent_id = ?")
            params.append(agent_id)

        if min_significance is not None:
            conditions.append("f.significance >= ?")
            params.append(min_significance)

        join_clause = ""
        if metric_name:
            join_clause = "JOIN finding_metrics fm ON f.id = fm.finding_id"
            conditions.append("fm.metric_name = ?")
            params.append(metric_name)
            if metric_max is not None:
                conditions.append("fm.metric_value <= ?")
                params.append(metric_max)
            if metric_min is not None:
                conditions.append("fm.metric_value >= ?")
                params.append(metric_min)

        where = " AND ".join(conditions)
        params.append(limit)

        rows = self.conn.execute(
            f"""SELECT f.* FROM findings f {join_clause}
                WHERE {where}
                ORDER BY f.significance DESC, f.timestamp DESC
                LIMIT ?""",
            params,
        ).fetchall()

        return self._enrich_with_earned_significance([self._row_to_dict(row) for row in rows])

    def _fts_search(self, query: str, direction: str | None, limit: int) -> list[dict[str, Any]]:
        conditions = ["findings_fts MATCH ?", "f.status = 'published'"]
        params: list[Any] = [query]

        if direction:
            conditions.append("f.direction LIKE ?")
            params.append(f"%{direction}%")

        where = " AND ".join(conditions)
        params.append(limit)

        rows = self.conn.execute(
            f"""SELECT f.* FROM findings f
                JOIN findings_fts fts ON f.id = fts.id
                WHERE {where}
                ORDER BY rank, f.significance DESC
                LIMIT ?""",
            params,
        ).fetchall()

        return [self._row_to_dict(row) for row in rows]

    def get_metrics(self, finding_id: str) -> dict[str, float]:
        """Get all metrics for a finding."""
        rows = self.conn.execute(
            "SELECT metric_name, metric_value FROM finding_metrics WHERE finding_id = ?",
            (finding_id,),
        ).fetchall()
        return {row["metric_name"]: row["metric_value"] for row in rows}

    def get_lineage(self, finding_id: str, depth: int = 10) -> list[dict[str, Any]]:
        """Trace the lineage of a finding (what it builds on, recursively)."""
        visited: set[str] = set()
        lineage: list[dict[str, Any]] = []
        queue: deque[str] = deque([finding_id])

        while queue and len(visited) < depth:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            row = self.conn.execute("SELECT * FROM findings WHERE id = ?", (current,)).fetchone()
            if row is None:
                continue

            entry = self._row_to_dict(row)
            if current != finding_id:
                lineage.append(entry)

            builds_on = entry.get("builds_on", "")
            if builds_on:
                parents = builds_on.split(_LIST_SEP) if isinstance(builds_on, str) else builds_on
                queue.extend(p for p in parents if p and p not in visited)

        return lineage

    def get_dependents(self, finding_id: str) -> list[dict[str, Any]]:
        """Find all findings that build on a given finding."""
        # Match exact ID within the separator-delimited builds_on field
        pattern = f"%{finding_id}%"
        rows = self.conn.execute(
            "SELECT * FROM findings WHERE builds_on LIKE ?",
            (pattern,),
        ).fetchall()
        # Post-filter to ensure exact ID match (not partial)
        results = []
        for row in rows:
            entry = self._row_to_dict(row)
            parents = entry.get("builds_on", "").split(_LIST_SEP) if entry.get("builds_on") else []
            if finding_id in parents:
                results.append(entry)
        return results

    def get_adoption_count(self, finding_id: str) -> int:
        """Count how many published findings build on a given finding."""
        rows = self.conn.execute(
            "SELECT builds_on FROM findings WHERE builds_on LIKE ? AND status = 'published'",
            (f"%{finding_id}%",),
        ).fetchall()
        # Post-filter for exact ID match within the separator-delimited field
        count = 0
        for row in rows:
            parents = row["builds_on"].split(_LIST_SEP) if row["builds_on"] else []
            if finding_id in parents:
                count += 1
        return count

    def get_earned_significance(self, finding_id: str) -> float:
        """Compute earned significance for a single finding."""
        row = self.conn.execute(
            "SELECT significance FROM findings WHERE id = ?", (finding_id,)
        ).fetchone()
        if row is None:
            return 0.0
        return compute_earned_significance(row["significance"], self.get_adoption_count(finding_id))

    def _enrich_with_earned_significance(
        self, results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Add adoption_count and earned_significance to search results, then re-sort."""
        for r in results:
            count = self.get_adoption_count(r["id"])
            r["adoption_count"] = count
            r["earned_significance"] = compute_earned_significance(r["significance"], count)
        results.sort(key=lambda r: r["earned_significance"], reverse=True)
        return results

    def stats(self) -> dict[str, Any]:
        """Return summary statistics about the index."""
        total = self.conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
        directions = self.conn.execute("SELECT DISTINCT direction FROM findings").fetchall()
        agents = self.conn.execute("SELECT DISTINCT agent_id FROM findings").fetchall()
        return {
            "total_findings": total,
            "directions": [r["direction"] for r in directions],
            "agents": [r["agent_id"] for r in agents],
        }

    def clear(self) -> None:
        """Clear the entire index."""
        self.conn.execute("DELETE FROM finding_metrics")
        self.conn.execute("DELETE FROM findings")
        self.conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)
