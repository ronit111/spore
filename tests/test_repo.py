"""Unit tests for SporeRepo in src/spore/repo.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from spore.models import ExperimentStatus, Finding, FindingStatus
from spore.repo import SporeError, SporeRepo

if TYPE_CHECKING:
    import git

# ---------------------------------------------------------------------------
# init()
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_success(self, tmp_git_repo):
        repo = SporeRepo(tmp_git_repo)
        config = repo.init(agent_id="agent-1", repo_name="test")
        assert repo.is_initialized
        assert config.agent_id == "agent-1"
        assert config.repo_name == "test"

    def test_init_creates_directory_structure(self, tmp_git_repo):
        repo = SporeRepo(tmp_git_repo)
        repo.init(agent_id="agent-1")
        spore_dir = tmp_git_repo / ".spore"
        assert (spore_dir / "findings").is_dir()
        assert (spore_dir / "experiments").is_dir()
        assert (spore_dir / "directions").is_dir()
        assert (spore_dir / "config.yaml").exists()
        assert (spore_dir / ".gitignore").exists()

    def test_init_double_init_raises(self, spore_repo):
        with pytest.raises(SporeError, match="already initialized"):
            spore_repo.init(agent_id="agent-2")

    def test_init_uses_dir_name_as_repo_name(self, tmp_git_repo):
        repo = SporeRepo(tmp_git_repo)
        config = repo.init(agent_id="agent-1")
        assert config.repo_name == tmp_git_repo.name


# ---------------------------------------------------------------------------
# Uninitialized repo errors
# ---------------------------------------------------------------------------


class TestUninitializedErrors:
    def test_start_experiment_on_uninitialized(self, tmp_git_repo):
        repo = SporeRepo(tmp_git_repo)
        with pytest.raises(SporeError, match="not initialized"):
            repo.start_experiment(direction="d", hypothesis="h", create_branch=False)

    def test_publish_finding_on_uninitialized(self, tmp_git_repo):
        repo = SporeRepo(tmp_git_repo)
        with pytest.raises(SporeError, match="not initialized"):
            repo.publish_finding(direction="d", claim="c")

    def test_create_direction_on_uninitialized(self, tmp_git_repo):
        repo = SporeRepo(tmp_git_repo)
        with pytest.raises(SporeError, match="not initialized"):
            repo.create_direction(name="n", description="d")

    def test_adopt_finding_on_uninitialized(self, tmp_git_repo):
        repo = SporeRepo(tmp_git_repo)
        with pytest.raises(SporeError, match="not initialized"):
            repo.adopt_finding(finding_id="f-abc", experiment_id="exp-xyz")


# ---------------------------------------------------------------------------
# start_experiment()
# ---------------------------------------------------------------------------


class TestStartExperiment:
    def test_creates_experiment(self, spore_repo):
        exp = spore_repo.start_experiment(
            direction="attention",
            hypothesis="MQA helps",
            create_branch=False,
        )
        assert exp.id.startswith("exp-")
        assert exp.direction == "attention"
        assert exp.hypothesis == "MQA helps"
        assert exp.status == ExperimentStatus.RUNNING

    def test_writes_manifest(self, spore_repo):
        exp = spore_repo.start_experiment(
            direction="attention", hypothesis="h", create_branch=False
        )
        exp_path = spore_repo.spore_dir / "experiments" / f"{exp.id}.yaml"
        assert exp_path.exists()

    def test_creates_direction_if_missing(self, spore_repo):
        spore_repo.start_experiment(direction="new-direction", hypothesis="h", create_branch=False)
        directions = spore_repo.list_directions()
        assert any(d.name == "new-direction" for d in directions)

    def test_with_builds_on(self, spore_repo):
        exp = spore_repo.start_experiment(
            direction="attention",
            hypothesis="h",
            builds_on=["f-abc123"],
            create_branch=False,
        )
        assert "f-abc123" in exp.builds_on

    def test_with_config(self, spore_repo):
        exp = spore_repo.start_experiment(
            direction="attention",
            hypothesis="h",
            config={"lr": 0.001},
            create_branch=False,
        )
        assert exp.config == {"lr": 0.001}


# ---------------------------------------------------------------------------
# complete_experiment() / abandon_experiment()
# ---------------------------------------------------------------------------


class TestExperimentLifecycle:
    def test_complete_experiment(self, spore_repo_with_experiment):
        repo = spore_repo_with_experiment
        exp_id = repo.list_experiments()[0].id
        exp = repo.complete_experiment(exp_id)
        assert exp.status == ExperimentStatus.COMPLETED
        assert exp.completed is not None

    def test_abandon_experiment(self, spore_repo_with_experiment):
        repo = spore_repo_with_experiment
        exp_id = repo.list_experiments()[0].id
        exp = repo.abandon_experiment(exp_id)
        assert exp.status == ExperimentStatus.ABANDONED
        assert exp.completed is not None

    def test_complete_persists_to_disk(self, spore_repo_with_experiment):
        repo = spore_repo_with_experiment
        exp_id = repo.list_experiments()[0].id
        repo.complete_experiment(exp_id)
        reloaded = repo.get_experiment(exp_id)
        assert reloaded.status == ExperimentStatus.COMPLETED

    def test_abandon_persists_to_disk(self, spore_repo_with_experiment):
        repo = spore_repo_with_experiment
        exp_id = repo.list_experiments()[0].id
        repo.abandon_experiment(exp_id)
        reloaded = repo.get_experiment(exp_id)
        assert reloaded.status == ExperimentStatus.ABANDONED


# ---------------------------------------------------------------------------
# get_experiment()
# ---------------------------------------------------------------------------


class TestGetExperiment:
    def test_get_existing_experiment(self, spore_repo_with_experiment):
        repo = spore_repo_with_experiment
        exp_id = repo.list_experiments()[0].id
        exp = repo.get_experiment(exp_id)
        assert exp.id == exp_id

    def test_get_nonexistent_raises(self, spore_repo):
        with pytest.raises(SporeError, match="Experiment not found"):
            spore_repo.get_experiment("exp-doesnotexist")


# ---------------------------------------------------------------------------
# list_experiments()
# ---------------------------------------------------------------------------


class TestListExperiments:
    def test_list_all(self, spore_repo_with_experiment):
        exps = spore_repo_with_experiment.list_experiments()
        assert len(exps) == 1

    def test_list_empty(self, spore_repo):
        assert spore_repo.list_experiments() == []

    def test_filter_by_direction(self, spore_repo):
        spore_repo.start_experiment(direction="alpha", hypothesis="h1", create_branch=False)
        spore_repo.start_experiment(direction="beta", hypothesis="h2", create_branch=False)
        results = spore_repo.list_experiments(direction="alpha")
        assert len(results) == 1
        assert results[0].direction == "alpha"

    def test_filter_by_status(self, spore_repo):
        exp = spore_repo.start_experiment(direction="alpha", hypothesis="h", create_branch=False)
        spore_repo.complete_experiment(exp.id)
        running = spore_repo.list_experiments(status=ExperimentStatus.RUNNING)
        completed = spore_repo.list_experiments(status=ExperimentStatus.COMPLETED)
        assert len(running) == 0
        assert len(completed) == 1


# ---------------------------------------------------------------------------
# publish_finding()
# ---------------------------------------------------------------------------


class TestPublishFinding:
    def test_creates_finding(self, spore_repo_with_experiment):
        repo = spore_repo_with_experiment
        exp_id = repo.list_experiments()[0].id
        finding = repo.publish_finding(
            experiment_id=exp_id,
            direction="attention-variants",
            claim="MQA is good",
            metrics={"val_bpb": 0.45},
        )
        assert finding.id.startswith("f-")
        assert finding.claim == "MQA is good"
        assert finding.status == FindingStatus.PUBLISHED

    def test_writes_manifest(self, spore_repo_with_experiment):
        repo = spore_repo_with_experiment
        exp_id = repo.list_experiments()[0].id
        finding = repo.publish_finding(
            experiment_id=exp_id,
            direction="attention-variants",
            claim="test claim",
        )
        finding_path = repo.spore_dir / "findings" / f"{finding.id}.yaml"
        assert finding_path.exists()

    def test_updates_experiment_findings_list(self, spore_repo_with_experiment):
        repo = spore_repo_with_experiment
        exp_id = repo.list_experiments()[0].id
        finding = repo.publish_finding(
            experiment_id=exp_id,
            direction="attention-variants",
            claim="some claim",
        )
        exp = repo.get_experiment(exp_id)
        assert finding.id in exp.findings

    def test_indexes_finding(self, spore_repo_with_experiment):
        repo = spore_repo_with_experiment
        exp_id = repo.list_experiments()[0].id
        finding = repo.publish_finding(
            experiment_id=exp_id,
            direction="attention-variants",
            claim="indexed claim",
        )
        results = repo.index.search(direction="attention-variants")
        ids = [r["id"] for r in results]
        assert finding.id in ids

    def test_auto_detects_experiment(self, spore_repo_with_experiment):
        repo = spore_repo_with_experiment
        # No experiment_id — should auto-detect running experiment
        finding = repo.publish_finding(
            direction="attention-variants",
            claim="auto-detected experiment",
        )
        exp_id = repo.list_experiments()[0].id
        assert finding.experiment_id == exp_id

    def test_standalone_when_no_matching_experiment(self, spore_repo):
        finding = spore_repo.publish_finding(
            direction="no-running-exp",
            claim="standalone finding",
        )
        assert finding.experiment_id == "standalone"

    def test_with_significance(self, spore_repo_with_experiment):
        repo = spore_repo_with_experiment
        exp_id = repo.list_experiments()[0].id
        finding = repo.publish_finding(
            experiment_id=exp_id,
            direction="attention-variants",
            claim="high sig",
            significance=0.9,
        )
        assert finding.significance == 0.9


# ---------------------------------------------------------------------------
# get_finding()
# ---------------------------------------------------------------------------


class TestGetFinding:
    def test_get_existing_finding(self, spore_repo_with_finding):
        repo = spore_repo_with_finding
        finding_id = repo.list_findings()[0].id
        finding = repo.get_finding(finding_id)
        assert finding.id == finding_id

    def test_get_nonexistent_raises(self, spore_repo):
        with pytest.raises(SporeError, match="Finding not found"):
            spore_repo.get_finding("f-doesnotexist")


# ---------------------------------------------------------------------------
# list_findings()
# ---------------------------------------------------------------------------


class TestListFindings:
    def test_list_all(self, spore_repo_with_finding):
        findings = spore_repo_with_finding.list_findings()
        assert len(findings) == 1

    def test_list_empty(self, spore_repo):
        assert spore_repo.list_findings() == []

    def test_filter_by_direction(self, spore_repo):
        spore_repo.start_experiment(direction="alpha", hypothesis="h1", create_branch=False)
        spore_repo.start_experiment(direction="beta", hypothesis="h2", create_branch=False)
        spore_repo.publish_finding(direction="alpha", claim="alpha claim")
        spore_repo.publish_finding(direction="beta", claim="beta claim")
        results = spore_repo.list_findings(direction="alpha")
        assert len(results) == 1
        assert results[0].direction == "alpha"

    def test_filter_by_status(self, spore_repo_with_finding):
        repo = spore_repo_with_finding
        finding_id = repo.list_findings()[0].id
        repo.retract_finding(finding_id)
        published = repo.list_findings(status=FindingStatus.PUBLISHED)
        retracted = repo.list_findings(status=FindingStatus.RETRACTED)
        assert len(published) == 0
        assert len(retracted) == 1


# ---------------------------------------------------------------------------
# retract_finding()
# ---------------------------------------------------------------------------


class TestRetractFinding:
    def test_retract_changes_status(self, spore_repo_with_finding):
        repo = spore_repo_with_finding
        finding_id = repo.list_findings()[0].id
        finding = repo.retract_finding(finding_id)
        assert finding.status == FindingStatus.RETRACTED

    def test_retract_persists(self, spore_repo_with_finding):
        repo = spore_repo_with_finding
        finding_id = repo.list_findings()[0].id
        repo.retract_finding(finding_id)
        reloaded = repo.get_finding(finding_id)
        assert reloaded.status == FindingStatus.RETRACTED


# ---------------------------------------------------------------------------
# create_direction() / list_directions()
# ---------------------------------------------------------------------------


class TestDirections:
    def test_create_direction(self, spore_repo):
        direction = spore_repo.create_direction(
            name="attention", description="Attention mechanism research"
        )
        assert direction.id.startswith("dir-")
        assert direction.name == "attention"

    def test_create_direction_writes_file(self, spore_repo):
        direction = spore_repo.create_direction(name="test-dir", description="d")
        dir_path = spore_repo.spore_dir / "directions" / f"{direction.id}.yaml"
        assert dir_path.exists()

    def test_list_directions_empty(self, spore_repo):
        assert spore_repo.list_directions() == []

    def test_list_directions(self, spore_repo):
        spore_repo.create_direction(name="alpha", description="d1")
        spore_repo.create_direction(name="beta", description="d2")
        dirs = spore_repo.list_directions()
        names = [d.name for d in dirs]
        assert "alpha" in names
        assert "beta" in names

    def test_create_direction_with_tags(self, spore_repo):
        direction = spore_repo.create_direction(
            name="tagged", description="d", tags=["ml", "efficiency"]
        )
        assert "ml" in direction.tags

    def test_create_direction_with_parents(self, spore_repo):
        parent = spore_repo.create_direction(name="parent", description="p")
        child = spore_repo.create_direction(
            name="child", description="c", parent_directions=[parent.id]
        )
        assert parent.id in child.parent_directions


# ---------------------------------------------------------------------------
# adopt_finding()
# ---------------------------------------------------------------------------


class TestAdoptFinding:
    def test_adopt_records_lineage(self, spore_repo_with_finding):
        repo = spore_repo_with_finding
        finding_id = repo.list_findings()[0].id
        exp_id = repo.list_experiments()[0].id
        result = repo.adopt_finding(finding_id=finding_id, experiment_id=exp_id)
        assert result["finding_id"] == finding_id
        assert result["experiment_id"] == exp_id
        exp = repo.get_experiment(exp_id)
        assert finding_id in exp.builds_on

    def test_adopt_idempotent(self, spore_repo_with_finding):
        repo = spore_repo_with_finding
        finding_id = repo.list_findings()[0].id
        exp_id = repo.list_experiments()[0].id
        repo.adopt_finding(finding_id=finding_id, experiment_id=exp_id)
        repo.adopt_finding(finding_id=finding_id, experiment_id=exp_id)
        exp = repo.get_experiment(exp_id)
        assert exp.builds_on.count(finding_id) == 1

    def test_adopt_auto_selects_running_experiment(self, spore_repo_with_finding):
        repo = spore_repo_with_finding
        finding_id = repo.list_findings()[0].id
        result = repo.adopt_finding(finding_id=finding_id)
        exp_id = repo.list_experiments()[0].id
        assert result["experiment_id"] == exp_id

    def test_adopt_no_running_experiment_raises(self, spore_repo_with_finding):
        repo = spore_repo_with_finding
        exp_id = repo.list_experiments()[0].id
        repo.complete_experiment(exp_id)
        finding_id = repo.list_findings()[0].id
        with pytest.raises(SporeError, match="No running experiment"):
            repo.adopt_finding(finding_id=finding_id)


# ---------------------------------------------------------------------------
# rebuild_index()
# ---------------------------------------------------------------------------


class TestRebuildIndex:
    def test_rebuild_returns_count(self, spore_repo_with_finding):
        repo = spore_repo_with_finding
        count = repo.rebuild_index()
        assert count == 1

    def test_rebuild_clears_and_repopulates(self, spore_repo_with_finding):
        repo = spore_repo_with_finding
        repo.index.clear()
        assert repo.index.search(direction="attention-variants") == []
        repo.rebuild_index()
        results = repo.index.search(direction="attention-variants")
        assert len(results) == 1

    def test_rebuild_empty(self, spore_repo):
        count = spore_repo.rebuild_index()
        assert count == 0


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_initialized(self, spore_repo):
        s = spore_repo.status()
        assert s["initialized"] is True
        assert s["experiments"]["total"] == 0
        assert s["findings"]["total"] == 0
        assert s["directions"] == 0

    def test_status_with_experiment(self, spore_repo_with_experiment):
        s = spore_repo_with_experiment.status()
        assert s["experiments"]["total"] == 1
        assert s["experiments"]["running"] == 1
        assert s["experiments"]["completed"] == 0

    def test_status_with_finding(self, spore_repo_with_finding):
        s = spore_repo_with_finding.status()
        assert s["findings"]["total"] == 1
        assert s["findings"]["published"] == 1

    def test_status_counts_directions(self, spore_repo):
        spore_repo.create_direction(name="alpha", description="d")
        s = spore_repo.status()
        assert s["directions"] == 1

    def test_status_completed_counts(self, spore_repo_with_experiment):
        repo = spore_repo_with_experiment
        exp_id = repo.list_experiments()[0].id
        repo.complete_experiment(exp_id)
        s = repo.status()
        assert s["experiments"]["running"] == 0
        assert s["experiments"]["completed"] == 1


# ---------------------------------------------------------------------------
# discover_remote()
# ---------------------------------------------------------------------------


def _commit_finding_to_branch(git_repo: git.Repo, branch_name: str, finding: Finding) -> None:
    """Helper: create a branch with a finding YAML committed to .spore/findings/."""
    original_branch = git_repo.active_branch.name
    git_repo.create_head(branch_name)
    git_repo.heads[branch_name].checkout()

    spore_findings_dir = git_repo.working_dir + "/.spore/findings"
    import os

    os.makedirs(spore_findings_dir, exist_ok=True)
    finding_path = spore_findings_dir + f"/{finding.id}.yaml"
    with open(finding_path, "w") as f:
        f.write(finding.to_yaml())

    git_repo.index.add([finding_path])
    git_repo.index.commit(f"Add finding {finding.id}")
    git_repo.heads[original_branch].checkout()


class TestDiscoverRemote:
    def test_discovers_findings_from_spore_branch(self, spore_repo):
        """discover_remote finds findings on spore/ prefixed branches."""
        finding = Finding(
            experiment_id="exp-remote1",
            agent_id="remote-agent",
            direction="attention-variants",
            claim="Remote finding on spore branch",
            significance=0.8,
        )
        _commit_finding_to_branch(
            spore_repo.git_repo, "spore/remote-agent/attention-variants", finding
        )
        results = spore_repo.discover_remote()
        assert len(results) >= 1
        ids = [f.id for f in results]
        assert finding.id in ids

    def test_ignores_non_spore_branches(self, spore_repo):
        """discover_remote skips branches without spore/ or origin/ prefix."""
        finding = Finding(
            experiment_id="exp-feature",
            agent_id="dev-agent",
            direction="feature-work",
            claim="Finding on a feature branch",
            significance=0.5,
        )
        _commit_finding_to_branch(spore_repo.git_repo, "feature/my-feature", finding)
        results = spore_repo.discover_remote()
        ids = [f.id for f in results]
        assert finding.id not in ids

    def test_filters_by_direction(self, spore_repo):
        """discover_remote filters by direction when specified."""
        f1 = Finding(
            experiment_id="exp-1",
            agent_id="agent-1",
            direction="attention-variants",
            claim="Attention finding",
            significance=0.7,
        )
        f2 = Finding(
            experiment_id="exp-2",
            agent_id="agent-2",
            direction="learning-rate",
            claim="LR finding",
            significance=0.6,
        )
        _commit_finding_to_branch(spore_repo.git_repo, "spore/agent-1/attention", f1)
        _commit_finding_to_branch(spore_repo.git_repo, "spore/agent-2/lr", f2)
        results = spore_repo.discover_remote(direction="attention")
        ids = [f.id for f in results]
        assert f1.id in ids
        assert f2.id not in ids

    def test_indexes_discovered_findings(self, spore_repo):
        """discover_remote adds findings to the local index."""
        finding = Finding(
            experiment_id="exp-idx",
            agent_id="remote-agent",
            direction="indexing-test",
            claim="Should be indexed locally",
            significance=0.9,
        )
        _commit_finding_to_branch(spore_repo.git_repo, "spore/remote-agent/indexing", finding)
        spore_repo.discover_remote()
        # Verify it's in the local index
        results = spore_repo.index.search(direction="indexing-test")
        assert len(results) >= 1
        assert results[0]["id"] == finding.id

    def test_returns_empty_when_no_spore_branches(self, spore_repo):
        """discover_remote returns empty list when no scannable branches exist."""
        results = spore_repo.discover_remote()
        assert results == []

    def test_sorted_by_significance(self, spore_repo):
        """discover_remote returns results sorted by significance descending."""
        f_low = Finding(
            experiment_id="exp-low",
            agent_id="agent-a",
            direction="sort-test",
            claim="Low significance",
            significance=0.2,
        )
        f_high = Finding(
            experiment_id="exp-high",
            agent_id="agent-b",
            direction="sort-test",
            claim="High significance",
            significance=0.9,
        )
        _commit_finding_to_branch(spore_repo.git_repo, "spore/agent-a/sort", f_low)
        _commit_finding_to_branch(spore_repo.git_repo, "spore/agent-b/sort", f_high)
        results = spore_repo.discover_remote()
        assert len(results) == 2
        assert results[0].significance >= results[1].significance


# ---------------------------------------------------------------------------
# Earned significance (repo-level integration)
# ---------------------------------------------------------------------------


class TestEarnedSignificance:
    def test_get_finding_significance_no_adoptions(self, spore_repo_with_finding):
        """A finding with no adoptions returns self-reported significance."""
        repo = spore_repo_with_finding
        findings = repo.list_findings()
        assert len(findings) >= 1
        sig_info = repo.get_finding_significance(findings[0].id)
        assert sig_info["self_reported"] == findings[0].significance
        assert sig_info["adoption_count"] == 0
        assert sig_info["earned_significance"] == findings[0].significance

    def test_get_finding_significance_with_adoption(self, spore_repo_with_finding):
        """After adopting a finding, its earned significance increases."""
        repo = spore_repo_with_finding
        findings = repo.list_findings()
        original_finding = findings[0]

        # Start a new experiment that builds on the original finding
        exp2 = repo.start_experiment(
            direction="follow-up",
            hypothesis="Building on previous work",
            builds_on=[original_finding.id],
            create_branch=False,
        )
        # Publish a finding that builds on the original
        repo.publish_finding(
            experiment_id=exp2.id,
            direction="follow-up",
            claim="Extended the original finding",
            builds_on=[original_finding.id],
            significance=0.6,
        )

        sig_info = repo.get_finding_significance(original_finding.id)
        assert sig_info["adoption_count"] == 1
        assert sig_info["earned_significance"] > sig_info["self_reported"]

    def test_discover_includes_earned_significance(self, spore_repo_with_finding):
        """discover() results include earned_significance and adoption_count."""
        repo = spore_repo_with_finding
        results = repo.discover()
        assert len(results) >= 1
        for r in results:
            assert "earned_significance" in r
            assert "adoption_count" in r

    def test_get_prior_art_includes_earned_significance(self, spore_repo_with_finding):
        """get_prior_art() results include earned_significance."""
        repo = spore_repo_with_finding
        results = repo.get_prior_art(direction="attention")
        assert len(results) >= 1
        for r in results:
            assert "earned_significance" in r
            assert "adoption_count" in r

    def test_get_finding_significance_nonexistent(self, spore_repo):
        """get_finding_significance raises SporeError for missing finding."""
        with pytest.raises(SporeError, match="not found"):
            spore_repo.get_finding_significance("f-nonexistent")
