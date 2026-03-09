"""Unit tests for the event/watch system (src/spore/watch.py)."""

from __future__ import annotations

import time

from spore.models import Finding
from spore.watch import SporeWatcher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(direction: str = "attention", significance: float = 0.5) -> Finding:
    return Finding(
        experiment_id="exp-test",
        agent_id="test-agent",
        direction=direction,
        claim=f"Test finding ({direction}, sig={significance})",
        significance=significance,
    )


def _write_finding(spore_repo, finding: Finding) -> None:
    """Write a finding YAML directly without going through publish (avoids side effects)."""
    findings_dir = spore_repo.spore_dir / "findings"
    findings_dir.mkdir(exist_ok=True)
    (findings_dir / f"{finding.id}.yaml").write_text(finding.to_yaml())


# ---------------------------------------------------------------------------
# SporeWatcher — initialization
# ---------------------------------------------------------------------------


class TestWatcherInit:
    def test_creates_watcher(self, spore_repo):
        watcher = SporeWatcher(spore_repo)
        assert watcher.repo is spore_repo
        assert watcher.interval == 5.0
        assert not watcher.is_running

    def test_custom_interval(self, spore_repo):
        watcher = SporeWatcher(spore_repo, interval=1.0)
        assert watcher.interval == 1.0

    def test_scans_existing_findings(self, spore_repo_with_finding):
        watcher = SporeWatcher(spore_repo_with_finding)
        # The existing finding should already be in _known_ids
        assert len(watcher._known_ids) >= 1


# ---------------------------------------------------------------------------
# SporeWatcher — callback registration
# ---------------------------------------------------------------------------


class TestWatcherCallbacks:
    def test_register_callback(self, spore_repo):
        watcher = SporeWatcher(spore_repo)
        watcher.on_finding(lambda f: None)
        assert len(watcher._callbacks) == 1

    def test_register_with_direction(self, spore_repo):
        watcher = SporeWatcher(spore_repo)
        watcher.on_finding(lambda f: None, direction="attention")
        assert watcher._callbacks[0]["direction"] == "attention"

    def test_register_with_min_significance(self, spore_repo):
        watcher = SporeWatcher(spore_repo)
        watcher.on_finding(lambda f: None, min_significance=0.7)
        assert watcher._callbacks[0]["min_significance"] == 0.7

    def test_multiple_callbacks(self, spore_repo):
        watcher = SporeWatcher(spore_repo)
        watcher.on_finding(lambda f: None)
        watcher.on_finding(lambda f: None, direction="memory")
        assert len(watcher._callbacks) == 2


# ---------------------------------------------------------------------------
# SporeWatcher — poll_once
# ---------------------------------------------------------------------------


class TestWatcherPollOnce:
    def test_no_new_findings(self, spore_repo):
        watcher = SporeWatcher(spore_repo)
        results = watcher.poll_once()
        assert results == []

    def test_detects_new_finding(self, spore_repo):
        watcher = SporeWatcher(spore_repo)
        found = []
        watcher.on_finding(lambda f: found.append(f))

        # Write a finding after watcher init
        finding = _make_finding()
        _write_finding(spore_repo, finding)

        results = watcher.poll_once()
        assert len(results) == 1
        assert results[0].id == finding.id
        assert len(found) == 1

    def test_same_finding_not_dispatched_twice(self, spore_repo):
        watcher = SporeWatcher(spore_repo)
        found = []
        watcher.on_finding(lambda f: found.append(f))

        finding = _make_finding()
        _write_finding(spore_repo, finding)

        watcher.poll_once()
        watcher.poll_once()  # Second poll should not re-trigger
        assert len(found) == 1

    def test_direction_filter(self, spore_repo):
        watcher = SporeWatcher(spore_repo)
        found = []
        watcher.on_finding(lambda f: found.append(f), direction="attention")

        # Write two findings
        f1 = _make_finding(direction="attention-variants")
        f2 = _make_finding(direction="memory-efficiency")
        _write_finding(spore_repo, f1)
        _write_finding(spore_repo, f2)

        watcher.poll_once()
        assert len(found) == 1
        assert "attention" in found[0].direction.lower()

    def test_significance_filter(self, spore_repo):
        watcher = SporeWatcher(spore_repo)
        found = []
        watcher.on_finding(lambda f: found.append(f), min_significance=0.7)

        f_low = _make_finding(significance=0.3)
        f_high = _make_finding(significance=0.9)
        _write_finding(spore_repo, f_low)
        _write_finding(spore_repo, f_high)

        watcher.poll_once()
        assert len(found) == 1
        assert found[0].significance >= 0.7

    def test_callback_error_does_not_crash(self, spore_repo):
        """A failing callback should not prevent other callbacks from running."""
        watcher = SporeWatcher(spore_repo)
        good_found = []

        def bad_cb(f):
            raise RuntimeError("boom")

        watcher.on_finding(bad_cb)
        watcher.on_finding(lambda f: good_found.append(f))

        finding = _make_finding()
        _write_finding(spore_repo, finding)

        # Should not raise
        results = watcher.poll_once()
        assert len(results) == 1
        assert len(good_found) == 1


# ---------------------------------------------------------------------------
# SporeWatcher — start/stop
# ---------------------------------------------------------------------------


class TestWatcherStartStop:
    def test_start_stop(self, spore_repo):
        watcher = SporeWatcher(spore_repo, interval=0.1)
        watcher.start()
        assert watcher.is_running
        watcher.stop()
        assert not watcher.is_running

    def test_double_start_is_noop(self, spore_repo):
        watcher = SporeWatcher(spore_repo, interval=0.1)
        watcher.start()
        thread1 = watcher._thread
        watcher.start()  # Should not create a new thread
        assert watcher._thread is thread1
        watcher.stop()

    def test_background_detection(self, spore_repo):
        """Watcher detects new findings in background thread."""
        watcher = SporeWatcher(spore_repo, interval=0.1)
        found = []
        watcher.on_finding(lambda f: found.append(f))
        watcher.start()

        finding = _make_finding()
        _write_finding(spore_repo, finding)

        # Give the watcher time to poll
        time.sleep(0.5)
        watcher.stop()

        assert len(found) >= 1
        assert found[0].id == finding.id


# ---------------------------------------------------------------------------
# SporeWatcher — integration with SporeRepo.watch()
# ---------------------------------------------------------------------------


class TestRepoWatchIntegration:
    def test_watch_convenience_method(self, spore_repo):
        found = []
        watcher = spore_repo.watch(
            callback=lambda f: found.append(f),
            interval=0.1,
        )
        assert watcher.is_running

        finding = _make_finding()
        _write_finding(spore_repo, finding)
        time.sleep(0.5)

        watcher.stop()
        assert len(found) >= 1

    def test_watch_with_filters(self, spore_repo):
        found = []
        watcher = spore_repo.watch(
            callback=lambda f: found.append(f),
            direction="attention",
            min_significance=0.5,
            interval=0.1,
        )

        f1 = _make_finding(direction="attention-variants", significance=0.8)
        f2 = _make_finding(direction="memory", significance=0.9)
        _write_finding(spore_repo, f1)
        _write_finding(spore_repo, f2)
        time.sleep(0.5)

        watcher.stop()
        assert len(found) == 1
        assert "attention" in found[0].direction.lower()
