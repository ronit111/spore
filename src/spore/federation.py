"""Cross-repo federation for Spore.

Enables agents in different Git repositories to discover each other's
findings. This is the "SETI@home for research" layer — a decentralized
network of Spore-enabled repos that share knowledge without a central
coordinator.

Usage:
    repo.add_peer("https://github.com/lab-a/experiments.git")
    repo.sync_peers()
    results = repo.discover_federated(direction="attention")
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import git
import yaml

if TYPE_CHECKING:
    from spore.index import SporeIndex

from spore.models import Finding

logger = logging.getLogger("spore")

FEDERATION_FILE = "federation.yaml"
PEER_CACHE_DIR = ".cache/peers"


class FederationPeer:
    """A registered peer repository in the federation."""

    def __init__(
        self,
        url: str,
        name: str | None = None,
        directions: list[str] | None = None,
    ) -> None:
        self.url = url
        self.name = name or self._name_from_url(url)
        self.directions = directions or []
        self.id = hashlib.sha256(url.encode()).hexdigest()[:12]

    @staticmethod
    def _name_from_url(url: str) -> str:
        """Extract a human-readable name from a Git URL."""
        name = url.rstrip("/").split("/")[-1]
        if name.endswith(".git"):
            name = name[:-4]
        return name

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"url": self.url, "name": self.name}
        if self.directions:
            data["directions"] = self.directions
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FederationPeer:
        return cls(
            url=data["url"],
            name=data.get("name"),
            directions=data.get("directions", []),
        )


class FederationRegistry:
    """Manages the federation peer list and cached clones.

    The registry is stored in `.spore/federation.yaml` and cached peer
    repos live in `.spore/.cache/peers/<peer-hash>/`.
    """

    def __init__(self, spore_dir: Path) -> None:
        self.spore_dir = spore_dir
        self.federation_path = spore_dir / FEDERATION_FILE
        self.cache_dir = spore_dir / PEER_CACHE_DIR
        self._peers: list[FederationPeer] | None = None

    @property
    def peers(self) -> list[FederationPeer]:
        if self._peers is None:
            self._peers = self._load_peers()
        return self._peers

    def _load_peers(self) -> list[FederationPeer]:
        if not self.federation_path.exists():
            return []
        data = yaml.safe_load(self.federation_path.read_text())
        if not data or "peers" not in data:
            return []
        return [FederationPeer.from_dict(p) for p in data["peers"]]

    def _save_peers(self) -> None:
        data = {
            "version": "1",
            "peers": [p.to_dict() for p in self.peers],
        }
        self.federation_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

    def add_peer(
        self,
        url: str,
        name: str | None = None,
        directions: list[str] | None = None,
    ) -> FederationPeer:
        """Register a new peer repository."""
        # Check for duplicates
        for existing in self.peers:
            if existing.url == url:
                return existing

        peer = FederationPeer(url=url, name=name, directions=directions)
        self.peers.append(peer)
        self._save_peers()
        return peer

    def remove_peer(self, url: str) -> bool:
        """Remove a peer by URL. Returns True if found and removed."""
        before = len(self.peers)
        self._peers = [p for p in self.peers if p.url != url]
        if len(self._peers) < before:
            self._save_peers()
            # Clean up cached clone
            removed = [p for p in self._load_peers() if p.url == url]
            if not removed:
                # Peer was removed, clean cache
                peer_id = hashlib.sha256(url.encode()).hexdigest()[:12]
                cache_path = self.cache_dir / peer_id
                if cache_path.exists():
                    shutil.rmtree(cache_path, ignore_errors=True)
            return True
        return False

    def list_peers(self) -> list[FederationPeer]:
        """List all registered peers."""
        return list(self.peers)

    def sync_peer(self, peer: FederationPeer) -> Path:
        """Clone or update a peer's cached repository.

        Uses shallow clone (depth=1) to minimize bandwidth and storage.
        Returns the path to the cached repo.
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self.cache_dir / peer.id

        if cache_path.exists():
            # Update existing clone
            try:
                repo = git.Repo(cache_path)
                repo.remotes.origin.fetch(depth=1)
                # Reset to latest remote HEAD
                for remote_ref in repo.remotes.origin.refs:
                    if remote_ref.remote_head in ("main", "master", "HEAD"):
                        repo.head.reset(remote_ref.commit, working_tree=True)
                        break
                logger.debug("Updated peer cache: %s", peer.name)
            except Exception as e:
                logger.debug("Failed to update peer %s, re-cloning: %s", peer.name, e)
                shutil.rmtree(cache_path, ignore_errors=True)
                git.Repo.clone_from(
                    peer.url,
                    str(cache_path),
                    depth=1,
                    no_single_branch=True,
                )
        else:
            # Fresh shallow clone
            git.Repo.clone_from(
                peer.url,
                str(cache_path),
                depth=1,
                no_single_branch=True,
            )
            logger.debug("Cloned peer: %s", peer.name)

        return cache_path

    def sync_all(self) -> dict[str, Path]:
        """Sync all peers. Returns mapping of peer name to cache path."""
        results: dict[str, Path] = {}
        for peer in self.peers:
            try:
                path = self.sync_peer(peer)
                results[peer.name] = path
            except Exception as e:
                logger.warning("Failed to sync peer %s: %s", peer.name, e)
        return results

    def discover_from_peer(
        self,
        peer: FederationPeer,
        index: SporeIndex,
        direction: str | None = None,
    ) -> list[Finding]:
        """Discover findings from a single peer's cached repo."""
        cache_path = self.cache_dir / peer.id
        findings_dir = cache_path / ".spore" / "findings"

        if not findings_dir.exists():
            return []

        findings: list[Finding] = []
        for yaml_file in findings_dir.glob("*.yaml"):
            try:
                finding = Finding.from_yaml(yaml_file.read_text())
                if direction and direction.lower() not in finding.direction.lower():
                    continue
                index.add_finding(finding, source_branch=f"federation:{peer.name}")
                findings.append(finding)
            except Exception as e:
                logger.debug("Failed to parse finding from peer %s: %s", peer.name, e)

        return findings

    def discover_all(
        self,
        index: SporeIndex,
        direction: str | None = None,
        limit: int = 50,
    ) -> list[Finding]:
        """Sync all peers and discover findings.

        This is the main entry point for federated discovery. It:
        1. Fetches latest from all peer repos
        2. Scans their .spore/findings/ directories
        3. Indexes findings locally
        4. Returns results sorted by significance
        """
        # Sync first
        self.sync_all()

        # Discover from all peers
        all_findings: list[Finding] = []
        seen_ids: set[str] = set()

        for peer in self.peers:
            findings = self.discover_from_peer(peer, index, direction)
            for f in findings:
                if f.id not in seen_ids:
                    seen_ids.add(f.id)
                    all_findings.append(f)

        all_findings.sort(key=lambda f: f.significance, reverse=True)
        return all_findings[:limit]
