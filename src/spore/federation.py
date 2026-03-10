"""Cross-repo federation for Spore.

Enables agents in different Git repositories to discover each other's
findings. This is the "SETI@home for research" layer — a decentralized
network of Spore-enabled repos that share knowledge without a central
coordinator.

Supports two federation modes:
1. **Direct peers** — manually added with `federation add <url>`
2. **Hub** — join a community with `federation join <hub-url>`,
   which auto-discovers all peers listed in the hub.

Usage:
    # Direct peer
    repo.add_peer("https://github.com/lab-a/experiments.git")

    # Hub (one command to join a whole community)
    repo.join_hub("https://raw.githubusercontent.com/org/hub/main/hub.yaml")

    repo.sync_peers()
    results = repo.discover_federated(direction="attention")
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import urllib.error
import urllib.request
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
        self._hub_url: str | None = None

    @property
    def peers(self) -> list[FederationPeer]:
        if self._peers is None:
            self._peers = self._load_peers()
        return self._peers

    @property
    def hub_url(self) -> str | None:
        """The hub URL this registry is subscribed to, if any."""
        if self._hub_url is None:
            self._hub_url = self._load_hub_url()
        return self._hub_url

    def _load_peers(self) -> list[FederationPeer]:
        if not self.federation_path.exists():
            return []
        data = yaml.safe_load(self.federation_path.read_text())
        if not data or "peers" not in data:
            return []
        return [FederationPeer.from_dict(p) for p in data["peers"]]

    def _load_hub_url(self) -> str | None:
        if not self.federation_path.exists():
            return None
        data = yaml.safe_load(self.federation_path.read_text())
        if not data:
            return None
        return data.get("hub")

    def _save(self) -> None:
        data: dict[str, Any] = {"version": "1"}
        if self._hub_url:
            data["hub"] = self._hub_url
        data["peers"] = [p.to_dict() for p in self.peers]
        self.federation_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

    def _save_peers(self) -> None:
        self._save()

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

    # ------------------------------------------------------------------
    # Hub
    # ------------------------------------------------------------------

    def join_hub(self, hub_url: str) -> list[FederationPeer]:
        """Join a federation hub.

        Fetches the hub YAML, registers all listed peers, and stores the
        hub URL so future syncs re-fetch it automatically.

        Args:
            hub_url: URL to a hub YAML file (HTTP/HTTPS or file://).

        Returns:
            List of peers added from the hub.
        """
        hub_peers = self._fetch_hub(hub_url)
        self._hub_url = hub_url

        added: list[FederationPeer] = []
        for peer in hub_peers:
            existing = next((p for p in self.peers if p.url == peer.url), None)
            if not existing:
                self.peers.append(peer)
                added.append(peer)

        self._save()
        return added

    def refresh_hub(self) -> list[FederationPeer]:
        """Re-fetch the hub and merge any new peers.

        Returns newly added peers. If no hub is configured, returns [].
        """
        if not self.hub_url:
            return []
        return self.join_hub(self.hub_url)

    @staticmethod
    def _fetch_hub(hub_url: str) -> list[FederationPeer]:
        """Fetch and parse a hub YAML from a URL."""
        try:
            with urllib.request.urlopen(hub_url, timeout=15) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8")
        except (urllib.error.URLError, OSError) as e:
            logger.warning("Failed to fetch hub %s: %s", hub_url, e)
            return []

        data = yaml.safe_load(raw)
        if not data or "peers" not in data:
            logger.warning("Hub %s has no peers list", hub_url)
            return []

        return [FederationPeer.from_dict(p) for p in data["peers"]]

    @staticmethod
    def generate_hub(
        name: str,
        description: str = "",
        peers: list[dict[str, Any]] | None = None,
    ) -> str:
        """Generate a hub YAML template.

        Returns YAML string suitable for hosting as a hub file.
        """
        data: dict[str, Any] = {"name": name}
        if description:
            data["description"] = description
        data["peers"] = peers or []
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

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
        """Sync all peers. Returns mapping of peer name to cache path.

        If a hub is configured, re-fetches it first to pick up new peers.
        """
        # Refresh hub to discover newly added peers
        self.refresh_hub()

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
