"""SporeRepo — the main interface for interacting with Spore.

SporeRepo wraps a Git repository with Spore protocol capabilities:
publishing findings, managing experiments, and discovering results
from other agents.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import git

from spore.federation import FederationRegistry
from spore.index import SporeIndex
from spore.models import (
    Direction,
    Evidence,
    Experiment,
    ExperimentStatus,
    Finding,
    FindingStatus,
    SporeConfig,
)

logger = logging.getLogger("spore")

SPORE_DIR = ".spore"
FINDINGS_DIR = "findings"
EXPERIMENTS_DIR = "experiments"
DIRECTIONS_DIR = "directions"
CONFIG_FILE = "config.yaml"
INDEX_FILE = "index.db"


class SporeError(Exception):
    """Base exception for Spore operations."""


class SporeRepo:
    """High-level interface for a Spore-enabled Git repository.

    Usage:
        repo = SporeRepo("/path/to/repo")
        repo.init(agent_id="agent-47")

        exp = repo.start_experiment(
            direction="attention-variants",
            hypothesis="MQA reduces memory without hurting quality",
        )

        finding = repo.publish_finding(
            experiment_id=exp.id,
            direction="attention-variants",
            claim="MQA with 4 KV heads drops val_bpb by 0.02",
            metrics={"val_bpb": 0.4523, "delta": -0.0201},
        )

        results = repo.discover(direction="attention")
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.spore_dir = self.path / SPORE_DIR

        try:
            self.git_repo = git.Repo(self.path)
        except git.InvalidGitRepositoryError:
            self.git_repo = git.Repo.init(self.path)

        self._index: SporeIndex | None = None
        self._config: SporeConfig | None = None
        self._federation: FederationRegistry | None = None

    @property
    def is_initialized(self) -> bool:
        return (self.spore_dir / CONFIG_FILE).exists()

    @property
    def config(self) -> SporeConfig:
        if self._config is None:
            config_path = self.spore_dir / CONFIG_FILE
            if config_path.exists():
                self._config = SporeConfig.from_yaml(config_path.read_text())
            else:
                self._config = SporeConfig()
        return self._config

    @property
    def agent_id(self) -> str:
        return self.config.agent_id or os.environ.get("SPORE_AGENT_ID", "unknown")

    @property
    def index(self) -> SporeIndex:
        if self._index is None:
            self._index = SporeIndex(self.spore_dir / INDEX_FILE)
        return self._index

    @property
    def federation(self) -> FederationRegistry:
        if self._federation is None:
            self._federation = FederationRegistry(self.spore_dir)
        return self._federation

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def init(self, agent_id: str | None = None, repo_name: str | None = None) -> SporeConfig:
        """Initialize this repository for Spore.

        Creates the .spore/ directory structure and config file.
        """
        if self.is_initialized:
            raise SporeError("Repository is already initialized for Spore")

        for subdir in (FINDINGS_DIR, EXPERIMENTS_DIR, DIRECTIONS_DIR):
            (self.spore_dir / subdir).mkdir(parents=True, exist_ok=True)

        # Write .gitignore for the index db
        gitignore = self.spore_dir / ".gitignore"
        gitignore.write_text("index.db\n.cache/\n")

        config = SporeConfig(
            agent_id=agent_id,
            repo_name=repo_name or self.path.name,
        )
        self._write_config(config)
        self._config = config

        # Stage and commit
        self.git_repo.index.add(
            [
                str(self.spore_dir / CONFIG_FILE),
                str(self.spore_dir / ".gitignore"),
            ]
        )
        self._try_commit("spore: initialize repository")

        return config

    # ------------------------------------------------------------------
    # Experiments
    # ------------------------------------------------------------------

    def start_experiment(
        self,
        direction: str,
        hypothesis: str,
        builds_on: list[str] | None = None,
        config: dict[str, Any] | None = None,
        create_branch: bool = True,
    ) -> Experiment:
        """Start a new research experiment."""
        self._ensure_initialized()

        experiment = Experiment(
            agent_id=self.agent_id,
            direction=direction,
            hypothesis=hypothesis,
            builds_on=builds_on or [],
            config=config,
        )

        # Ensure the direction exists
        self._ensure_direction(direction)

        # Write experiment manifest
        exp_path = self.spore_dir / EXPERIMENTS_DIR / f"{experiment.id}.yaml"
        exp_path.write_text(experiment.to_yaml())

        # Create branch
        if create_branch:
            try:
                self.git_repo.create_head(experiment.branch)
                self.git_repo.heads[experiment.branch].checkout()
            except (git.GitCommandError, OSError) as e:
                logger.debug("Could not create/checkout branch %s: %s", experiment.branch, e)

        # Commit the experiment manifest
        self.git_repo.index.add([str(exp_path)])
        self._try_commit(
            f"spore: start experiment {experiment.id}\n\n"
            f"Direction: {direction}\n"
            f"Hypothesis: {hypothesis}"
        )

        return experiment

    def complete_experiment(self, experiment_id: str) -> Experiment:
        """Mark an experiment as completed."""
        experiment = self.get_experiment(experiment_id)
        experiment.status = ExperimentStatus.COMPLETED
        experiment.completed = datetime.now(UTC)

        exp_path = self.spore_dir / EXPERIMENTS_DIR / f"{experiment.id}.yaml"
        exp_path.write_text(experiment.to_yaml())

        self.git_repo.index.add([str(exp_path)])
        self._try_commit(f"spore: complete experiment {experiment.id}")

        return experiment

    def abandon_experiment(self, experiment_id: str) -> Experiment:
        """Mark an experiment as abandoned."""
        experiment = self.get_experiment(experiment_id)
        experiment.status = ExperimentStatus.ABANDONED
        experiment.completed = datetime.now(UTC)

        exp_path = self.spore_dir / EXPERIMENTS_DIR / f"{experiment.id}.yaml"
        exp_path.write_text(experiment.to_yaml())

        self.git_repo.index.add([str(exp_path)])
        self._try_commit(f"spore: abandon experiment {experiment.id}")

        return experiment

    def get_experiment(self, experiment_id: str) -> Experiment:
        """Load an experiment by ID."""
        exp_path = self.spore_dir / EXPERIMENTS_DIR / f"{experiment_id}.yaml"
        if not exp_path.exists():
            raise SporeError(f"Experiment not found: {experiment_id}")
        return Experiment.from_yaml(exp_path.read_text())

    def list_experiments(
        self,
        direction: str | None = None,
        status: ExperimentStatus | None = None,
    ) -> list[Experiment]:
        """List all experiments, optionally filtered."""
        experiments = []
        exp_dir = self.spore_dir / EXPERIMENTS_DIR
        if not exp_dir.exists():
            return experiments

        for f in sorted(exp_dir.glob("*.yaml")):
            exp = Experiment.from_yaml(f.read_text())
            if direction and exp.direction != direction:
                continue
            if status and exp.status != status:
                continue
            experiments.append(exp)

        return experiments

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    def publish_finding(
        self,
        experiment_id: str | None = None,
        direction: str = "",
        claim: str = "",
        hypothesis: str | None = None,
        metrics: dict[str, float] | None = None,
        baseline: dict[str, Any] | None = None,
        artifacts: list[dict[str, str]] | None = None,
        builds_on: list[str] | None = None,
        applicability: list[str] | None = None,
        significance: float = 0.5,
        notes: str | None = None,
    ) -> Finding:
        """Publish a research finding.

        This is the core operation in Spore — an agent declares what it
        discovered, with structured evidence.
        """
        self._ensure_initialized()

        if not claim.strip():
            raise SporeError("Finding claim cannot be empty")
        if not direction.strip():
            raise SporeError("Finding direction cannot be empty")

        # Build artifact objects
        from spore.models import Artifact, ArtifactType

        artifact_objs = []
        for a in artifacts or []:
            artifact_objs.append(Artifact(type=ArtifactType(a.get("type", "commit")), ref=a["ref"]))

        # Auto-add current commit as artifact
        try:
            head_sha = self.git_repo.head.commit.hexsha[:12]
            artifact_objs.append(Artifact(type=ArtifactType.COMMIT, ref=head_sha))
        except (ValueError, TypeError):
            pass  # No HEAD commit yet (empty repo)

        evidence = Evidence(
            metrics=metrics or {},
            baseline=baseline,
            artifacts=artifact_objs,
            notes=notes,
        )

        # Default experiment_id if none given
        if not experiment_id:
            experiments = self.list_experiments(
                direction=direction, status=ExperimentStatus.RUNNING
            )
            experiment_id = experiments[-1].id if experiments else "standalone"

        finding = Finding(
            experiment_id=experiment_id,
            agent_id=self.agent_id,
            direction=direction,
            claim=claim,
            hypothesis=hypothesis,
            evidence=evidence,
            builds_on=builds_on or [],
            applicability=applicability or [],
            significance=significance,
        )

        # Write manifest
        finding_path = self.spore_dir / FINDINGS_DIR / f"{finding.id}.yaml"
        finding_path.write_text(finding.to_yaml())

        # Update experiment
        if experiment_id != "standalone":
            try:
                exp = self.get_experiment(experiment_id)
                if finding.id not in exp.findings:
                    exp.findings.append(finding.id)
                    exp_path = self.spore_dir / EXPERIMENTS_DIR / f"{exp.id}.yaml"
                    exp_path.write_text(exp.to_yaml())
                    self.git_repo.index.add([str(exp_path)])
            except SporeError:
                pass

        # Index the finding
        self.index.add_finding(finding, source_branch=self._current_branch())

        # Commit
        self.git_repo.index.add([str(finding_path)])
        self._try_commit(f"spore: publish finding {finding.id}\n\n{claim}")

        return finding

    def get_finding(self, finding_id: str) -> Finding:
        """Load a finding by ID."""
        finding_path = self.spore_dir / FINDINGS_DIR / f"{finding_id}.yaml"
        if not finding_path.exists():
            raise SporeError(f"Finding not found: {finding_id}")
        return Finding.from_yaml(finding_path.read_text())

    def list_findings(
        self,
        direction: str | None = None,
        status: FindingStatus | None = None,
    ) -> list[Finding]:
        """List all findings in the current branch."""
        findings = []
        findings_dir = self.spore_dir / FINDINGS_DIR
        if not findings_dir.exists():
            return findings

        for f in sorted(findings_dir.glob("*.yaml")):
            finding = Finding.from_yaml(f.read_text())
            if direction and finding.direction != direction:
                continue
            if status and finding.status != status:
                continue
            findings.append(finding)

        return findings

    def retract_finding(self, finding_id: str) -> Finding:
        """Retract a finding (mark as no longer valid)."""
        finding = self.get_finding(finding_id)
        finding.status = FindingStatus.RETRACTED

        finding_path = self.spore_dir / FINDINGS_DIR / f"{finding.id}.yaml"
        finding_path.write_text(finding.to_yaml())
        self.index.add_finding(finding)

        self.git_repo.index.add([str(finding_path)])
        self._try_commit(f"spore: retract finding {finding.id}")

        return finding

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(
        self,
        query: str | None = None,
        direction: str | None = None,
        agent_id: str | None = None,
        metric_name: str | None = None,
        metric_max: float | None = None,
        metric_min: float | None = None,
        min_significance: float | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Discover findings using the local index.

        This searches the SQLite index, which is fast but only includes
        findings that have been indexed locally. Use `index_remote()` to
        pull findings from other branches.
        """
        results = self.index.search(
            query=query,
            direction=direction,
            agent_id=agent_id,
            metric_name=metric_name,
            metric_max=metric_max,
            metric_min=metric_min,
            min_significance=min_significance,
            limit=limit,
        )

        # Attach metrics to each result
        for r in results:
            r["metrics"] = self.index.get_metrics(r["id"])

        return results

    def discover_remote(
        self,
        direction: str | None = None,
        limit: int = 50,
    ) -> list[Finding]:
        """Discover findings from remote branches.

        Fetches the latest refs and scans .spore/findings/ directories
        across all remote branches.
        """
        findings: list[Finding] = []
        seen_ids: set[str] = set()

        # Fetch latest
        try:
            for remote in self.git_repo.remotes:
                remote.fetch()
        except Exception:
            pass

        # Scan all refs (remote and local branches, excluding current)
        for ref in self.git_repo.refs:
            ref_name = str(ref)
            # Skip the current branch (we already have its findings locally)
            if ref_name == self._current_branch():
                continue
            # Skip tags and other non-branch refs
            if not (ref_name.startswith("origin/") or ref_name.startswith("spore/")):
                continue

            try:
                tree = ref.commit.tree
                spore_tree = tree[SPORE_DIR] / FINDINGS_DIR
                for blob in spore_tree.blobs:
                    if not blob.name.endswith(".yaml"):
                        continue
                    data = blob.data_stream.read().decode("utf-8")
                    finding = Finding.from_yaml(data)
                    if finding.id not in seen_ids:
                        if direction and direction.lower() not in finding.direction.lower():
                            continue
                        seen_ids.add(finding.id)
                        findings.append(finding)
                        # Add to local index
                        self.index.add_finding(finding, source_branch=ref_name)
            except (KeyError, ValueError):
                continue
            except Exception as e:
                logger.debug("Error scanning ref %s: %s", ref_name, e)
                continue

        findings.sort(key=lambda f: f.significance, reverse=True)
        return findings[:limit]

    # ------------------------------------------------------------------
    # Directions
    # ------------------------------------------------------------------

    def create_direction(
        self,
        name: str,
        description: str,
        parent_directions: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> Direction:
        """Create a new research direction."""
        self._ensure_initialized()

        direction = Direction(
            name=name,
            description=description,
            parent_directions=parent_directions or [],
            tags=tags or [],
        )

        dir_path = self.spore_dir / DIRECTIONS_DIR / f"{direction.id}.yaml"
        dir_path.write_text(direction.to_yaml())

        self.git_repo.index.add([str(dir_path)])
        self._try_commit(f"spore: create direction '{name}'")

        return direction

    def list_directions(self) -> list[Direction]:
        """List all research directions."""
        directions = []
        dir_dir = self.spore_dir / DIRECTIONS_DIR
        if not dir_dir.exists():
            return directions

        for f in sorted(dir_dir.glob("*.yaml")):
            directions.append(Direction.from_yaml(f.read_text()))

        return directions

    # ------------------------------------------------------------------
    # Adoption
    # ------------------------------------------------------------------

    def adopt_finding(
        self,
        finding_id: str,
        experiment_id: str | None = None,
    ) -> dict[str, str]:
        """Record that an experiment is building on a finding.

        This creates a lineage link. The agent reads the finding,
        understands the insight, and applies it in its own context.
        Spore tracks the relationship but doesn't automate the
        understanding — that's what the AI agent is for.
        """
        self._ensure_initialized()

        # Find the target experiment
        if not experiment_id:
            running = self.list_experiments(status=ExperimentStatus.RUNNING)
            if not running:
                raise SporeError("No running experiment to adopt into")
            experiment_id = running[-1].id

        exp = self.get_experiment(experiment_id)
        if finding_id not in exp.builds_on:
            exp.builds_on.append(finding_id)
            exp_path = self.spore_dir / EXPERIMENTS_DIR / f"{exp.id}.yaml"
            exp_path.write_text(exp.to_yaml())

            self.git_repo.index.add([str(exp_path)])
            self._try_commit(f"spore: adopt finding {finding_id} into {experiment_id}")

        return {"experiment_id": experiment_id, "finding_id": finding_id}

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def rebuild_index(self) -> int:
        """Rebuild the local index from .spore/findings/ manifests."""
        self.index.clear()
        count = 0
        findings_dir = self.spore_dir / FINDINGS_DIR
        if findings_dir.exists():
            for f in findings_dir.glob("*.yaml"):
                finding = Finding.from_yaml(f.read_text())
                self.index.add_finding(finding, source_branch=self._current_branch())
                count += 1
        return count

    def status(self) -> dict[str, Any]:
        """Get an overview of the repository's Spore state."""
        experiments = self.list_experiments()
        findings = self.list_findings()
        directions = self.list_directions()

        running = [e for e in experiments if e.status == ExperimentStatus.RUNNING]
        completed = [e for e in experiments if e.status == ExperimentStatus.COMPLETED]

        return {
            "initialized": self.is_initialized,
            "agent_id": self.agent_id,
            "branch": self._current_branch(),
            "experiments": {
                "total": len(experiments),
                "running": len(running),
                "completed": len(completed),
            },
            "findings": {
                "total": len(findings),
                "published": len([f for f in findings if f.status == FindingStatus.PUBLISHED]),
            },
            "directions": len(directions),
        }

    # ------------------------------------------------------------------
    # Federation
    # ------------------------------------------------------------------

    def add_peer(
        self,
        url: str,
        name: str | None = None,
        directions: list[str] | None = None,
    ) -> dict[str, str]:
        """Register a peer repository for federated discovery."""
        self._ensure_initialized()
        peer = self.federation.add_peer(url, name=name, directions=directions)

        # Stage federation file
        fed_path = self.spore_dir / "federation.yaml"
        if fed_path.exists():
            self.git_repo.index.add([str(fed_path)])
            self._try_commit(f"spore: add federation peer '{peer.name}'")

        return {"id": peer.id, "name": peer.name, "url": peer.url}

    def remove_peer(self, url: str) -> bool:
        """Remove a federation peer by URL."""
        self._ensure_initialized()
        removed = self.federation.remove_peer(url)
        if removed:
            fed_path = self.spore_dir / "federation.yaml"
            if fed_path.exists():
                self.git_repo.index.add([str(fed_path)])
                self._try_commit(f"spore: remove federation peer '{url}'")
        return removed

    def list_peers(self) -> list[dict[str, Any]]:
        """List all federation peers."""
        return [p.to_dict() for p in self.federation.list_peers()]

    def discover_federated(
        self,
        direction: str | None = None,
        limit: int = 50,
    ) -> list[Finding]:
        """Discover findings across all federated peer repositories.

        Syncs peer repos (shallow clone/fetch), scans their findings,
        indexes them locally, and returns results sorted by significance.
        """
        self._ensure_initialized()
        return self.federation.discover_all(self.index, direction=direction, limit=limit)

    def sync_peers(self) -> dict[str, str]:
        """Sync all federation peers (fetch latest)."""
        self._ensure_initialized()
        results = self.federation.sync_all()
        return {name: str(path) for name, path in results.items()}

    # ------------------------------------------------------------------
    # Watch
    # ------------------------------------------------------------------

    def watch(
        self,
        callback: Any,
        direction: str | None = None,
        min_significance: float | None = None,
        interval: float = 5.0,
    ) -> Any:
        """Start watching for new findings.

        Returns the SporeWatcher instance. Call watcher.stop() to stop.

        Args:
            callback: Called with each new Finding.
            direction: Only watch this direction (substring match).
            min_significance: Only trigger above this significance.
            interval: Poll interval in seconds.
        """
        from spore.watch import SporeWatcher

        watcher = SporeWatcher(self, interval=interval)
        watcher.on_finding(callback, direction=direction, min_significance=min_significance)
        watcher.start()
        return watcher

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_initialized(self) -> None:
        if not self.is_initialized:
            raise SporeError("Repository not initialized for Spore. Run 'spore init' first.")

    def _ensure_direction(self, name: str) -> None:
        """Create a direction if it doesn't already exist."""
        dir_dir = self.spore_dir / DIRECTIONS_DIR
        existing = [Direction.from_yaml(f.read_text()) for f in dir_dir.glob("*.yaml")]
        if not any(d.name == name for d in existing):
            self.create_direction(name=name, description=f"Auto-created direction: {name}")

    def _write_config(self, config: SporeConfig) -> None:
        config_path = self.spore_dir / CONFIG_FILE
        config_path.write_text(config.to_yaml())
        self._config = config

    def _try_commit(self, message: str) -> None:
        """Attempt a git commit, logging on failure instead of silently swallowing."""
        try:
            self.git_repo.index.commit(message)
        except Exception as e:
            logger.debug("Git commit skipped: %s", e)

    def _current_branch(self) -> str:
        try:
            return str(self.git_repo.active_branch)
        except (TypeError, ValueError):
            return "HEAD"
