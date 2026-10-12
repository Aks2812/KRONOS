"""Load per-engagement `BudgetLimits` from `budget.yaml` (SPEC_BRIEF5
FORK-D DEFAULT: a separate file, code-enforced, never part of the signed
Ed25519 manifest — scope authorization and operational budget are
different concerns, and coupling them would force a re-sign for a
token-limit tweak).

The one rule every branch of `load_budget_limits` upholds (guardrail 3):
a missing, empty, unparseable, or malformed `budget.yaml` NEVER produces
an unlimited budget — it falls back to `DEFAULT_BUDGET_LIMITS` and says
so in the returned `BudgetConfigResult.reason`, for the ledger/report to
record (SPEC_BRIEF5 §4 test 5). A dimension a *valid* `budget.yaml`
simply omits is filled from the same default, one field at a time — only
an explicit `null` in the file produces a genuinely unlimited dimension.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Union

import yaml

from kronos.budget.limits import BUDGET_DIMENSIONS, DEFAULT_BUDGET_LIMITS, BudgetLimits

BUDGET_FILENAME = "budget.yaml"


@dataclass(frozen=True)
class BudgetConfigResult:
    limits: BudgetLimits
    source: str  # "file" | "default"
    reason: str | None  # why the default was used; None when source == "file"


def _fallback(reason: str) -> BudgetConfigResult:
    return BudgetConfigResult(limits=DEFAULT_BUDGET_LIMITS, source="default", reason=reason)


def load_budget_limits(engagement_dir: Union[str, Path]) -> BudgetConfigResult:
    path = Path(engagement_dir) / BUDGET_FILENAME
    if not path.exists():
        return _fallback(f"{BUDGET_FILENAME} not found in {engagement_dir} — using the built-in conservative default")

    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        return _fallback(f"{BUDGET_FILENAME} is not valid YAML ({exc}) — using the built-in conservative default")

    if raw is None:
        return _fallback(f"{BUDGET_FILENAME} is empty — using the built-in conservative default")
    if not isinstance(raw, dict):
        return _fallback(
            f"{BUDGET_FILENAME} must be a mapping of dimension -> ceiling, got {type(raw).__name__} "
            "— using the built-in conservative default"
        )

    unknown = sorted(set(raw) - set(BUDGET_DIMENSIONS))
    if unknown:
        return _fallback(
            f"{BUDGET_FILENAME} has unknown dimension(s) {unknown} — using the built-in conservative default"
        )

    values = dataclasses.asdict(DEFAULT_BUDGET_LIMITS)
    for dim in BUDGET_DIMENSIONS:
        if dim not in raw:
            continue  # omitted -> keep the conservative default for THIS dimension
        value = raw[dim]
        if value is None:
            values[dim] = None  # explicit, operator-written "unlimited" — never implied
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return _fallback(
                f"{BUDGET_FILENAME}: {dim!r} must be a number or null, got {value!r} "
                "— using the built-in conservative default"
            )
        if value < 0:
            return _fallback(
                f"{BUDGET_FILENAME}: {dim!r} must be >= 0, got {value!r} — using the built-in conservative default"
            )
        values[dim] = value

    return BudgetConfigResult(limits=BudgetLimits(**values), source="file", reason=None)
