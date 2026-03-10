"""Unit tests for Spore protocol models."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from spore.models import (
    Artifact,
    ArtifactType,
    Direction,
    Evidence,
    Experiment,
    ExperimentStatus,
    Finding,
    FindingStatus,
    SporeConfig,
)

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestFindingStatus:
    def test_values(self):
        assert FindingStatus.PUBLISHED == "published"
        assert FindingStatus.RETRACTED == "retracted"
        assert FindingStatus.SUPERSEDED == "superseded"

    def test_is_str_enum(self):
        assert isinstance(FindingStatus.PUBLISHED, str)

    def test_all_members(self):
        members = {e.value for e in FindingStatus}
        assert members == {"published", "retracted", "superseded"}


class TestExperimentStatus:
    def test_values(self):
        assert ExperimentStatus.RUNNING == "running"
        assert ExperimentStatus.COMPLETED == "completed"
        assert ExperimentStatus.ABANDONED == "abandoned"

    def test_is_str_enum(self):
        assert isinstance(ExperimentStatus.RUNNING, str)

    def test_all_members(self):
        members = {e.value for e in ExperimentStatus}
        assert members == {"running", "completed", "abandoned"}


class TestArtifactType:
    def test_values(self):
        assert ArtifactType.COMMIT == "commit"
        assert ArtifactType.CHECKPOINT == "checkpoint"
        assert ArtifactType.FILE == "file"
        assert ArtifactType.URL == "url"

    def test_is_str_enum(self):
        assert isinstance(ArtifactType.COMMIT, str)

    def test_all_members(self):
        members = {e.value for e in ArtifactType}
        assert members == {"commit", "checkpoint", "file", "url"}


# ---------------------------------------------------------------------------
# Artifact tests
# ---------------------------------------------------------------------------


class TestArtifact:
    def test_required_fields(self):
        a = Artifact(type=ArtifactType.COMMIT, ref="abc123")
        assert a.type == ArtifactType.COMMIT
        assert a.ref == "abc123"
        assert a.description is None

    def test_with_description(self):
        a = Artifact(type=ArtifactType.FILE, ref="/path/to/file.py", description="Model weights")
        assert a.description == "Model weights"

    def test_url_type(self):
        a = Artifact(type=ArtifactType.URL, ref="https://example.com/model")
        assert a.type == ArtifactType.URL

    def test_checkpoint_type(self):
        a = Artifact(type=ArtifactType.CHECKPOINT, ref="step-1000")
        assert a.type == ArtifactType.CHECKPOINT

    def test_string_enum_value_accepted(self):
        a = Artifact(type="commit", ref="abc123")
        assert a.type == ArtifactType.COMMIT


# ---------------------------------------------------------------------------
# Evidence tests
# ---------------------------------------------------------------------------


class TestEvidence:
    def test_defaults(self):
        e = Evidence()
        assert e.metrics == {}
        assert e.baseline is None
        assert e.artifacts == []
        assert e.notes is None

    def test_with_metrics(self):
        e = Evidence(metrics={"val_bpb": 0.45, "loss": 1.2})
        assert e.metrics["val_bpb"] == 0.45
        assert e.metrics["loss"] == 1.2

    def test_with_baseline(self):
        e = Evidence(baseline={"val_bpb": 0.47})
        assert e.baseline == {"val_bpb": 0.47}

    def test_with_artifacts(self):
        artifact = Artifact(type=ArtifactType.COMMIT, ref="abc123")
        e = Evidence(artifacts=[artifact])
        assert len(e.artifacts) == 1
        assert e.artifacts[0].ref == "abc123"

    def test_with_notes(self):
        e = Evidence(notes="Ran for 10k steps on A100")
        assert e.notes == "Ran for 10k steps on A100"

    def test_default_factories_are_independent(self):
        e1 = Evidence()
        e2 = Evidence()
        e1.metrics["key"] = 1.0
        assert "key" not in e2.metrics
        e1.artifacts.append(Artifact(type=ArtifactType.FILE, ref="f"))
        assert len(e2.artifacts) == 0


# ---------------------------------------------------------------------------
# Finding tests
# ---------------------------------------------------------------------------


FINDING_REQUIRED = dict(
    experiment_id="exp-abc123",
    agent_id="agent-1",
    direction="attention-variants",
    claim="MQA reduces memory by 40%",
)


class TestFindingCreation:
    def test_required_fields(self):
        f = Finding(**FINDING_REQUIRED)
        assert f.experiment_id == "exp-abc123"
        assert f.agent_id == "agent-1"
        assert f.direction == "attention-variants"
        assert f.claim == "MQA reduces memory by 40%"

    def test_defaults(self):
        f = Finding(**FINDING_REQUIRED)
        assert f.status == FindingStatus.PUBLISHED
        assert f.significance == 0.5
        assert f.hypothesis is None
        assert f.builds_on == []
        assert f.applicability == []
        assert isinstance(f.evidence, Evidence)
        assert isinstance(f.timestamp, datetime)

    def test_id_auto_generated(self):
        f = Finding(**FINDING_REQUIRED)
        assert f.id.startswith("f-")
        assert len(f.id) == 14  # "f-" + 12 hex chars

    def test_id_not_overwritten_when_provided(self):
        f = Finding(**FINDING_REQUIRED, id="f-custom")
        assert f.id == "f-custom"

    def test_timestamp_is_utc(self):
        f = Finding(**FINDING_REQUIRED)
        assert f.timestamp.tzinfo is not None

    def test_optional_fields(self):
        f = Finding(
            **FINDING_REQUIRED,
            hypothesis="H1",
            builds_on=["f-111"],
            applicability=["attention"],
            significance=0.8,
            status=FindingStatus.RETRACTED,
        )
        assert f.hypothesis == "H1"
        assert f.builds_on == ["f-111"]
        assert f.applicability == ["attention"]
        assert f.significance == 0.8
        assert f.status == FindingStatus.RETRACTED


class TestFindingIdGeneration:
    def test_deterministic_same_inputs(self):
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        f1 = Finding(**FINDING_REQUIRED, timestamp=ts)
        f2 = Finding(**FINDING_REQUIRED, timestamp=ts)
        assert f1.id == f2.id

    def test_different_claim_produces_different_id(self):
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        f1 = Finding(**FINDING_REQUIRED, timestamp=ts)
        f2 = Finding(**{**FINDING_REQUIRED, "claim": "Different claim"}, timestamp=ts)
        assert f1.id != f2.id

    def test_different_agent_produces_different_id(self):
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        f1 = Finding(**FINDING_REQUIRED, timestamp=ts)
        f2 = Finding(**{**FINDING_REQUIRED, "agent_id": "agent-2"}, timestamp=ts)
        assert f1.id != f2.id

    def test_id_format(self):
        f = Finding(**FINDING_REQUIRED)
        parts = f.id.split("-")
        assert parts[0] == "f"
        assert len(parts[1]) == 12

    def test_id_matches_manual_hash(self):
        ts = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        f = Finding(**FINDING_REQUIRED, timestamp=ts)
        hashable = {
            "experiment_id": FINDING_REQUIRED["experiment_id"],
            "agent_id": FINDING_REQUIRED["agent_id"],
            "direction": FINDING_REQUIRED["direction"],
            "claim": FINDING_REQUIRED["claim"],
            "timestamp": ts.isoformat(),
        }
        content = json.dumps(hashable, sort_keys=True)
        expected = "f-" + hashlib.sha256(content.encode()).hexdigest()[:12]
        assert f.id == expected


class TestFindingSignificanceClamping:
    def test_valid_significance(self):
        f = Finding(**FINDING_REQUIRED, significance=0.7)
        assert f.significance == 0.7

    def test_significance_zero(self):
        f = Finding(**FINDING_REQUIRED, significance=0.0)
        assert f.significance == 0.0

    def test_significance_one(self):
        f = Finding(**FINDING_REQUIRED, significance=1.0)
        assert f.significance == 1.0

    def test_significance_above_one_raises(self):
        # Pydantic's ge/le Field constraint runs before the field_validator,
        # so out-of-range values raise ValidationError rather than being clamped.
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Finding(**FINDING_REQUIRED, significance=1.5)

    def test_significance_below_zero_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Finding(**FINDING_REQUIRED, significance=-0.5)


class TestFindingYamlRoundtrip:
    def test_basic_roundtrip(self):
        f = Finding(**FINDING_REQUIRED)
        yaml_str = f.to_yaml()
        f2 = Finding.from_yaml(yaml_str)
        assert f2.id == f.id
        assert f2.claim == f.claim
        assert f2.agent_id == f.agent_id
        assert f2.experiment_id == f.experiment_id
        assert f2.direction == f.direction
        assert f2.status == f.status
        assert f2.significance == f.significance

    def test_roundtrip_preserves_evidence(self):
        evidence = Evidence(
            metrics={"val_bpb": 0.45},
            notes="good run",
            artifacts=[Artifact(type=ArtifactType.COMMIT, ref="abc123")],
        )
        f = Finding(**FINDING_REQUIRED, evidence=evidence)
        f2 = Finding.from_yaml(f.to_yaml())
        assert f2.evidence.metrics == {"val_bpb": 0.45}
        assert f2.evidence.notes == "good run"
        assert f2.evidence.artifacts[0].ref == "abc123"

    def test_roundtrip_preserves_lists(self):
        f = Finding(**FINDING_REQUIRED, builds_on=["f-aaa", "f-bbb"], applicability=["attn"])
        f2 = Finding.from_yaml(f.to_yaml())
        assert f2.builds_on == ["f-aaa", "f-bbb"]
        assert f2.applicability == ["attn"]

    def test_yaml_output_is_string(self):
        f = Finding(**FINDING_REQUIRED)
        assert isinstance(f.to_yaml(), str)


class TestFindingEdgeCases:
    def test_empty_claim(self):
        f = Finding(**{**FINDING_REQUIRED, "claim": ""})
        assert f.claim == ""
        assert f.id.startswith("f-")

    def test_very_long_claim(self):
        long_claim = "A" * 10000
        f = Finding(**{**FINDING_REQUIRED, "claim": long_claim})
        assert f.claim == long_claim
        assert f.id.startswith("f-")

    def test_special_characters_in_claim(self):
        claim = "val_bpb: 0.45 (Δ -0.02) — 'quoted' & <tagged>"
        f = Finding(**{**FINDING_REQUIRED, "claim": claim})
        f2 = Finding.from_yaml(f.to_yaml())
        assert f2.claim == claim

    def test_unicode_in_claim(self):
        claim = "Reducción de memoria: αβγ 测试 🧪"
        f = Finding(**{**FINDING_REQUIRED, "claim": claim})
        f2 = Finding.from_yaml(f.to_yaml())
        assert f2.claim == claim

    def test_none_hypothesis_roundtrip(self):
        f = Finding(**FINDING_REQUIRED, hypothesis=None)
        f2 = Finding.from_yaml(f.to_yaml())
        assert f2.hypothesis is None

    def test_newlines_in_claim(self):
        claim = "Line one\nLine two\nLine three"
        f = Finding(**{**FINDING_REQUIRED, "claim": claim})
        f2 = Finding.from_yaml(f.to_yaml())
        assert f2.claim == claim


# ---------------------------------------------------------------------------
# Experiment tests
# ---------------------------------------------------------------------------


EXPERIMENT_REQUIRED = dict(
    agent_id="agent-1",
    direction="attention-variants",
    hypothesis="MQA reduces memory without hurting quality",
)


class TestExperimentCreation:
    def test_required_fields(self):
        e = Experiment(**EXPERIMENT_REQUIRED)
        assert e.agent_id == "agent-1"
        assert e.direction == "attention-variants"
        assert e.hypothesis == "MQA reduces memory without hurting quality"

    def test_defaults(self):
        e = Experiment(**EXPERIMENT_REQUIRED)
        assert e.status == ExperimentStatus.RUNNING
        assert e.iterations == 0
        assert e.findings == []
        assert e.builds_on == []
        assert e.completed is None
        assert e.config is None
        assert isinstance(e.started, datetime)

    def test_id_auto_generated(self):
        e = Experiment(**EXPERIMENT_REQUIRED)
        assert e.id.startswith("exp-")
        assert len(e.id) == 16  # "exp-" + 12 hex chars

    def test_id_not_overwritten_when_provided(self):
        e = Experiment(**EXPERIMENT_REQUIRED, id="exp-custom")
        assert e.id == "exp-custom"


class TestExperimentBranchGeneration:
    def test_branch_auto_generated(self):
        e = Experiment(**EXPERIMENT_REQUIRED)
        assert e.branch == "spore/agent-1/attention-variants"

    def test_branch_uses_agent_id(self):
        e = Experiment(**{**EXPERIMENT_REQUIRED, "agent_id": "my-agent"})
        assert e.branch.startswith("spore/my-agent/")

    def test_branch_direction_lowercased(self):
        e = Experiment(**{**EXPERIMENT_REQUIRED, "direction": "Attention-Variants"})
        assert "attention-variants" in e.branch.lower()

    def test_branch_spaces_replaced_with_hyphens(self):
        e = Experiment(**{**EXPERIMENT_REQUIRED, "direction": "multi head attention"})
        assert " " not in e.branch
        assert "multi-head-attention" in e.branch

    def test_branch_direction_truncated_at_30(self):
        long_direction = "a" * 50
        e = Experiment(**{**EXPERIMENT_REQUIRED, "direction": long_direction})
        dir_part = e.branch.split("/")[-1]
        assert len(dir_part) <= 30

    def test_branch_not_overwritten_when_provided(self):
        e = Experiment(**EXPERIMENT_REQUIRED, branch="custom/branch")
        assert e.branch == "custom/branch"


class TestExperimentIdGeneration:
    def test_deterministic_same_inputs(self):
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        e1 = Experiment(**EXPERIMENT_REQUIRED, started=ts)
        e2 = Experiment(**EXPERIMENT_REQUIRED, started=ts)
        assert e1.id == e2.id

    def test_different_hypothesis_produces_different_id(self):
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        e1 = Experiment(**EXPERIMENT_REQUIRED, started=ts)
        e2 = Experiment(**{**EXPERIMENT_REQUIRED, "hypothesis": "Different hypothesis"}, started=ts)
        assert e1.id != e2.id

    def test_id_matches_manual_hash(self):
        ts = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        e = Experiment(**EXPERIMENT_REQUIRED, started=ts)
        hashable = {
            "agent_id": EXPERIMENT_REQUIRED["agent_id"],
            "direction": EXPERIMENT_REQUIRED["direction"],
            "hypothesis": EXPERIMENT_REQUIRED["hypothesis"],
            "started": ts.isoformat(),
        }
        content = json.dumps(hashable, sort_keys=True)
        expected = "exp-" + hashlib.sha256(content.encode()).hexdigest()[:12]
        assert e.id == expected


class TestExperimentYamlRoundtrip:
    def test_basic_roundtrip(self):
        e = Experiment(**EXPERIMENT_REQUIRED)
        e2 = Experiment.from_yaml(e.to_yaml())
        assert e2.id == e.id
        assert e2.agent_id == e.agent_id
        assert e2.direction == e.direction
        assert e2.hypothesis == e.hypothesis
        assert e2.status == e.status
        assert e2.branch == e.branch

    def test_roundtrip_preserves_status(self):
        e = Experiment(**EXPERIMENT_REQUIRED, status=ExperimentStatus.COMPLETED)
        e2 = Experiment.from_yaml(e.to_yaml())
        assert e2.status == ExperimentStatus.COMPLETED

    def test_roundtrip_preserves_findings_list(self):
        e = Experiment(**EXPERIMENT_REQUIRED, findings=["f-aaa", "f-bbb"])
        e2 = Experiment.from_yaml(e.to_yaml())
        assert e2.findings == ["f-aaa", "f-bbb"]

    def test_roundtrip_with_config(self):
        config = {"lr": 0.001, "batch_size": 32}
        e = Experiment(**EXPERIMENT_REQUIRED, config=config)
        e2 = Experiment.from_yaml(e.to_yaml())
        assert e2.config == config

    def test_roundtrip_with_completed_timestamp(self):
        ts = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        e = Experiment(**EXPERIMENT_REQUIRED, completed=ts, status=ExperimentStatus.COMPLETED)
        e2 = Experiment.from_yaml(e.to_yaml())
        assert e2.completed is not None
        assert e2.status == ExperimentStatus.COMPLETED


class TestExperimentEdgeCases:
    def test_empty_direction(self):
        e = Experiment(**{**EXPERIMENT_REQUIRED, "direction": ""})
        assert e.direction == ""
        assert e.branch == "spore/agent-1/"

    def test_special_chars_in_direction_for_branch(self):
        e = Experiment(**{**EXPERIMENT_REQUIRED, "direction": "LR/Scheduler Tests"})
        assert " " not in e.branch

    def test_none_optional_fields_roundtrip(self):
        e = Experiment(**EXPERIMENT_REQUIRED)
        assert e.completed is None
        assert e.config is None
        e2 = Experiment.from_yaml(e.to_yaml())
        assert e2.completed is None
        assert e2.config is None


# ---------------------------------------------------------------------------
# Direction tests
# ---------------------------------------------------------------------------


DIRECTION_REQUIRED = dict(
    name="Attention Variants",
    description="Exploring different attention mechanisms",
)


class TestDirectionCreation:
    def test_required_fields(self):
        d = Direction(**DIRECTION_REQUIRED)
        assert d.name == "Attention Variants"
        assert d.description == "Exploring different attention mechanisms"

    def test_defaults(self):
        d = Direction(**DIRECTION_REQUIRED)
        assert d.parent_directions == []
        assert d.tags == []

    def test_id_auto_generated(self):
        d = Direction(**DIRECTION_REQUIRED)
        assert d.id.startswith("dir-")
        assert len(d.id) == 16  # "dir-" + 12 hex chars

    def test_id_not_overwritten_when_provided(self):
        d = Direction(**DIRECTION_REQUIRED, id="dir-custom")
        assert d.id == "dir-custom"


class TestDirectionIdGeneration:
    def test_deterministic_same_name(self):
        d1 = Direction(**DIRECTION_REQUIRED)
        d2 = Direction(**DIRECTION_REQUIRED)
        assert d1.id == d2.id

    def test_id_based_on_name_only(self):
        d1 = Direction(name="test", description="desc1")
        d2 = Direction(name="test", description="desc2 different")
        assert d1.id == d2.id  # description doesn't affect ID

    def test_different_names_produce_different_ids(self):
        d1 = Direction(name="Alpha", description="x")
        d2 = Direction(name="Beta", description="x")
        assert d1.id != d2.id

    def test_id_is_case_insensitive_on_name(self):
        d1 = Direction(name="Attention Variants", description="x")
        d2 = Direction(name="attention variants", description="x")
        assert d1.id == d2.id

    def test_id_matches_manual_hash(self):
        name = "Attention Variants"
        expected = "dir-" + hashlib.sha256(name.lower().encode()).hexdigest()[:12]
        d = Direction(**DIRECTION_REQUIRED)
        assert d.id == expected


class TestDirectionYamlRoundtrip:
    def test_basic_roundtrip(self):
        d = Direction(**DIRECTION_REQUIRED)
        d2 = Direction.from_yaml(d.to_yaml())
        assert d2.id == d.id
        assert d2.name == d.name
        assert d2.description == d.description

    def test_roundtrip_preserves_tags(self):
        d = Direction(**DIRECTION_REQUIRED, tags=["memory", "efficiency"])
        d2 = Direction.from_yaml(d.to_yaml())
        assert d2.tags == ["memory", "efficiency"]

    def test_roundtrip_preserves_parent_directions(self):
        d = Direction(**DIRECTION_REQUIRED, parent_directions=["dir-abc", "dir-def"])
        d2 = Direction.from_yaml(d.to_yaml())
        assert d2.parent_directions == ["dir-abc", "dir-def"]

    def test_special_chars_in_description(self):
        desc = "Exploring: <attention> & 'mechanisms' — with Δ changes"
        d = Direction(name="test", description=desc)
        d2 = Direction.from_yaml(d.to_yaml())
        assert d2.description == desc


# ---------------------------------------------------------------------------
# SporeConfig tests
# ---------------------------------------------------------------------------


class TestSporeConfigCreation:
    def test_all_defaults(self):
        c = SporeConfig()
        assert c.version == "0.4.0"
        assert c.repo_name is None
        assert c.default_direction is None
        assert c.agent_id is None

    def test_with_all_fields(self):
        c = SporeConfig(
            version="0.4.0",
            repo_name="my-repo",
            default_direction="attention-variants",
            agent_id="agent-42",
        )
        assert c.version == "0.4.0"
        assert c.repo_name == "my-repo"
        assert c.default_direction == "attention-variants"
        assert c.agent_id == "agent-42"


class TestSporeConfigYamlRoundtrip:
    def test_empty_config_roundtrip(self):
        c = SporeConfig()
        yaml_str = c.to_yaml()
        c2 = SporeConfig.from_yaml(yaml_str)
        assert c2.version == c.version
        assert c2.repo_name is None
        assert c2.agent_id is None

    def test_full_config_roundtrip(self):
        c = SporeConfig(
            version="0.4.0",
            repo_name="my-repo",
            default_direction="attention-variants",
            agent_id="agent-42",
        )
        c2 = SporeConfig.from_yaml(c.to_yaml())
        assert c2.version == "0.4.0"
        assert c2.repo_name == "my-repo"
        assert c2.default_direction == "attention-variants"
        assert c2.agent_id == "agent-42"

    def test_none_fields_excluded_from_yaml(self):
        c = SporeConfig(repo_name=None)
        yaml_str = c.to_yaml()
        assert "repo_name" not in yaml_str

    def test_from_yaml_empty_string(self):
        # Empty YAML parses to None; from_yaml handles this gracefully
        c = SporeConfig.from_yaml("")
        assert c.version == "0.4.0"

    def test_from_yaml_none_content(self):
        c = SporeConfig.from_yaml("~\n")  # YAML null
        assert c.version == "0.4.0"

    def test_version_default_preserved(self):
        c = SporeConfig(repo_name="test")
        c2 = SporeConfig.from_yaml(c.to_yaml())
        assert c2.version == "0.4.0"


# ---------------------------------------------------------------------------
# Cross-model integration-style unit tests
# ---------------------------------------------------------------------------


class TestModelInteractions:
    def test_finding_references_experiment_id(self):
        e = Experiment(**EXPERIMENT_REQUIRED)
        f = Finding(
            experiment_id=e.id,
            agent_id=e.agent_id,
            direction=e.direction,
            claim="Result from this experiment",
        )
        assert f.experiment_id == e.id

    def test_finding_builds_on_other_finding(self):
        f1 = Finding(**FINDING_REQUIRED)
        f2 = Finding(**{**FINDING_REQUIRED, "claim": "Follow-up claim"}, builds_on=[f1.id])
        assert f1.id in f2.builds_on

    def test_direction_tags_preserved_in_roundtrip(self):
        d = Direction(name="test-dir", description="x", tags=["tag1", "tag2"])
        d2 = Direction.from_yaml(d.to_yaml())
        assert set(d2.tags) == {"tag1", "tag2"}
