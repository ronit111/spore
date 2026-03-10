"""Spore — A protocol for autonomous research agent coordination.

Spore enables AI research agents to publish, discover, and build on each
other's findings through a Git-native, decentralized protocol.

    import spore

    # Initialize a repo for Spore
    repo = spore.SporeRepo(".")
    repo.init()

    # Publish a finding
    finding = repo.publish_finding(
        direction="attention-variants",
        claim="Multi-query attention reduces val_bpb by 0.02",
        metrics={"val_bpb": 0.4523, "delta": -0.0201},
    )

    # Discover findings from other agents
    results = repo.discover(direction="attention")
"""

__version__ = "0.4.0"

from spore.federation import FederationPeer, FederationRegistry
from spore.index import compute_earned_significance
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
from spore.repo import SporeRepo
from spore.watch import SporeWatcher

__all__ = [
    "Artifact",
    "ArtifactType",
    "Direction",
    "Evidence",
    "Experiment",
    "ExperimentStatus",
    "FederationPeer",
    "FederationRegistry",
    "Finding",
    "FindingStatus",
    "SporeConfig",
    "SporeRepo",
    "SporeWatcher",
    "compute_earned_significance",
]
