"""Event system for Spore — watch for new findings.

Provides a cross-platform file-polling watcher that triggers callbacks
when new findings appear in a Spore repository. Enables agents to react
to discoveries instead of manually polling.

Usage:
    from spore.watch import SporeWatcher

    def on_new_finding(finding):
        print(f"New finding: {finding.claim}")

    watcher = SporeWatcher(repo)
    watcher.on_finding(on_new_finding, direction="attention")
    watcher.start()  # Runs in background thread
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

if TYPE_CHECKING:
    from spore.repo import SporeRepo

from spore.models import Finding

logger = logging.getLogger("spore")


class SporeWatcher:
    """Watches a Spore repository for new findings.

    Uses polling (not filesystem events) for cross-platform compatibility.
    The watcher runs in a background daemon thread and triggers registered
    callbacks when new findings appear.
    """

    def __init__(self, repo: SporeRepo, interval: float = 5.0) -> None:
        """Initialize the watcher.

        Args:
            repo: The SporeRepo to watch.
            interval: Polling interval in seconds (default: 5.0).
        """
        self.repo = repo
        self.interval = interval
        self._callbacks: list[dict[str, Any]] = []
        self._known_ids: set[str] = set()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Initialize known findings
        self._scan_existing()

    def _scan_existing(self) -> None:
        """Record all currently existing finding IDs."""
        findings_dir = self.repo.spore_dir / "findings"
        if findings_dir.exists():
            for f in findings_dir.glob("*.yaml"):
                # Extract ID from filename (finding files are named <id>.yaml)
                self._known_ids.add(f.stem)

    def on_finding(
        self,
        callback: Callable[[Finding], None],
        direction: str | None = None,
        min_significance: float | None = None,
    ) -> None:
        """Register a callback for new findings.

        Args:
            callback: Function called with the new Finding object.
            direction: Only trigger for findings in this direction (substring match).
            min_significance: Only trigger for findings above this significance.
        """
        self._callbacks.append(
            {
                "fn": callback,
                "direction": direction,
                "min_significance": min_significance,
            }
        )

    def _check_for_new(self) -> list[Finding]:
        """Check for new findings since last poll."""
        new_findings: list[Finding] = []
        findings_dir = self.repo.spore_dir / "findings"

        if not findings_dir.exists():
            return new_findings

        for f in findings_dir.glob("*.yaml"):
            finding_id = f.stem
            if finding_id not in self._known_ids:
                try:
                    finding = Finding.from_yaml(f.read_text())
                    self._known_ids.add(finding_id)
                    new_findings.append(finding)
                except Exception as e:
                    logger.debug("Failed to parse new finding %s: %s", finding_id, e)

        return new_findings

    def _dispatch(self, finding: Finding) -> None:
        """Dispatch a finding to all matching callbacks."""
        for cb in self._callbacks:
            # Check direction filter
            if cb["direction"] and cb["direction"].lower() not in finding.direction.lower():
                continue

            # Check significance filter
            if cb["min_significance"] is not None and finding.significance < cb["min_significance"]:
                continue

            try:
                cb["fn"](finding)
            except Exception as e:
                logger.warning("Callback error for finding %s: %s", finding.id, e)

    def _poll_loop(self) -> None:
        """Main polling loop (runs in background thread)."""
        while not self._stop_event.is_set():
            try:
                new_findings = self._check_for_new()
                for finding in new_findings:
                    self._dispatch(finding)
            except Exception as e:
                logger.debug("Watcher poll error: %s", e)

            self._stop_event.wait(self.interval)

    def start(self) -> None:
        """Start watching in a background daemon thread."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.debug("Watcher started (interval=%.1fs)", self.interval)

    def stop(self) -> None:
        """Stop the watcher."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 1)
            self._thread = None
        logger.debug("Watcher stopped")

    def poll_once(self) -> list[Finding]:
        """Run a single poll cycle (useful for testing or one-shot checks)."""
        new_findings = self._check_for_new()
        for finding in new_findings:
            self._dispatch(finding)
        return new_findings

    @property
    def is_running(self) -> bool:
        """Whether the watcher is currently running."""
        return self._thread is not None and self._thread.is_alive()
