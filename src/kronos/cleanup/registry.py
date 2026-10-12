"""The teardown chokepoint (SPEC_BRIEF6 §2): every ephemeral artifact an
engagement creates — Docker containers/networks/volumes, temp files,
temp credential files, spawned processes — is registered here, and
`CleanupRegistry.teardown_all()` is the ONE place that disposes of
them. No per-caller ad-hoc `finally` blocks scattered around the
codebase; the orchestrator registers as it creates, and teardown is
guaranteed on exit.

Deliberately has nothing to do with `kronos.budget` (guardrail 3 /
FORK-F's DEFAULT): nothing in this module imports it, calls
`BudgetLedger.charge`, or can raise `BudgetExceeded` — teardown must
run even when an engagement's budget is fully exhausted, so it cannot
depend on spare budget to finish. See `tests/test_cleanup.py`'s
guardrail tests for the mechanical proof, not just the convention.

Each registered teardown callable is a zero-arg `Callable[[], str |
None]`: it performs the disposal and returns `"already_gone"` if the
artifact had already been removed by something else (not a failure),
or `None` on an ordinary successful disposal. Raising is the only way
to report a real failure — `teardown_all()` catches it, records it on
the `TeardownReport`, and keeps going (guardrail 4: best-effort, never
silently swallowed, one failure never blocks the rest).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Union

TEARDOWN_REPORT_FILENAME = "teardown_report.json"

Outcome = str  # "done" | "already_gone" | "failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TeardownItem:
    kind: str
    detail: str
    outcome: Outcome
    error: Optional[str]
    timestamp: str


@dataclass(frozen=True)
class TeardownReport:
    """The audit-trail artifact (SPEC_BRIEF6 §2/§4 test 7-ish parallel
    to the budget ledger snapshot): what was torn down, in what order,
    and what — if anything — couldn't be, so an operator can finish by
    hand (guardrail 4)."""

    items: tuple[TeardownItem, ...]

    @property
    def all_ok(self) -> bool:
        return all(item.outcome != "failed" for item in self.items)

    @property
    def failures(self) -> tuple[TeardownItem, ...]:
        return tuple(item for item in self.items if item.outcome == "failed")

    def to_dict(self) -> dict:
        return {
            "all_ok": self.all_ok,
            "items": [
                {
                    "kind": item.kind,
                    "detail": item.detail,
                    "outcome": item.outcome,
                    "error": item.error,
                    "timestamp": item.timestamp,
                }
                for item in self.items
            ],
        }


@dataclass
class _RegisteredArtifact:
    kind: str
    handle: object
    teardown: Callable[[], Optional[str]]
    detail: str


@dataclass
class CleanupRegistry:
    """Append-only registration; `teardown_all()` disposes everything in
    **LIFO** order (reverse of registration — e.g. containers before
    the network they attach to, files before their parent dir)."""

    _artifacts: list[_RegisteredArtifact] = field(default_factory=list, init=False, repr=False)
    _torn_down: set[int] = field(default_factory=set, init=False, repr=False)
    _last_report: Optional[TeardownReport] = field(default=None, init=False, repr=False)

    def register(
        self,
        kind: str,
        handle: object,
        teardown: Callable[[], Optional[str]],
        *,
        detail: str = "",
    ) -> None:
        self._artifacts.append(_RegisteredArtifact(kind=kind, handle=handle, teardown=teardown, detail=detail))

    def teardown_all(self) -> TeardownReport:
        """Dispose every registered artifact in LIFO order. Idempotent:
        an artifact already torn down by a previous call is reported
        `already_gone` without invoking its teardown callable again
        (guardrail 4 / §4 test 4); a previously FAILED item is retried,
        since its disposal genuinely never happened."""
        items: list[TeardownItem] = []
        for index in reversed(range(len(self._artifacts))):
            artifact = self._artifacts[index]
            if index in self._torn_down:
                items.append(
                    TeardownItem(kind=artifact.kind, detail=artifact.detail, outcome="already_gone", error=None, timestamp=_now())
                )
                continue
            try:
                already_gone = artifact.teardown()
            except Exception as exc:  # noqa: BLE001 — best-effort-but-reported, never fatal (guardrail 4)
                items.append(
                    TeardownItem(kind=artifact.kind, detail=artifact.detail, outcome="failed", error=str(exc), timestamp=_now())
                )
            else:
                self._torn_down.add(index)
                outcome = "already_gone" if already_gone == "already_gone" else "done"
                items.append(
                    TeardownItem(kind=artifact.kind, detail=artifact.detail, outcome=outcome, error=None, timestamp=_now())
                )
        report = TeardownReport(items=tuple(items))
        self._last_report = report
        return report

    @property
    def last_report(self) -> Optional[TeardownReport]:
        return self._last_report

    def __enter__(self) -> "CleanupRegistry":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        # Crash-safety mechanism (FORK-G's DEFAULT): teardown runs here
        # whether the body returned normally OR raised — including a
        # `BudgetExceeded` propagating straight through (guardrail 3).
        # Never swallow the body's own exception.
        self.teardown_all()
        return False


def write_teardown_report(engagement_dir: Union[str, Path], report: TeardownReport) -> Path:
    """Writes the report to the engagement dir, alongside the budget
    ledger snapshot (SPEC_BRIEF6 §2 integration step)."""
    path = Path(engagement_dir) / TEARDOWN_REPORT_FILENAME
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return path
