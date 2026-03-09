"""Unit tests for cross-repo federation (src/spore/federation.py)."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
import yaml

from spore.federation import FederationPeer, FederationRegistry
from spore.models import Finding

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# FederationPeer
# ---------------------------------------------------------------------------


class TestFederationPeer:
    def test_basic_creation(self):
        peer = FederationPeer(url="https://github.com/lab-a/experiments.git")
        assert peer.url == "https://github.com/lab-a/experiments.git"
        assert peer.name == "experiments"
        assert peer.directions == []
        assert len(peer.id) == 12

    def test_name_from_url_strips_git(self):
        peer = FederationPeer(url="https://github.com/org/my-repo.git")
        assert peer.name == "my-repo"

    def test_name_from_url_no_git_suffix(self):
        peer = FederationPeer(url="https://github.com/org/my-repo")
        assert peer.name == "my-repo"

    def test_name_from_url_trailing_slash(self):
        peer = FederationPeer(url="https://github.com/org/my-repo/")
        assert peer.name == "my-repo"

    def test_custom_name(self):
        peer = FederationPeer(url="https://example.com/repo.git", name="custom")
        assert peer.name == "custom"

    def test_directions(self):
        peer = FederationPeer(
            url="https://example.com/repo.git",
            directions=["attention", "memory"],
        )
        assert peer.directions == ["attention", "memory"]

    def test_id_is_deterministic(self):
        url = "https://github.com/lab-a/experiments.git"
        p1 = FederationPeer(url=url)
        p2 = FederationPeer(url=url)
        assert p1.id == p2.id

    def test_id_matches_manual_hash(self):
        url = "https://github.com/lab-a/experiments.git"
        expected = hashlib.sha256(url.encode()).hexdigest()[:12]
        peer = FederationPeer(url=url)
        assert peer.id == expected

    def test_different_urls_produce_different_ids(self):
        p1 = FederationPeer(url="https://example.com/repo-a.git")
        p2 = FederationPeer(url="https://example.com/repo-b.git")
        assert p1.id != p2.id

    def test_to_dict(self):
        peer = FederationPeer(
            url="https://example.com/repo.git",
            name="repo",
            directions=["attention"],
        )
        d = peer.to_dict()
        assert d["url"] == "https://example.com/repo.git"
        assert d["name"] == "repo"
        assert d["directions"] == ["attention"]

    def test_to_dict_no_directions(self):
        peer = FederationPeer(url="https://example.com/repo.git")
        d = peer.to_dict()
        assert "directions" not in d

    def test_from_dict(self):
        data = {
            "url": "https://example.com/repo.git",
            "name": "repo",
            "directions": ["memory"],
        }
        peer = FederationPeer.from_dict(data)
        assert peer.url == data["url"]
        assert peer.name == data["name"]
        assert peer.directions == ["memory"]

    def test_from_dict_minimal(self):
        data = {"url": "https://example.com/repo.git"}
        peer = FederationPeer.from_dict(data)
        assert peer.name == "repo"
        assert peer.directions == []

    def test_roundtrip_dict(self):
        peer = FederationPeer(
            url="https://example.com/repo.git",
            name="repo",
            directions=["a", "b"],
        )
        peer2 = FederationPeer.from_dict(peer.to_dict())
        assert peer2.url == peer.url
        assert peer2.name == peer.name
        assert peer2.directions == peer.directions


# ---------------------------------------------------------------------------
# FederationRegistry — peer management
# ---------------------------------------------------------------------------


class TestFederationRegistryPeers:
    @pytest.fixture
    def registry(self, tmp_path: Path) -> FederationRegistry:
        spore_dir = tmp_path / ".spore"
        spore_dir.mkdir()
        return FederationRegistry(spore_dir)

    def test_empty_peers(self, registry: FederationRegistry):
        assert registry.peers == []
        assert registry.list_peers() == []

    def test_add_peer(self, registry: FederationRegistry):
        peer = registry.add_peer("https://example.com/repo.git")
        assert peer.name == "repo"
        assert len(registry.peers) == 1

    def test_add_peer_with_options(self, registry: FederationRegistry):
        peer = registry.add_peer(
            "https://example.com/repo.git",
            name="custom",
            directions=["attention"],
        )
        assert peer.name == "custom"
        assert peer.directions == ["attention"]

    def test_add_duplicate_returns_existing(self, registry: FederationRegistry):
        p1 = registry.add_peer("https://example.com/repo.git")
        p2 = registry.add_peer("https://example.com/repo.git")
        assert p1.id == p2.id
        assert len(registry.peers) == 1

    def test_add_multiple_peers(self, registry: FederationRegistry):
        registry.add_peer("https://example.com/repo-a.git")
        registry.add_peer("https://example.com/repo-b.git")
        assert len(registry.peers) == 2

    def test_remove_peer(self, registry: FederationRegistry):
        registry.add_peer("https://example.com/repo.git")
        assert registry.remove_peer("https://example.com/repo.git") is True
        assert len(registry.peers) == 0

    def test_remove_nonexistent_peer(self, registry: FederationRegistry):
        assert registry.remove_peer("https://example.com/nope.git") is False

    def test_list_peers(self, registry: FederationRegistry):
        registry.add_peer("https://example.com/a.git")
        registry.add_peer("https://example.com/b.git")
        peers = registry.list_peers()
        assert len(peers) == 2
        urls = {p.url for p in peers}
        assert "https://example.com/a.git" in urls
        assert "https://example.com/b.git" in urls

    def test_persistence(self, tmp_path: Path):
        """Peers survive registry re-creation from disk."""
        spore_dir = tmp_path / ".spore"
        spore_dir.mkdir()

        reg1 = FederationRegistry(spore_dir)
        reg1.add_peer("https://example.com/repo.git", name="persisted")

        reg2 = FederationRegistry(spore_dir)
        assert len(reg2.peers) == 1
        assert reg2.peers[0].name == "persisted"

    def test_federation_yaml_format(self, registry: FederationRegistry):
        registry.add_peer("https://example.com/repo.git")
        data = yaml.safe_load(registry.federation_path.read_text())
        assert data["version"] == "1"
        assert len(data["peers"]) == 1
        assert data["peers"][0]["url"] == "https://example.com/repo.git"


# ---------------------------------------------------------------------------
# FederationRegistry — discover from peer (filesystem-level)
# ---------------------------------------------------------------------------


class TestFederationRegistryDiscover:
    @pytest.fixture
    def registry_with_peer_findings(self, tmp_path: Path):
        """Set up a registry with a fake peer cache containing findings."""
        spore_dir = tmp_path / ".spore"
        spore_dir.mkdir()
        registry = FederationRegistry(spore_dir)

        peer = registry.add_peer("https://example.com/lab-x.git")

        # Create fake cached peer with .spore/findings/
        cache_path = registry.cache_dir / peer.id
        peer_findings_dir = cache_path / ".spore" / "findings"
        peer_findings_dir.mkdir(parents=True)

        # Write a finding YAML
        finding = Finding(
            experiment_id="exp-remote",
            agent_id="remote-agent",
            direction="attention-variants",
            claim="Remote finding about attention",
            significance=0.8,
        )
        (peer_findings_dir / f"{finding.id}.yaml").write_text(finding.to_yaml())

        # Write a second finding in a different direction
        finding2 = Finding(
            experiment_id="exp-remote2",
            agent_id="remote-agent",
            direction="memory-efficiency",
            claim="Remote finding about memory",
            significance=0.6,
        )
        (peer_findings_dir / f"{finding2.id}.yaml").write_text(finding2.to_yaml())

        return registry, peer, [finding, finding2]

    def test_discover_from_peer_all(self, registry_with_peer_findings):
        from spore.index import SporeIndex

        registry, peer, expected_findings = registry_with_peer_findings
        index = SporeIndex(registry.spore_dir / "index.db")

        findings = registry.discover_from_peer(peer, index)
        assert len(findings) == 2

    def test_discover_from_peer_with_direction_filter(self, registry_with_peer_findings):
        from spore.index import SporeIndex

        registry, peer, _ = registry_with_peer_findings
        index = SporeIndex(registry.spore_dir / "index.db")

        findings = registry.discover_from_peer(peer, index, direction="attention")
        assert len(findings) == 1
        assert "attention" in findings[0].direction.lower()

    def test_discover_from_peer_no_findings_dir(self, tmp_path: Path):
        from spore.index import SporeIndex

        spore_dir = tmp_path / ".spore"
        spore_dir.mkdir()
        registry = FederationRegistry(spore_dir)
        peer = registry.add_peer("https://example.com/empty.git")

        # Create cache dir but no .spore/findings
        (registry.cache_dir / peer.id).mkdir(parents=True)

        index = SporeIndex(spore_dir / "index.db")
        findings = registry.discover_from_peer(peer, index)
        assert findings == []

    def test_discover_from_peer_indexes_findings(self, registry_with_peer_findings):
        from spore.index import SporeIndex

        registry, peer, _ = registry_with_peer_findings
        index = SporeIndex(registry.spore_dir / "index.db")

        findings = registry.discover_from_peer(peer, index)
        # Verify findings are in the index
        results = index.search(limit=10)
        assert len(results) == len(findings)

    def test_discover_from_peer_sets_federation_source(self, registry_with_peer_findings):
        from spore.index import SporeIndex

        registry, peer, _ = registry_with_peer_findings
        index = SporeIndex(registry.spore_dir / "index.db")

        registry.discover_from_peer(peer, index)
        results = index.search(limit=10)
        for r in results:
            assert r["source_branch"].startswith("federation:")


# ---------------------------------------------------------------------------
# FederationRegistry — integration with SporeRepo
# ---------------------------------------------------------------------------


class TestFederationRepoIntegration:
    def test_repo_has_federation(self, spore_repo):
        assert spore_repo.federation is not None
        assert isinstance(spore_repo.federation, FederationRegistry)

    def test_add_peer_via_repo(self, spore_repo):
        result = spore_repo.add_peer("https://example.com/peer.git")
        assert result["name"] == "peer"
        assert result["url"] == "https://example.com/peer.git"

    def test_list_peers_via_repo(self, spore_repo):
        spore_repo.add_peer("https://example.com/peer.git")
        peers = spore_repo.list_peers()
        assert len(peers) == 1
        assert peers[0]["url"] == "https://example.com/peer.git"

    def test_remove_peer_via_repo(self, spore_repo):
        spore_repo.add_peer("https://example.com/peer.git")
        assert spore_repo.remove_peer("https://example.com/peer.git") is True
        assert len(spore_repo.list_peers()) == 0

    def test_add_peer_requires_init(self, tmp_git_repo):
        from spore.repo import SporeError, SporeRepo

        repo = SporeRepo(tmp_git_repo)
        with pytest.raises(SporeError, match="not initialized"):
            repo.add_peer("https://example.com/peer.git")
