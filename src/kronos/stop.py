"""Shared stop primitive (SPEC_BRIEF30 §4.1): a filesystem-backed, cross-process stop record.

`<engagement_dir>/stop.jsonl` is append-only (events.py idiom: open(path, "a")). The FIRST
line is authoritative (source, reason); later lines are an audit trail and never override it.
`request_stop` is the only function that sets stop. No locks and no atomic-rename.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

StopSource = Literal["operator", "watchdog", "budget", "deadline"]
STOP_SOURCES: frozenset[str] = frozenset({"operator", "watchdog", "budget", "deadline"})

_STOP_FILENAME = "stop.jsonl"


class Stopped(Exception):
    """Raised by `raise_if_stopped` when a stop has been requested."""

    def __init__(self, source: str, reason: str):
        self.source = source
        self.reason = reason
        super().__init__(f"stopped by {source}: {reason}")


@dataclass(frozen=True)
class StopState:
    source: str
    reason: str


def _path(engagement_dir) -> Path:
    return Path(engagement_dir) / _STOP_FILENAME


def request_stop(
    engagement_dir,
    source: str,
    reason: str,
    *,
    now: Callable[[], datetime] | None = None,
) -> None:
    """Append one stop line. Idempotent in effect: the first line wins."""
    if source not in STOP_SOURCES:
        raise ValueError(f"unknown stop source {source!r}; must be one of {sorted(STOP_SOURCES)}")
    ts = (now or (lambda: datetime.now(timezone.utc)))()
    line = json.dumps({"source": source, "reason": reason, "timestamp": ts.isoformat()}, sort_keys=True)
    with open(_path(engagement_dir), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def is_stopped(engagement_dir) -> StopState | None:
    """The first line's (source, reason) if the record is present and non-empty, else None."""
    try:
        with open(_path(engagement_dir), "r", encoding="utf-8") as f:
            first = f.readline()
    except FileNotFoundError:
        return None
    if not first.strip():
        return None
    try:
        rec = json.loads(first)
    except json.JSONDecodeError:
        return None  # torn first line from a concurrent writer: not yet a complete record
    return StopState(source=rec["source"], reason=rec["reason"])


def raise_if_stopped(engagement_dir) -> None:
    state = is_stopped(engagement_dir)
    if state is not None:
        raise Stopped(state.source, state.reason)
