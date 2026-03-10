"""Unit tests for SporeIndex in src/spore/index.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from spore.index import SporeIndex, compute_earned_significance
from spore.models import Evidence, Finding, FindingStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_finding(
    claim: str = "test claim",
    direction: str = "attention",
    agent_id: str = "agent-1",
    significance: float = 0.5,
    builds_on: list[str] | None = None,
    metrics: dict[str, float] | None = None,
    applicability: list[str] | None = None,
    status: FindingStatus = FindingStatus.PUBLISHED,
) -> Finding:
    return Finding(
        experiment_id="exp-test",
        agent_id=agent_id,
        direction=direction,
        claim=claim,
        significance=significance,
        builds_on=builds_on or [],
        applicability=applicability or [],
        status=status,
        evidence=Evidence(metrics=metrics or {}),
    )


@pytest.fixture
def index(tmp_path: Path) -> SporeIndex:
    return SporeIndex(tmp_path / "test.db")


# ---------------------------------------------------------------------------
# add_finding / remove_finding
# ---------------------------------------------------------------------------


class TestAddRemoveFinding:
    def test_add_finding(self, index):
        f = make_finding(claim="hello world")
        index.add_finding(f)
        results = index.search()
        assert len(results) == 1
        assert results[0]["id"] == f.id

    def test_add_finding_upsert(self, index):
        f = make_finding(claim="original")
        index.add_finding(f)
        # Modify significance and re-add
        f.significance = 0.9
        index.add_finding(f)
        results = index.search()
        assert len(results) == 1
        assert results[0]["significance"] == 0.9

    def test_remove_finding(self, index):
        f = make_finding()
        index.add_finding(f)
        index.remove_finding(f.id)
        results = index.search()
        assert results == []

    def test_remove_nonexistent_is_safe(self, index):
        index.remove_finding("f-nonexistent")  # Should not raise

    def test_add_finding_indexes_metrics(self, index):
        f = make_finding(metrics={"val_bpb": 0.45, "delta": -0.02})
        index.add_finding(f)
        metrics = index.get_metrics(f.id)
        assert metrics["val_bpb"] == pytest.approx(0.45)
        assert metrics["delta"] == pytest.approx(-0.02)

    def test_add_finding_replaces_metrics(self, index):
        f = make_finding(metrics={"loss": 1.0})
        index.add_finding(f)
        f.evidence.metrics = {"loss": 0.5, "acc": 0.9}
        index.add_finding(f)
        metrics = index.get_metrics(f.id)
        assert metrics["loss"] == pytest.approx(0.5)
        assert "acc" in metrics


# ---------------------------------------------------------------------------
# search — basic filters
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_all(self, index):
        index.add_finding(make_finding(claim="a"))
        index.add_finding(make_finding(claim="b"))
        results = index.search()
        assert len(results) == 2

    def test_search_filter_direction(self, index):
        index.add_finding(make_finding(claim="a", direction="attention"))
        index.add_finding(make_finding(claim="b", direction="memory"))
        results = index.search(direction="attention")
        assert len(results) == 1
        assert results[0]["direction"] == "attention"

    def test_search_direction_substring(self, index):
        index.add_finding(make_finding(direction="attention-variants"))
        results = index.search(direction="attention")
        assert len(results) == 1

    def test_search_filter_agent_id(self, index):
        index.add_finding(make_finding(agent_id="agent-1"))
        index.add_finding(make_finding(agent_id="agent-2"))
        results = index.search(agent_id="agent-1")
        assert len(results) == 1
        assert results[0]["agent_id"] == "agent-1"

    def test_search_filter_significance(self, index):
        index.add_finding(make_finding(significance=0.3))
        index.add_finding(make_finding(significance=0.7))
        index.add_finding(make_finding(significance=0.9))
        results = index.search(min_significance=0.6)
        assert len(results) == 2
        for r in results:
            assert r["significance"] >= 0.6

    def test_search_excludes_retracted(self, index):
        index.add_finding(make_finding(claim="published"))
        index.add_finding(make_finding(claim="retracted", status=FindingStatus.RETRACTED))
        results = index.search()
        assert len(results) == 1
        assert results[0]["claim"] == "published"

    def test_search_limit(self, index):
        for i in range(10):
            index.add_finding(make_finding(claim=f"claim {i}"))
        results = index.search(limit=3)
        assert len(results) == 3

    def test_search_ordered_by_significance(self, index):
        index.add_finding(make_finding(claim="low", significance=0.2))
        index.add_finding(make_finding(claim="high", significance=0.9))
        results = index.search()
        assert results[0]["significance"] >= results[1]["significance"]


# ---------------------------------------------------------------------------
# search — metric filters
# ---------------------------------------------------------------------------


class TestSearchMetricFilters:
    def test_filter_by_metric_name(self, index):
        f1 = make_finding(claim="has val_bpb", metrics={"val_bpb": 0.45})
        f2 = make_finding(claim="no val_bpb", metrics={"loss": 1.0})
        index.add_finding(f1)
        index.add_finding(f2)
        results = index.search(metric_name="val_bpb")
        assert len(results) == 1
        assert results[0]["id"] == f1.id

    def test_filter_metric_max(self, index):
        f1 = make_finding(claim="low", metrics={"loss": 0.3})
        f2 = make_finding(claim="high", metrics={"loss": 0.9})
        index.add_finding(f1)
        index.add_finding(f2)
        results = index.search(metric_name="loss", metric_max=0.5)
        assert len(results) == 1
        assert results[0]["id"] == f1.id

    def test_filter_metric_min(self, index):
        f1 = make_finding(claim="low", metrics={"acc": 0.3})
        f2 = make_finding(claim="high", metrics={"acc": 0.9})
        index.add_finding(f1)
        index.add_finding(f2)
        results = index.search(metric_name="acc", metric_min=0.7)
        assert len(results) == 1
        assert results[0]["id"] == f2.id

    def test_filter_metric_range(self, index):
        for val in [0.1, 0.4, 0.7, 0.95]:
            index.add_finding(make_finding(claim=f"val {val}", metrics={"score": val}))
        results = index.search(metric_name="score", metric_min=0.3, metric_max=0.8)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Full-text search
# ---------------------------------------------------------------------------


class TestFullTextSearch:
    def test_fts_by_claim(self, index):
        f1 = make_finding(claim="attention mechanism reduces memory overhead")
        f2 = make_finding(claim="gradient checkpointing saves GPU memory")
        index.add_finding(f1)
        index.add_finding(f2)
        results = index.search(query="attention")
        ids = [r["id"] for r in results]
        assert f1.id in ids

    def test_fts_by_direction(self, index):
        f1 = make_finding(claim="a", direction="efficient-attention")
        f2 = make_finding(claim="b", direction="memory-compression")
        index.add_finding(f1)
        index.add_finding(f2)
        results = index.search(query="efficient")
        ids = [r["id"] for r in results]
        assert f1.id in ids

    def test_fts_excludes_retracted(self, index):
        f1 = make_finding(claim="attention mechanism works well")
        f2 = make_finding(claim="attention mechanism is flawed", status=FindingStatus.RETRACTED)
        index.add_finding(f1)
        index.add_finding(f2)
        results = index.search(query="attention")
        assert len(results) == 1
        assert results[0]["id"] == f1.id


# ---------------------------------------------------------------------------
# get_metrics
# ---------------------------------------------------------------------------


class TestGetMetrics:
    def test_returns_metrics(self, index):
        f = make_finding(metrics={"val_bpb": 0.45, "delta": -0.02})
        index.add_finding(f)
        metrics = index.get_metrics(f.id)
        assert set(metrics.keys()) == {"val_bpb", "delta"}

    def test_returns_empty_for_no_metrics(self, index):
        f = make_finding()
        index.add_finding(f)
        assert index.get_metrics(f.id) == {}

    def test_returns_empty_for_missing_finding(self, index):
        assert index.get_metrics("f-nonexistent") == {}


# ---------------------------------------------------------------------------
# get_lineage
# ---------------------------------------------------------------------------


class TestGetLineage:
    def test_lineage_single_parent(self, index):
        parent = make_finding(claim="parent finding")
        child = make_finding(claim="child finding", builds_on=[parent.id])
        index.add_finding(parent)
        index.add_finding(child)
        lineage = index.get_lineage(child.id)
        assert len(lineage) == 1
        assert lineage[0]["id"] == parent.id

    def test_lineage_chain(self, index):
        grandparent = make_finding(claim="grandparent")
        parent = make_finding(claim="parent", builds_on=[grandparent.id])
        child = make_finding(claim="child", builds_on=[parent.id])
        index.add_finding(grandparent)
        index.add_finding(parent)
        index.add_finding(child)
        lineage = index.get_lineage(child.id)
        ids = [e["id"] for e in lineage]
        assert parent.id in ids
        assert grandparent.id in ids

    def test_lineage_no_parents(self, index):
        f = make_finding()
        index.add_finding(f)
        lineage = index.get_lineage(f.id)
        assert lineage == []

    def test_lineage_excludes_self(self, index):
        f = make_finding()
        index.add_finding(f)
        lineage = index.get_lineage(f.id)
        ids = [e["id"] for e in lineage]
        assert f.id not in ids


# ---------------------------------------------------------------------------
# get_dependents
# ---------------------------------------------------------------------------


class TestGetDependents:
    def test_get_dependents(self, index):
        parent = make_finding(claim="root")
        child1 = make_finding(claim="child1", builds_on=[parent.id])
        child2 = make_finding(claim="child2", builds_on=[parent.id])
        index.add_finding(parent)
        index.add_finding(child1)
        index.add_finding(child2)
        deps = index.get_dependents(parent.id)
        dep_ids = [d["id"] for d in deps]
        assert child1.id in dep_ids
        assert child2.id in dep_ids

    def test_get_dependents_none(self, index):
        f = make_finding()
        index.add_finding(f)
        assert index.get_dependents(f.id) == []


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_stats_empty(self, index):
        s = index.stats()
        assert s["total_findings"] == 0
        assert s["directions"] == []
        assert s["agents"] == []

    def test_stats_counts(self, index):
        index.add_finding(make_finding(direction="alpha", agent_id="agent-1"))
        index.add_finding(make_finding(direction="beta", agent_id="agent-2"))
        s = index.stats()
        assert s["total_findings"] == 2
        assert set(s["directions"]) == {"alpha", "beta"}
        assert set(s["agents"]) == {"agent-1", "agent-2"}

    def test_stats_distinct(self, index):
        index.add_finding(make_finding(claim="a", direction="alpha", agent_id="agent-1"))
        index.add_finding(make_finding(claim="b", direction="alpha", agent_id="agent-1"))
        s = index.stats()
        assert s["total_findings"] == 2
        assert len(s["directions"]) == 1
        assert len(s["agents"]) == 1


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_removes_all(self, index):
        index.add_finding(make_finding(claim="a", metrics={"loss": 0.5}))
        index.add_finding(make_finding(claim="b", metrics={"acc": 0.9}))
        index.clear()
        assert index.search() == []
        s = index.stats()
        assert s["total_findings"] == 0

    def test_clear_removes_metrics(self, index):
        f = make_finding(metrics={"val_bpb": 0.45})
        index.add_finding(f)
        index.clear()
        assert index.get_metrics(f.id) == {}

    def test_clear_then_add(self, index):
        index.add_finding(make_finding(claim="old"))
        index.clear()
        index.add_finding(make_finding(claim="new"))
        results = index.search()
        assert len(results) == 1
        assert results[0]["claim"] == "new"


# ---------------------------------------------------------------------------
# compute_earned_significance (unit function)
# ---------------------------------------------------------------------------


class TestComputeEarnedSignificance:
    def test_zero_adoptions_returns_self_reported(self):
        assert compute_earned_significance(0.5, 0) == 0.5

    def test_negative_adoptions_returns_self_reported(self):
        assert compute_earned_significance(0.7, -1) == 0.7

    def test_one_adoption_adds_bonus(self):
        result = compute_earned_significance(0.5, 1)
        assert result > 0.5
        assert result == pytest.approx(0.6, abs=0.01)

    def test_three_adoptions(self):
        result = compute_earned_significance(0.5, 3)
        assert result == pytest.approx(0.7, abs=0.01)

    def test_seven_adoptions(self):
        result = compute_earned_significance(0.5, 7)
        assert result == pytest.approx(0.8, abs=0.01)

    def test_fifteen_adoptions(self):
        result = compute_earned_significance(0.5, 15)
        assert result == pytest.approx(0.9, abs=0.01)

    def test_capped_at_one(self):
        result = compute_earned_significance(0.9, 1000)
        assert result == 1.0

    def test_low_self_reported_with_high_adoption(self):
        result = compute_earned_significance(0.1, 31)
        assert result == pytest.approx(0.6, abs=0.01)

    def test_zero_self_reported_zero_adoptions(self):
        assert compute_earned_significance(0.0, 0) == 0.0

    def test_one_self_reported_zero_adoptions(self):
        assert compute_earned_significance(1.0, 0) == 1.0

    def test_one_self_reported_with_adoptions(self):
        assert compute_earned_significance(1.0, 10) == 1.0

    def test_monotonically_increasing(self):
        """More adoptions always means equal or higher earned significance."""
        prev = 0.0
        for n in range(20):
            cur = compute_earned_significance(0.5, n)
            assert cur >= prev
            prev = cur


# ---------------------------------------------------------------------------
# get_adoption_count
# ---------------------------------------------------------------------------


class TestGetAdoptionCount:
    def test_no_adopters(self, index):
        f = make_finding(claim="root")
        index.add_finding(f)
        assert index.get_adoption_count(f.id) == 0

    def test_one_adopter(self, index):
        parent = make_finding(claim="parent")
        child = make_finding(claim="child", builds_on=[parent.id])
        index.add_finding(parent)
        index.add_finding(child)
        assert index.get_adoption_count(parent.id) == 1

    def test_multiple_adopters(self, index):
        parent = make_finding(claim="root finding")
        child1 = make_finding(claim="child 1", builds_on=[parent.id])
        child2 = make_finding(claim="child 2", builds_on=[parent.id])
        child3 = make_finding(claim="child 3", builds_on=[parent.id])
        index.add_finding(parent)
        index.add_finding(child1)
        index.add_finding(child2)
        index.add_finding(child3)
        assert index.get_adoption_count(parent.id) == 3

    def test_retracted_adopters_not_counted(self, index):
        parent = make_finding(claim="root")
        child = make_finding(
            claim="retracted child",
            builds_on=[parent.id],
            status=FindingStatus.RETRACTED,
        )
        index.add_finding(parent)
        index.add_finding(child)
        assert index.get_adoption_count(parent.id) == 0

    def test_nonexistent_finding(self, index):
        assert index.get_adoption_count("f-nonexistent") == 0

    def test_multi_parent_counted_once(self, index):
        """A finding that builds on two parents counts as one adoption for each."""
        parent_a = make_finding(claim="parent a")
        parent_b = make_finding(claim="parent b")
        child = make_finding(claim="dual parent", builds_on=[parent_a.id, parent_b.id])
        index.add_finding(parent_a)
        index.add_finding(parent_b)
        index.add_finding(child)
        assert index.get_adoption_count(parent_a.id) == 1
        assert index.get_adoption_count(parent_b.id) == 1


# ---------------------------------------------------------------------------
# get_earned_significance
# ---------------------------------------------------------------------------


class TestGetEarnedSignificance:
    def test_no_adopters(self, index):
        f = make_finding(claim="standalone", significance=0.7)
        index.add_finding(f)
        assert index.get_earned_significance(f.id) == 0.7

    def test_with_adopters(self, index):
        parent = make_finding(claim="root", significance=0.5)
        child = make_finding(claim="child", builds_on=[parent.id])
        index.add_finding(parent)
        index.add_finding(child)
        earned = index.get_earned_significance(parent.id)
        assert earned > 0.5
        assert earned == pytest.approx(0.6, abs=0.01)

    def test_nonexistent_finding_returns_zero(self, index):
        assert index.get_earned_significance("f-nonexistent") == 0.0


# ---------------------------------------------------------------------------
# search results include earned significance
# ---------------------------------------------------------------------------


class TestSearchEarnedSignificance:
    def test_search_includes_earned_fields(self, index):
        f = make_finding(claim="test", significance=0.5)
        index.add_finding(f)
        results = index.search()
        assert len(results) == 1
        assert "earned_significance" in results[0]
        assert "adoption_count" in results[0]
        assert results[0]["adoption_count"] == 0
        assert results[0]["earned_significance"] == 0.5

    def test_search_earned_significance_with_adoption(self, index):
        parent = make_finding(claim="parent finding", significance=0.5)
        child = make_finding(claim="child finding", builds_on=[parent.id])
        index.add_finding(parent)
        index.add_finding(child)
        results = index.search()
        parent_result = next(r for r in results if r["id"] == parent.id)
        assert parent_result["adoption_count"] == 1
        assert parent_result["earned_significance"] > 0.5

    def test_search_sorted_by_earned_significance(self, index):
        """A low-self-reported finding with many adoptions should rank above a
        high-self-reported finding with no adoptions (when earned > raw)."""
        popular = make_finding(claim="popular", significance=0.4)
        niche = make_finding(claim="niche", significance=0.6)
        # Give 'popular' 7 adopters (bonus ~0.3 → earned ~0.7)
        index.add_finding(popular)
        index.add_finding(niche)
        for i in range(7):
            adopter = make_finding(claim=f"adopter {i}", builds_on=[popular.id])
            index.add_finding(adopter)
        results = index.search()
        # popular (earned ~0.7) should rank above niche (earned 0.6)
        ids = [r["id"] for r in results]
        assert ids.index(popular.id) < ids.index(niche.id)

    def test_fts_search_includes_earned_fields(self, index):
        f = make_finding(claim="attention mechanism", significance=0.6)
        index.add_finding(f)
        results = index.search(query="attention")
        assert len(results) == 1
        assert "earned_significance" in results[0]
        assert "adoption_count" in results[0]
