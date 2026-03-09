"""Protocol data models for Spore.

These Pydantic models define the core protocol objects: Findings, Experiments,
and Directions. They are the contract between agents and the Spore system.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import yaml
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FindingStatus(StrEnum):
    PUBLISHED = "published"
    RETRACTED = "retracted"
    SUPERSEDED = "superseded"


class ExperimentStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class ArtifactType(StrEnum):
    COMMIT = "commit"
    CHECKPOINT = "checkpoint"
    FILE = "file"
    URL = "url"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class Artifact(BaseModel):
    type: ArtifactType
    ref: str
    description: str | None = None


class Evidence(BaseModel):
    metrics: dict[str, float] = Field(default_factory=dict)
    baseline: dict[str, Any] | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    notes: str | None = None


# ---------------------------------------------------------------------------
# Core protocol objects
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    """A structured research claim with evidence.

    The fundamental unit of knowledge exchange in Spore. Agents publish
    findings; other agents discover and build on them.
    """

    id: str = ""
    experiment_id: str
    agent_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    direction: str

    claim: str
    hypothesis: str | None = None
    evidence: Evidence = Field(default_factory=Evidence)

    builds_on: list[str] = Field(default_factory=list)
    applicability: list[str] = Field(default_factory=list)
    significance: float = Field(default=0.5, ge=0.0, le=1.0)
    status: FindingStatus = FindingStatus.PUBLISHED

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            self.id = self._generate_id()

    def _generate_id(self) -> str:
        hashable = {
            "experiment_id": self.experiment_id,
            "agent_id": self.agent_id,
            "direction": self.direction,
            "claim": self.claim,
            "timestamp": self.timestamp.isoformat(),
        }
        content = json.dumps(hashable, sort_keys=True)
        h = hashlib.sha256(content.encode()).hexdigest()[:12]
        return f"f-{h}"

    def to_yaml(self) -> str:
        data = self.model_dump(mode="json")
        return yaml.dump(data, default_flow_style=False, sort_keys=False, Dumper=yaml.SafeDumper)

    @classmethod
    def from_yaml(cls, text: str) -> Finding:
        data = yaml.safe_load(text)
        if data is None:
            raise ValueError("Cannot parse Finding from empty YAML")
        return cls.model_validate(data)


class Experiment(BaseModel):
    """A sequence of iterations exploring a research hypothesis.

    Each experiment runs on its own Git branch and may produce zero or
    more Findings.
    """

    id: str = ""
    agent_id: str
    branch: str = ""
    direction: str
    hypothesis: str

    status: ExperimentStatus = ExperimentStatus.RUNNING
    started: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed: datetime | None = None
    iterations: int = 0
    findings: list[str] = Field(default_factory=list)
    builds_on: list[str] = Field(default_factory=list)
    config: dict[str, Any] | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            self.id = self._generate_id()
        if not self.branch:
            # Sanitize for valid git branch names
            safe_dir = re.sub(r"[^a-z0-9_-]", "-", self.direction.lower())[:30]
            safe_dir = safe_dir.strip("-")
            safe_agent = re.sub(r"[^a-z0-9_-]", "-", self.agent_id.lower())[:30]
            self.branch = f"spore/{safe_agent}/{safe_dir}"

    def _generate_id(self) -> str:
        hashable = {
            "agent_id": self.agent_id,
            "direction": self.direction,
            "hypothesis": self.hypothesis,
            "started": self.started.isoformat(),
        }
        content = json.dumps(hashable, sort_keys=True)
        h = hashlib.sha256(content.encode()).hexdigest()[:12]
        return f"exp-{h}"

    def to_yaml(self) -> str:
        data = self.model_dump(mode="json")
        return yaml.dump(data, default_flow_style=False, sort_keys=False, Dumper=yaml.SafeDumper)

    @classmethod
    def from_yaml(cls, text: str) -> Experiment:
        data = yaml.safe_load(text)
        if data is None:
            raise ValueError("Cannot parse Experiment from empty YAML")
        return cls.model_validate(data)


class Direction(BaseModel):
    """A research area that groups related experiments."""

    id: str = ""
    name: str
    description: str
    parent_directions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            self.id = self._generate_id()

    def _generate_id(self) -> str:
        h = hashlib.sha256(self.name.lower().encode()).hexdigest()[:12]
        return f"dir-{h}"

    def to_yaml(self) -> str:
        data = self.model_dump(mode="json")
        return yaml.dump(data, default_flow_style=False, sort_keys=False, Dumper=yaml.SafeDumper)

    @classmethod
    def from_yaml(cls, text: str) -> Direction:
        data = yaml.safe_load(text)
        if data is None:
            raise ValueError("Cannot parse Direction from empty YAML")
        return cls.model_validate(data)


class SporeConfig(BaseModel):
    """Repository-level Spore configuration."""

    version: str = "0.2.0"
    repo_name: str | None = None
    default_direction: str | None = None
    agent_id: str | None = None

    def to_yaml(self) -> str:
        data = self.model_dump(mode="json", exclude_none=True)
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    @classmethod
    def from_yaml(cls, text: str) -> SporeConfig:
        data = yaml.safe_load(text)
        if data is None:
            return cls()
        return cls.model_validate(data)
