"""Independent read-only watchdog (SPEC_BRIEF30 §4.4).

Reads the engagement's `events.jsonl` (existing kinds only) and the signed `WatchdogPolicy`
from a verified in-force `VerifiedManifest` (`.autonomy.watchdog`). Writes no graph, evidence
or event; its only state effect is a `stop.jsonl` line via `request_stop(source="watchdog")`.

Policy None or `may_auto_stop` False: alert only, never stop. `may_auto_stop` True: when the
trigger condition first holds, a `confirm_window_seconds` grace starts; at window end the
condition is re-checked and a stop is requested only if it still persists (D5).

The brief does not name the trigger condition, so the caller injects it as a predicate over
the parsed events list. Time comes only from the injected `clock`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from kronos.manifest import VerifiedManifest, WatchdogPolicy
from kronos.stop import is_stopped, request_stop

logger = logging.getLogger(__name__)

_EVENTS_FILENAME = "events.jsonl"


class Watchdog:
    def __init__(
        self,
        verified: VerifiedManifest,
        engagement_dir,
        condition: Callable[[list[dict]], bool],
        clock: Callable[[], float],
    ) -> None:
        self._policy: WatchdogPolicy | None = verified.autonomy.watchdog if verified.autonomy else None
        self._dir = Path(engagement_dir)
        self._condition = condition
        self._clock = clock
        self._held_since: float | None = None

    def _events(self) -> list[dict]:
        try:
            with open(self._dir / _EVENTS_FILENAME, "r", encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError:
            return []

    def poll(self) -> str:
        """One observation. Returns idle | alert | grace | stood_down | stopped."""
        if is_stopped(self._dir) is not None:
            self._held_since = None
            return "stopped"  # already stopped (first-wins); never override
        if not self._condition(self._events()):
            if self._held_since is None:
                return "idle"
            self._held_since = None
            return "stood_down"
        if self._policy is None or not self._policy.may_auto_stop:
            logger.warning("watchdog: trigger condition holds; alert only (auto-stop not permitted)")
            return "alert"
        now = self._clock()
        if self._held_since is None:
            self._held_since = now
            return "grace"
        if now - self._held_since >= self._policy.confirm_window_seconds:
            request_stop(self._dir, "watchdog", "trigger condition persisted past confirm window")
            return "stopped"
        return "grace"
