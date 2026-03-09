"""End-to-end workflow tests for Spore.

These tests simulate complete autoresearch use cases:
- Single agent: full research lifecycle (init → experiment → findings → adopt → lineage)
- Multi-agent: two agents publishing to the same repo and discovering each other's findings
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import git

if TYPE_CHECKING:
    from pathlib import Path

from spore.models import ExperimentStatus
from spore.repo import SporeRepo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_git_repo(path: Path) -> git.Repo:
    """Initialize a git repo with user config and initial commit."""
    repo = git.Repo.init(str(path))
    repo.config_writer().set_value("user", "name", "Test Agent").release()
    repo.config_writer().set_value("user", "email", "test@spore.dev").release()
    (path / "README.md").write_text("# Test\n")
    repo.index.add(["README.md"])
    repo.index.commit("initial commit")
    return repo


# ---------------------------------------------------------------------------
# Full autoresearch lifecycle
# ---------------------------------------------------------------------------


class TestFullWorkflow:
    """Simulates a complete single-agent research lifecycle."""

    def test_full_research_lifecycle(self, tmp_path: Path):
        """
        Full workflow:
        1. Init repo with agent-id
        2. Create a research direction
        3. Start experiment on that direction
        4. Publish 3 findings with different metrics
        5. Discover findings (verify they're found)
        6. Start a SECOND experiment that builds on first's findings
        7. Adopt findings into second experiment
        8. Verify lineage shows the chain
        9. Complete both experiments
        10. Check status shows correct counts
        """
        make_git_repo(tmp_path)

        # Step 1: Init
        repo = SporeRepo(tmp_path)
        config = repo.init(agent_id="autoresearch-agent", repo_name="test-research")
        assert config.agent_id == "autoresearch-agent"
        assert repo.is_initialized

        # Step 2: Create a research direction
        direction = repo.create_direction(
            name="attention-variants",
            description="Exploring attention mechanism variants for efficiency",
            tags=["attention", "efficiency"],
        )
        assert direction.id.startswith("dir-")
        directions = repo.list_directions()
        assert len(directions) == 1
        assert directions[0].name == "attention-variants"

        # Step 3: Start first experiment
        exp1 = repo.start_experiment(
            direction="attention-variants",
            hypothesis="Multi-Query Attention reduces memory without hurting quality",
            create_branch=False,
        )
        assert exp1.id.startswith("exp-")
        assert exp1.status == ExperimentStatus.RUNNING
        assert exp1.direction == "attention-variants"

        # Step 4: Publish 3 findings with different metrics
        finding1 = repo.publish_finding(
            experiment_id=exp1.id,
            direction="attention-variants",
            claim="MQA with 4 KV heads drops val_bpb by 0.02",
            metrics={"val_bpb": 0.4523, "delta": -0.0201},
            significance=0.8,
            applicability=["attention", "memory-efficiency"],
        )
        assert finding1.id.startswith("f-")
        assert finding1.significance == 0.8

        finding2 = repo.publish_finding(
            experiment_id=exp1.id,
            direction="attention-variants",
            claim="MQA with 8 KV heads slightly better but more memory",
            metrics={"val_bpb": 0.4489, "memory_gb": 12.4},
            significance=0.6,
        )

        finding3 = repo.publish_finding(
            experiment_id=exp1.id,
            direction="attention-variants",
            claim="Grouped Query Attention (GQA) with 8 groups beats MQA",
            metrics={"val_bpb": 0.4411, "delta": -0.0312},
            significance=0.9,
            builds_on=[finding1.id, finding2.id],
        )
        assert finding3.significance == 0.9

        # Verify experiment has findings attached
        exp1_loaded = repo.get_experiment(exp1.id)
        assert finding1.id in exp1_loaded.findings
        assert finding2.id in exp1_loaded.findings
        assert finding3.id in exp1_loaded.findings

        # Step 5: Discover findings — verify they're returned
        results = repo.discover(direction="attention-variants")
        assert len(results) == 3
        result_ids = {r["id"] for r in results}
        assert finding1.id in result_ids
        assert finding2.id in result_ids
        assert finding3.id in result_ids

        # Discover with metric filter
        low_bpb_results = repo.discover(
            metric_name="val_bpb",
            metric_max=0.445,
        )
        assert len(low_bpb_results) >= 1
        # finding3 has val_bpb=0.4411 which is <= 0.445
        assert any(r["id"] == finding3.id for r in low_bpb_results)

        # Discover with significance filter
        high_sig_results = repo.discover(min_significance=0.75)
        assert len(high_sig_results) == 2  # finding1 (0.8) and finding3 (0.9)

        # Step 6: Start second experiment building on first's findings
        exp2 = repo.start_experiment(
            direction="attention-variants",
            hypothesis="GQA with learned grouping further reduces val_bpb",
            builds_on=[finding3.id],
            create_branch=False,
        )
        assert exp2.id != exp1.id
        assert finding3.id in exp2.builds_on

        # Step 7: Adopt findings into second experiment
        adoption = repo.adopt_finding(finding_id=finding3.id, experiment_id=exp2.id)
        assert adoption["finding_id"] == finding3.id
        assert adoption["experiment_id"] == exp2.id

        # Also adopt finding1 into exp2
        repo.adopt_finding(finding_id=finding1.id, experiment_id=exp2.id)
        exp2_loaded = repo.get_experiment(exp2.id)
        assert finding3.id in exp2_loaded.builds_on
        assert finding1.id in exp2_loaded.builds_on

        # Publish a finding from exp2 that builds on finding3
        finding4 = repo.publish_finding(
            experiment_id=exp2.id,
            direction="attention-variants",
            claim="GQA with 4 learned groups outperforms fixed GQA",
            metrics={"val_bpb": 0.4320, "delta": -0.0091},
            significance=0.85,
            builds_on=[finding3.id],
        )
        assert finding4.builds_on == [finding3.id]

        # Step 8: Verify lineage shows the chain
        # finding4 builds on finding3 which builds on finding1 and finding2
        lineage = repo.index.get_lineage(finding4.id, depth=10)
        lineage_ids = {entry["id"] for entry in lineage}
        assert finding3.id in lineage_ids
        assert finding1.id in lineage_ids
        assert finding2.id in lineage_ids

        # Step 9: Complete both experiments
        completed_exp1 = repo.complete_experiment(exp1.id)
        assert completed_exp1.status == ExperimentStatus.COMPLETED
        assert completed_exp1.completed is not None

        completed_exp2 = repo.complete_experiment(exp2.id)
        assert completed_exp2.status == ExperimentStatus.COMPLETED

        # Step 10: Check status shows correct counts
        status = repo.status()
        assert status["experiments"]["total"] == 2
        assert status["experiments"]["completed"] == 2
        assert status["experiments"]["running"] == 0
        assert status["findings"]["total"] == 4
        assert status["findings"]["published"] == 4
        assert status["directions"] == 1

    def test_experiment_abandon_workflow(self, tmp_path: Path):
        """Test that abandoning an experiment marks it correctly."""
        make_git_repo(tmp_path)
        repo = SporeRepo(tmp_path)
        repo.init(agent_id="test-agent")

        exp = repo.start_experiment(
            direction="test-direction",
            hypothesis="This won't work out",
            create_branch=False,
        )

        abandoned = repo.abandon_experiment(exp.id)
        assert abandoned.status == ExperimentStatus.ABANDONED

        status = repo.status()
        assert status["experiments"]["running"] == 0

    def test_index_rebuild_restores_discover(self, tmp_path: Path):
        """After rebuilding index, discover returns same results."""
        make_git_repo(tmp_path)
        repo = SporeRepo(tmp_path)
        repo.init(agent_id="test-agent")

        exp = repo.start_experiment(
            direction="attention",
            hypothesis="MQA works",
            create_branch=False,
        )
        finding = repo.publish_finding(
            experiment_id=exp.id,
            direction="attention",
            claim="MQA reduces memory",
            metrics={"val_bpb": 0.45},
            significance=0.7,
        )

        # Rebuild index from scratch
        count = repo.rebuild_index()
        assert count == 1

        # Discover should still work
        results = repo.discover(direction="attention")
        assert len(results) == 1
        assert results[0]["id"] == finding.id


# ---------------------------------------------------------------------------
# Multi-agent simulation
# ---------------------------------------------------------------------------


class TestMultiAgentWorkflow:
    """Simulates two agents publishing to the same repo and discovering each other's findings."""

    def test_two_agents_cross_discovery(self, tmp_path: Path):
        """
        Agent Alpha and Agent Beta both publish findings to the same repo.
        Each uses SPORE_AGENT_ID env var to identify themselves. The repo is
        initialized without an embedded agent_id so both agents rely on env vars.
        Each can discover the other's findings through the shared index.
        """
        make_git_repo(tmp_path)

        # Agent Alpha initializes the repo WITHOUT embedding agent_id in config.
        # This lets each agent use SPORE_AGENT_ID env var to identify themselves.
        os.environ["SPORE_AGENT_ID"] = "agent-alpha"
        repo_alpha = SporeRepo(tmp_path)
        repo_alpha.init(agent_id=None)  # No agent_id in config; use env var
        assert repo_alpha.agent_id == "agent-alpha"

        # Alpha starts an experiment and publishes findings
        exp_alpha = repo_alpha.start_experiment(
            direction="attention-variants",
            hypothesis="MQA reduces memory",
            create_branch=False,
        )
        finding_alpha_1 = repo_alpha.publish_finding(
            experiment_id=exp_alpha.id,
            direction="attention-variants",
            claim="Alpha: MQA with 4 KV heads reduces val_bpb by 0.02",
            metrics={"val_bpb": 0.4523},
            significance=0.8,
        )
        finding_alpha_2 = repo_alpha.publish_finding(
            experiment_id=exp_alpha.id,
            direction="attention-variants",
            claim="Alpha: Grouped QA is better than MQA",
            metrics={"val_bpb": 0.4411},
            significance=0.85,
            builds_on=[finding_alpha_1.id],
        )

        # Switch env to Beta — both SporeRepo instances read env var since config.agent_id is None
        os.environ["SPORE_AGENT_ID"] = "agent-beta"
        repo_beta = SporeRepo(tmp_path)
        # Beta doesn't call init — repo is already initialized
        assert repo_beta.agent_id == "agent-beta"

        # Beta starts their own experiment
        exp_beta = repo_beta.start_experiment(
            direction="learning-rate",
            hypothesis="Cosine LR schedule converges faster",
            create_branch=False,
        )
        finding_beta_1 = repo_beta.publish_finding(
            experiment_id=exp_beta.id,
            direction="learning-rate",
            claim="Beta: Cosine LR reduces training steps by 15%",
            metrics={"steps_to_convergence": 8500},
            significance=0.75,
        )
        finding_beta_2 = repo_beta.publish_finding(
            experiment_id=exp_beta.id,
            direction="learning-rate",
            claim="Beta: Warmup + cosine outperforms flat LR",
            metrics={"final_loss": 1.234, "steps_to_convergence": 7800},
            significance=0.9,
        )

        # Switch back to Alpha for discovery
        os.environ["SPORE_AGENT_ID"] = "agent-alpha"

        # Alpha discovers Beta's findings
        alpha_discovers_beta = repo_alpha.discover(direction="learning-rate")
        assert len(alpha_discovers_beta) == 2
        beta_ids_found = {r["id"] for r in alpha_discovers_beta}
        assert finding_beta_1.id in beta_ids_found
        assert finding_beta_2.id in beta_ids_found

        # Beta discovers Alpha's findings
        os.environ["SPORE_AGENT_ID"] = "agent-beta"
        beta_discovers_alpha = repo_beta.discover(direction="attention-variants")
        assert len(beta_discovers_alpha) == 2
        alpha_ids_found = {r["id"] for r in beta_discovers_alpha}
        assert finding_alpha_1.id in alpha_ids_found
        assert finding_alpha_2.id in alpha_ids_found

        # Discover all findings across both directions
        all_results = repo_alpha.discover()
        assert len(all_results) == 4

        # Filter by agent
        alpha_only = repo_alpha.discover(agent_id="agent-alpha")
        assert len(alpha_only) == 2
        assert all(r["agent_id"] == "agent-alpha" for r in alpha_only)

        beta_only = repo_beta.discover(agent_id="agent-beta")
        assert len(beta_only) == 2
        assert all(r["agent_id"] == "agent-beta" for r in beta_only)

        # Clean up env var
        del os.environ["SPORE_AGENT_ID"]

    def test_two_agents_cross_adoption(self, tmp_path: Path):
        """
        Agent Beta discovers Alpha's finding and adopts it into their experiment,
        then publishes a finding that builds on it. Lineage chain is verifiable.
        """
        make_git_repo(tmp_path)

        # Alpha publishes — init without embedded agent_id so env var drives identity
        os.environ["SPORE_AGENT_ID"] = "agent-alpha"
        repo_alpha = SporeRepo(tmp_path)
        repo_alpha.init(agent_id=None)

        exp_alpha = repo_alpha.start_experiment(
            direction="attention-variants",
            hypothesis="MQA reduces memory",
            create_branch=False,
        )
        finding_alpha = repo_alpha.publish_finding(
            experiment_id=exp_alpha.id,
            direction="attention-variants",
            claim="Alpha: MQA with 4 KV heads is baseline",
            metrics={"val_bpb": 0.4523},
            significance=0.8,
        )

        # Beta discovers Alpha's finding
        os.environ["SPORE_AGENT_ID"] = "agent-beta"
        repo_beta = SporeRepo(tmp_path)

        discovered = repo_beta.discover(direction="attention-variants")
        assert len(discovered) == 1
        assert discovered[0]["id"] == finding_alpha.id

        # Beta starts experiment building on Alpha's finding
        exp_beta = repo_beta.start_experiment(
            direction="attention-variants",
            hypothesis="Can we push Alpha's MQA baseline further?",
            builds_on=[finding_alpha.id],
            create_branch=False,
        )

        # Beta adopts Alpha's finding
        repo_beta.adopt_finding(finding_id=finding_alpha.id, experiment_id=exp_beta.id)
        exp_beta_loaded = repo_beta.get_experiment(exp_beta.id)
        assert finding_alpha.id in exp_beta_loaded.builds_on

        # Beta publishes a follow-on finding
        finding_beta = repo_beta.publish_finding(
            experiment_id=exp_beta.id,
            direction="attention-variants",
            claim="Beta: GQA further reduces val_bpb beyond Alpha's MQA",
            metrics={"val_bpb": 0.4300},
            significance=0.9,
            builds_on=[finding_alpha.id],
        )
        assert finding_alpha.id in finding_beta.builds_on

        # Verify lineage: finding_beta -> finding_alpha
        lineage = repo_alpha.index.get_lineage(finding_beta.id)
        lineage_ids = {entry["id"] for entry in lineage}
        assert finding_alpha.id in lineage_ids

        # Both experiments can be completed
        repo_alpha.complete_experiment(exp_alpha.id)
        repo_beta.complete_experiment(exp_beta.id)

        final_status = repo_alpha.status()
        assert final_status["experiments"]["total"] == 2
        assert final_status["experiments"]["completed"] == 2
        assert final_status["findings"]["total"] == 2

        # Clean up env var
        del os.environ["SPORE_AGENT_ID"]

    def test_two_agents_direction_filtering(self, tmp_path: Path):
        """
        Two agents working in different directions don't interfere with
        each other's direction-filtered discovery.
        """
        make_git_repo(tmp_path)

        os.environ["SPORE_AGENT_ID"] = "agent-alpha"
        repo_alpha = SporeRepo(tmp_path)
        repo_alpha.init(agent_id=None)  # Use env var for agent identity

        exp_a = repo_alpha.start_experiment(
            direction="attention-research",
            hypothesis="Attention matters",
            create_branch=False,
        )
        for i in range(3):
            repo_alpha.publish_finding(
                experiment_id=exp_a.id,
                direction="attention-research",
                claim=f"Alpha attention finding {i}",
                metrics={"val_bpb": 0.45 - i * 0.01},
                significance=0.7,
            )

        os.environ["SPORE_AGENT_ID"] = "agent-beta"
        repo_beta = SporeRepo(tmp_path)
        exp_b = repo_beta.start_experiment(
            direction="optimizer-research",
            hypothesis="Optimizer matters",
            create_branch=False,
        )
        for i in range(2):
            repo_beta.publish_finding(
                experiment_id=exp_b.id,
                direction="optimizer-research",
                claim=f"Beta optimizer finding {i}",
                metrics={"val_loss": 1.5 - i * 0.1},
                significance=0.65,
            )

        # Each agent filters by their own direction
        alpha_attention = repo_alpha.discover(direction="attention-research")
        assert len(alpha_attention) == 3

        beta_optimizer = repo_beta.discover(direction="optimizer-research")
        assert len(beta_optimizer) == 2

        # Cross-discovery with no filter returns all 5
        all_findings = repo_alpha.discover()
        assert len(all_findings) == 5

        del os.environ["SPORE_AGENT_ID"]
