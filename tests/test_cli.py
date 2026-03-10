"""CLI integration tests using Click's CliRunner.

Tests all Spore CLI commands with isolated filesystems. Each test sets up
a git repo with an initial commit before invoking CLI commands.
"""

from __future__ import annotations

from pathlib import Path

import git
from click.testing import CliRunner

from spore.cli import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_git_repo(path: str | Path) -> git.Repo:
    """Initialize a git repo with user config and initial commit."""
    repo = git.Repo.init(str(path))
    repo.config_writer().set_value("user", "name", "Test Agent").release()
    repo.config_writer().set_value("user", "email", "test@spore.dev").release()
    Path(path, "README.md").write_text("# Test\n")
    repo.index.add(["README.md"])
    repo.index.commit("initial commit")
    return repo


def init_spore(runner: CliRunner, agent_id: str = "test-agent") -> None:
    """Run spore init inside an already-isolated filesystem."""
    result = runner.invoke(main, ["init", "--agent-id", agent_id])
    assert result.exit_code == 0, f"spore init failed: {result.output}"


def extract_id_from_panel(output: str, label: str) -> str | None:
    """Extract an ID value from Rich Panel output.

    Rich Panel lines look like:
      │   ID:         exp-abc123  │
    We strip the │ border chars and trailing whitespace.
    """
    for line in output.splitlines():
        stripped = line.strip().lstrip("\u2502").strip().rstrip("\u2502").strip()
        if stripped.startswith(f"{label}:"):
            value = stripped.split(":", 1)[-1].strip()
            # Remove any trailing Rich markup or border artifacts
            value = value.split("\u2502")[0].strip()
            return value
    return None


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_with_agent_id(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            result = runner.invoke(main, ["init", "--agent-id", "agent-47"])
            assert result.exit_code == 0
            assert "Spore initialized" in result.output
            assert "agent-47" in result.output

    def test_init_without_agent_id(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            result = runner.invoke(main, ["init"])
            assert result.exit_code == 0
            assert "Spore initialized" in result.output

    def test_init_with_repo_name(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            result = runner.invoke(main, ["init", "--agent-id", "a1", "--repo-name", "my-research"])
            assert result.exit_code == 0
            assert "my-research" in result.output

    def test_init_creates_spore_directory(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            runner.invoke(main, ["init", "--agent-id", "test-agent"])
            assert Path(fs, ".spore", "config.yaml").exists()

    def test_init_twice_fails(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            runner.invoke(main, ["init", "--agent-id", "test-agent"])
            result = runner.invoke(main, ["init", "--agent-id", "test-agent"])
            assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------


class TestExperimentStart:
    def test_start_experiment(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            assert result.exit_code == 0
            assert "Experiment started" in result.output
            assert "attention-variants" in result.output

    def test_start_requires_direction(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            assert result.exit_code != 0

    def test_start_requires_hypothesis(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--no-branch",
                ],
            )
            assert result.exit_code != 0

    def test_start_experiment_before_init_fails(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            result = runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "test",
                    "--hypothesis",
                    "test",
                    "--no-branch",
                ],
            )
            assert result.exit_code != 0

    def test_start_with_builds_on(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--builds-on",
                    "f-abc123",
                    "--no-branch",
                ],
            )
            assert result.exit_code == 0

    def test_start_returns_experiment_id(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            assert result.exit_code == 0
            exp_id = extract_id_from_panel(result.output, "ID")
            assert exp_id is not None
            assert exp_id.startswith("exp-")


class TestExperimentList:
    def test_list_empty(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(main, ["experiment", "list"])
            assert result.exit_code == 0
            assert "No experiments found" in result.output

    def test_list_with_experiments(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            result = runner.invoke(main, ["experiment", "list"])
            assert result.exit_code == 0
            # Rich truncates long strings in tables; "attention-varia…" or "attention-"
            assert "attention-" in result.output

    def test_list_filter_by_direction(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "learning-rate",
                    "--hypothesis",
                    "LR warmup helps",
                    "--no-branch",
                ],
            )
            result = runner.invoke(
                main, ["experiment", "list", "--direction", "attention-variants"]
            )
            assert result.exit_code == 0
            assert "attention-" in result.output
            assert "learning-rate" not in result.output

    def test_list_filter_by_status(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            result = runner.invoke(main, ["experiment", "list", "--status", "running"])
            assert result.exit_code == 0
            assert "attention-" in result.output


class TestExperimentShow:
    def _start_and_get_id(self, runner: CliRunner) -> str:
        result = runner.invoke(
            main,
            [
                "experiment",
                "start",
                "--direction",
                "attention-variants",
                "--hypothesis",
                "MQA reduces memory",
                "--no-branch",
            ],
        )
        return extract_id_from_panel(result.output, "ID")

    def test_show_experiment(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            exp_id = self._start_and_get_id(runner)
            assert exp_id is not None
            assert exp_id.startswith("exp-")

            result = runner.invoke(main, ["experiment", "show", exp_id])
            assert result.exit_code == 0
            assert exp_id in result.output
            assert "attention-variants" in result.output

    def test_show_nonexistent_experiment(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(main, ["experiment", "show", "exp-notexist"])
            assert result.exit_code != 0


class TestExperimentComplete:
    def test_complete_experiment(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            start_result = runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            exp_id = extract_id_from_panel(start_result.output, "ID")
            assert exp_id is not None

            result = runner.invoke(main, ["experiment", "complete", exp_id])
            assert result.exit_code == 0
            assert "completed" in result.output.lower()

    def test_complete_nonexistent_experiment(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(main, ["experiment", "complete", "exp-notexist"])
            assert result.exit_code != 0


class TestExperimentAbandon:
    def test_abandon_experiment(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            start_result = runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            exp_id = extract_id_from_panel(start_result.output, "ID")
            assert exp_id is not None

            result = runner.invoke(main, ["experiment", "abandon", exp_id])
            assert result.exit_code == 0
            assert "abandoned" in result.output.lower()

    def test_abandon_nonexistent_experiment(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(main, ["experiment", "abandon", "exp-notexist"])
            assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


class TestFindingPublish:
    def test_publish_finding(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            result = runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "MQA with 4 KV heads drops val_bpb by 0.02",
                    "--direction",
                    "attention-variants",
                    "--metric",
                    "val_bpb=0.4523",
                ],
            )
            assert result.exit_code == 0
            assert "Finding published" in result.output
            assert "attention-variants" in result.output

    def test_publish_requires_claim(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--direction",
                    "attention-variants",
                    "--metric",
                    "val_bpb=0.45",
                ],
            )
            assert result.exit_code != 0

    def test_publish_requires_direction(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "MQA reduces memory",
                    "--metric",
                    "val_bpb=0.45",
                ],
            )
            assert result.exit_code != 0

    def test_publish_with_multiple_metrics(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            result = runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "MQA is effective",
                    "--direction",
                    "attention-variants",
                    "--metric",
                    "val_bpb=0.4523",
                    "--metric",
                    "delta=-0.0201",
                    "--significance",
                    "0.8",
                ],
            )
            assert result.exit_code == 0

    def test_publish_with_invalid_metric_format(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "Some finding",
                    "--direction",
                    "attention-variants",
                    "--metric",
                    "val_bpb_no_equals",
                ],
            )
            assert result.exit_code != 0

    def test_publish_before_init_fails(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            result = runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "Some finding",
                    "--direction",
                    "attention-variants",
                ],
            )
            assert result.exit_code != 0

    def test_publish_with_tags(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            result = runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "MQA is effective",
                    "--direction",
                    "attention-variants",
                    "--tag",
                    "attention",
                    "--tag",
                    "memory-efficiency",
                ],
            )
            assert result.exit_code == 0

    def test_publish_returns_finding_id(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            result = runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "MQA is effective",
                    "--direction",
                    "attention-variants",
                ],
            )
            assert result.exit_code == 0
            finding_id = extract_id_from_panel(result.output, "ID")
            assert finding_id is not None
            assert finding_id.startswith("f-")


class TestFindingList:
    def test_list_empty(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(main, ["finding", "list"])
            assert result.exit_code == 0
            assert "No findings found" in result.output

    def test_list_findings(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "MQA is effective",
                    "--direction",
                    "attention-variants",
                ],
            )
            result = runner.invoke(main, ["finding", "list"])
            assert result.exit_code == 0
            assert "attention-" in result.output

    def test_list_filter_by_direction(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "MQA is effective",
                    "--direction",
                    "attention-variants",
                ],
            )
            runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "Warmup helps",
                    "--direction",
                    "learning-rate",
                ],
            )
            result = runner.invoke(main, ["finding", "list", "--direction", "attention-variants"])
            assert result.exit_code == 0
            assert "attention-" in result.output
            assert "learning-rate" not in result.output


class TestFindingShow:
    def _publish_and_get_id(self, runner: CliRunner) -> str:
        runner.invoke(
            main,
            [
                "experiment",
                "start",
                "--direction",
                "attention-variants",
                "--hypothesis",
                "MQA reduces memory",
                "--no-branch",
            ],
        )
        publish_result = runner.invoke(
            main,
            [
                "finding",
                "publish",
                "--claim",
                "MQA with 4 KV heads drops val_bpb by 0.02",
                "--direction",
                "attention-variants",
                "--metric",
                "val_bpb=0.4523",
            ],
        )
        return extract_id_from_panel(publish_result.output, "ID")

    def test_show_finding(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            finding_id = self._publish_and_get_id(runner)
            assert finding_id is not None
            assert finding_id.startswith("f-")

            result = runner.invoke(main, ["finding", "show", finding_id])
            assert result.exit_code == 0
            assert finding_id in result.output
            assert "attention-variants" in result.output

    def test_show_nonexistent_finding(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(main, ["finding", "show", "f-notexist"])
            assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Discover
# ---------------------------------------------------------------------------


class TestDiscover:
    def _setup_with_findings(self, runner: CliRunner) -> list[str]:
        runner.invoke(
            main,
            [
                "experiment",
                "start",
                "--direction",
                "attention-variants",
                "--hypothesis",
                "MQA reduces memory",
                "--no-branch",
            ],
        )
        ids = []
        for i in range(3):
            result = runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    f"Finding {i} about attention",
                    "--direction",
                    "attention-variants",
                    "--metric",
                    f"val_bpb={0.45 - i * 0.01}",
                    "--significance",
                    "0.7",
                ],
            )
            fid = extract_id_from_panel(result.output, "ID")
            if fid:
                ids.append(fid)
        return ids

    def test_discover_all(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            self._setup_with_findings(runner)
            result = runner.invoke(main, ["discover"])
            assert result.exit_code == 0
            # Rich table truncates; check prefix "attenti" (survives column squeeze)
            assert "attenti" in result.output

    def test_discover_filter_by_direction(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            self._setup_with_findings(runner)
            runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "LR warmup helps",
                    "--direction",
                    "learning-rate",
                ],
            )
            result = runner.invoke(main, ["discover", "--direction", "attention-variants"])
            assert result.exit_code == 0
            assert "attenti" in result.output
            # learning-rate should NOT appear when filtered
            assert "learning-rate" not in result.output

    def test_discover_with_query(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            self._setup_with_findings(runner)
            result = runner.invoke(main, ["discover", "--query", "attention"])
            assert result.exit_code == 0

    def test_discover_with_metric_filter(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            self._setup_with_findings(runner)
            result = runner.invoke(
                main,
                [
                    "discover",
                    "--metric",
                    "val_bpb",
                    "--metric-max",
                    "0.46",
                ],
            )
            assert result.exit_code == 0

    def test_discover_with_min_significance(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            self._setup_with_findings(runner)
            result = runner.invoke(main, ["discover", "--min-significance", "0.5"])
            assert result.exit_code == 0

    def test_discover_with_limit(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            self._setup_with_findings(runner)
            result = runner.invoke(main, ["discover", "--limit", "2"])
            assert result.exit_code == 0

    def test_discover_empty(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(main, ["discover"])
            assert result.exit_code == 0
            assert "No findings found" in result.output

    def test_discover_filter_by_agent(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            self._setup_with_findings(runner)
            result = runner.invoke(main, ["discover", "--agent", "test-agent"])
            assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Adopt
# ---------------------------------------------------------------------------


class TestAdopt:
    def test_adopt_finding(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            # Publish first finding
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            publish_result = runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "MQA with 4 KV heads works",
                    "--direction",
                    "attention-variants",
                ],
            )
            finding_id = extract_id_from_panel(publish_result.output, "ID")
            assert finding_id is not None

            # Start a second experiment and adopt the finding
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "learning-rate",
                    "--hypothesis",
                    "LR warmup helps",
                    "--no-branch",
                ],
            )
            result = runner.invoke(main, ["adopt", finding_id])
            assert result.exit_code == 0
            assert "Adopted" in result.output
            assert finding_id in result.output

    def test_adopt_requires_running_experiment(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            # No running experiment — adopt should fail
            result = runner.invoke(main, ["adopt", "f-notexist"])
            assert result.exit_code != 0

    def test_adopt_with_explicit_experiment_id(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            start_result = runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            exp_id = extract_id_from_panel(start_result.output, "ID")

            publish_result = runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "MQA works",
                    "--direction",
                    "attention-variants",
                ],
            )
            finding_id = extract_id_from_panel(publish_result.output, "ID")

            result = runner.invoke(main, ["adopt", finding_id, "--experiment", exp_id])
            assert result.exit_code == 0
            assert "Adopted" in result.output


# ---------------------------------------------------------------------------
# Direction
# ---------------------------------------------------------------------------


class TestDirection:
    def test_create_direction(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(
                main,
                [
                    "direction",
                    "create",
                    "--name",
                    "attention-variants",
                    "--description",
                    "Exploring attention mechanisms",
                ],
            )
            assert result.exit_code == 0
            assert "Direction created" in result.output
            assert "attention-variants" in result.output

    def test_create_direction_with_tags(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(
                main,
                [
                    "direction",
                    "create",
                    "--name",
                    "attention-variants",
                    "--description",
                    "Exploring attention mechanisms",
                    "--tag",
                    "attention",
                    "--tag",
                    "memory",
                ],
            )
            assert result.exit_code == 0

    def test_create_direction_requires_name(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(
                main,
                [
                    "direction",
                    "create",
                    "--description",
                    "Exploring attention mechanisms",
                ],
            )
            assert result.exit_code != 0

    def test_create_direction_requires_description(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(
                main,
                [
                    "direction",
                    "create",
                    "--name",
                    "attention-variants",
                ],
            )
            assert result.exit_code != 0

    def test_list_directions_empty(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(main, ["direction", "list"])
            assert result.exit_code == 0
            assert "No directions found" in result.output

    def test_list_directions(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            runner.invoke(
                main,
                [
                    "direction",
                    "create",
                    "--name",
                    "attention-variants",
                    "--description",
                    "Exploring attention",
                ],
            )
            runner.invoke(
                main,
                [
                    "direction",
                    "create",
                    "--name",
                    "learning-rate",
                    "--description",
                    "Exploring LR schedules",
                ],
            )
            result = runner.invoke(main, ["direction", "list"])
            assert result.exit_code == 0
            assert "attention-variants" in result.output
            assert "learning-rate" in result.output

    def test_direction_before_init_fails(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            result = runner.invoke(
                main,
                [
                    "direction",
                    "create",
                    "--name",
                    "attention-variants",
                    "--description",
                    "Exploring attention",
                ],
            )
            assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_uninitialized(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            result = runner.invoke(main, ["status"])
            assert result.exit_code == 0
            assert "not initialized" in result.output.lower()

    def test_status_initialized(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner, agent_id="agent-47")
            result = runner.invoke(main, ["status"])
            assert result.exit_code == 0
            assert "Spore Status" in result.output
            assert "agent-47" in result.output

    def test_status_shows_correct_counts(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "MQA is effective",
                    "--direction",
                    "attention-variants",
                ],
            )
            result = runner.invoke(main, ["status"])
            assert result.exit_code == 0
            assert "1 running" in result.output
            assert "1 total" in result.output


# ---------------------------------------------------------------------------
# Index rebuild
# ---------------------------------------------------------------------------


class TestIndexRebuild:
    def test_index_rebuild(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "MQA is effective",
                    "--direction",
                    "attention-variants",
                ],
            )
            result = runner.invoke(main, ["index", "rebuild"])
            assert result.exit_code == 0
            assert "Index rebuilt" in result.output
            assert "1 findings indexed" in result.output

    def test_index_rebuild_empty(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(main, ["index", "rebuild"])
            assert result.exit_code == 0
            assert "0 findings indexed" in result.output


# ---------------------------------------------------------------------------
# Lineage
# ---------------------------------------------------------------------------


class TestLineage:
    def test_lineage_no_ancestors(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            publish_result = runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "MQA is effective",
                    "--direction",
                    "attention-variants",
                ],
            )
            finding_id = extract_id_from_panel(publish_result.output, "ID")
            assert finding_id is not None

            result = runner.invoke(main, ["lineage", finding_id])
            assert result.exit_code == 0
            assert "No lineage found" in result.output

    def test_lineage_with_ancestors(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            runner.invoke(
                main,
                [
                    "experiment",
                    "start",
                    "--direction",
                    "attention-variants",
                    "--hypothesis",
                    "MQA reduces memory",
                    "--no-branch",
                ],
            )
            parent_result = runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "MQA is effective",
                    "--direction",
                    "attention-variants",
                ],
            )
            parent_id = extract_id_from_panel(parent_result.output, "ID")
            assert parent_id is not None

            child_result = runner.invoke(
                main,
                [
                    "finding",
                    "publish",
                    "--claim",
                    "MQA with more heads is even better",
                    "--direction",
                    "attention-variants",
                    "--builds-on",
                    parent_id,
                ],
            )
            child_id = extract_id_from_panel(child_result.output, "ID")
            assert child_id is not None

            result = runner.invoke(main, ["lineage", child_id])
            assert result.exit_code == 0
            assert "Finding Lineage" in result.output
            assert parent_id in result.output

    def test_lineage_nonexistent_finding(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            make_git_repo(fs)
            init_spore(runner)
            result = runner.invoke(main, ["lineage", "f-notexist"])
            assert result.exit_code == 0
            assert "No lineage found" in result.output
