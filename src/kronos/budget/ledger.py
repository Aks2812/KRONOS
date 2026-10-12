"""The chokepoint (SPEC_BRIEF5 §1 guardrail 5 / §2): every cost-incurring
action in the whole codebase spends through `BudgetLedger.charge`, the
one API. No scattered per-caller counting, no second place that decides
whether a run may keep going.

Fail-closed, never fail-open (guardrail 3/6): `charge` checks the
ceiling BEFORE recording anything. A charge that would cross it raises
`BudgetExceeded` and leaves the ledger exactly as it was — the action it
would have paid for never happens, and nothing about this call is
silently downgraded to "continue anyway." The charge-before-the-action
calling convention (every caller charges, THEN performs the action) is
what makes FORK-E's DEFAULT (let the current atomic action finish, then
stop before the next) fall out for free: an action whose own charge
raises was never started, and every action KRONOS performs today runs
to completion synchronously before the next one's charge is even
attempted — there is no "abort a half-done action" case to build,
because charge-before-start never creates one.

Wall-clock is the one dimension that isn't a simple running sum: it's
real elapsed time since the ledger was created, so `charge` re-measures
it (via `elapsed_seconds`, itself driven by an injectable clock — real
`time.monotonic` by default, a deterministic fake in tests) and checks
it against `limits.wall_clock_seconds` on every single call, not just
when a caller happens to charge the `wall_clock_seconds` dimension
itself. `check_wall_clock()` exposes that same assertion standalone, for
an orchestrator to call between pipeline phases that charge nothing (so
a long gap — e.g. standing up a Docker lab — still can't blow through
the overall ceiling unnoticed until the next charge).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Union

from kronos.budget.limits import BUDGET_DIMENSIONS, BudgetLimits

LEDGER_FILENAME = "budget_ledger.json"


class BudgetExceeded(Exception):
    """Raised by `BudgetLedger.charge`/`check_wall_clock` the instant a
    charge would cross its dimension's ceiling. There is no catch site
    inside `kronos.validate` or `kronos.budget` itself that swallows
    this — every raise is meant to propagate to whichever orchestrator
    owns wind-down (write the ledger snapshot, emit the partial report,
    exit non-crash); see `cybergym/kronos_validation_run.py`."""

    def __init__(self, dimension: str, ceiling: float, attempted: float):
        self.dimension = dimension
        self.ceiling = ceiling
        self.attempted = attempted
        super().__init__(
            f"budget exceeded: {dimension} would reach {attempted} > ceiling {ceiling}"
        )


@dataclass(frozen=True)
class BudgetLedgerEntry:
    dimension: str
    amount: float
    running_total: float
    actor: str
    detail: str
    timestamp: str


@dataclass(frozen=True)
class BudgetSnapshot:
    """The audit-trail artifact (SPEC_BRIEF5 §2/§4 test 7): every
    dimension's ceiling next to what's actually been spent, the
    append-only entry log, where the limits came from (`budget.yaml` or
    the built-in default, and why), and — when the run stopped early —
    which dimension did it."""

    limits: BudgetLimits
    totals: dict[str, float]
    entries: tuple[BudgetLedgerEntry, ...]
    config_source: str
    config_reason: str | None
    stopped_reason: str | None

    def to_dict(self) -> dict:
        return {
            "limits": asdict(self.limits),
            "totals": self.totals,
            "entries": [asdict(e) for e in self.entries],
            "config_source": self.config_source,
            "config_reason": self.config_reason,
            "stopped_reason": self.stopped_reason,
        }


@dataclass
class BudgetLedger:
    limits: BudgetLimits
    config_source: str = "default"
    config_reason: str | None = None
    clock: Callable[[], float] = time.monotonic

    _start: float = field(init=False, repr=False)
    _totals: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _entries: list[BudgetLedgerEntry] = field(default_factory=list, init=False, repr=False)
    _stopped_reason: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._start = self.clock()

    @property
    def elapsed_seconds(self) -> float:
        return self.clock() - self._start

    def _assert_wall_clock_not_exceeded(self) -> None:
        ceiling = self.limits.wall_clock_seconds
        if ceiling is None:
            return
        elapsed = self.elapsed_seconds
        if elapsed > ceiling:
            self._stopped_reason = "wall_clock_seconds"
            raise BudgetExceeded("wall_clock_seconds", ceiling, elapsed)

    def check_wall_clock(self) -> None:
        """Explicit phase-boundary check (SPEC_BRIEF5 §2: "checked at
        each charge and between phases") — the same assertion `charge`
        runs before every discrete charge, exposed standalone so a long,
        charge-free phase still enforces the overall ceiling."""
        self._assert_wall_clock_not_exceeded()

    def charge(self, dimension: str, amount: float = 1, *, actor: str, detail: str = "") -> None:
        if dimension not in BUDGET_DIMENSIONS:
            raise ValueError(f"unknown budget dimension {dimension!r}; must be one of {BUDGET_DIMENSIONS}")

        # Every charge re-checks the overall wall-clock ceiling first,
        # regardless of which dimension it's for — see module docstring.
        self._assert_wall_clock_not_exceeded()

        current = self._totals.get(dimension, 0.0)
        new_total = current + amount
        ceiling = getattr(self.limits, dimension)
        if ceiling is not None and new_total > ceiling:
            self._stopped_reason = dimension
            raise BudgetExceeded(dimension, ceiling, new_total)

        self._totals[dimension] = new_total
        self._entries.append(
            BudgetLedgerEntry(
                dimension=dimension,
                amount=amount,
                running_total=new_total,
                actor=actor,
                detail=detail,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )

    def snapshot(self) -> BudgetSnapshot:
        totals = dict(self._totals)
        # Wall-clock has no discrete "charge" of its own in the common
        # case (it's asserted as a side effect of every other charge),
        # so the snapshot always reports the CURRENT elapsed time for it
        # rather than whatever stale value (if any) happened to be
        # recorded on the last charge — the audit trail should always be
        # able to answer "how long has this run been going," live.
        totals["wall_clock_seconds"] = self.elapsed_seconds
        return BudgetSnapshot(
            limits=self.limits,
            totals=totals,
            entries=tuple(self._entries),
            config_source=self.config_source,
            config_reason=self.config_reason,
            stopped_reason=self._stopped_reason,
        )


def stopped_early_marker(snapshot: BudgetSnapshot) -> str | None:
    """The one canonical "stopped early" string (SPEC_BRIEF5 §2/§4 test
    7), so every orchestrator reports an exhausted budget identically
    instead of each one inventing its own wording. `None` when the run
    wasn't stopped by the budget."""
    if snapshot.stopped_reason is None:
        return None
    return f"stopped early: budget {snapshot.stopped_reason} exhausted"


def write_ledger_snapshot(engagement_dir: Union[str, Path], ledger: BudgetLedger) -> Path:
    """Writes the ledger's current snapshot to the engagement dir
    (SPEC_BRIEF5 §2 wind-down step / §4 test 7: "the ledger snapshot is
    written to the engagement dir ... is queryable/parseable"). Safe to
    call more than once (e.g. mid-run and again at wind-down) — each
    call overwrites with the latest state; the append-only guarantee is
    about the in-memory entry log `charge` builds, not about this file
    never being rewritten."""
    path = Path(engagement_dir) / LEDGER_FILENAME
    path.write_text(json.dumps(ledger.snapshot().to_dict(), indent=2, sort_keys=True))
    return path
