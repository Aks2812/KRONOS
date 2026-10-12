"""The ceilings a `BudgetLedger` enforces (SPEC_BRIEF5 §2/§1 guardrail 3).

`BudgetLimits` is a plain, frozen data holder — no graph access, no I/O,
no decision logic. Every field is `float | int | None`; `None` means
"unlimited for this dimension," which a caller can only reach by writing
it explicitly (as a literal `null` in `budget.yaml`) or by constructing
`BudgetLimits` directly themselves. `config.py`'s loader never produces
`None` for a dimension on its own — a dimension a `budget.yaml` leaves
out still gets `DEFAULT_BUDGET_LIMITS`'s value, not `None` — so an
engagement is never unlimited by *accident* (guardrail 3).
"""

from __future__ import annotations

from dataclasses import dataclass

# The only five dimensions this brief knows about (SPEC_BRIEF5 §2 table).
# `config.py` and `ledger.py` both drive off this tuple rather than
# hardcoding the field list a second time.
BUDGET_DIMENSIONS: tuple[str, ...] = (
    "validation_attempts",
    "tool_invocations",
    "wall_clock_seconds",
    "llm_tokens",
    "llm_cost_usd",
)


@dataclass(frozen=True)
class BudgetLimits:
    validation_attempts: int | None = None
    tool_invocations: int | None = None
    wall_clock_seconds: float | None = None
    # Pre-wired for the agent layer (SPEC_BRIEF5 §2): nothing charges
    # these two dimensions yet, but the ceiling — and the chargeable API
    # on `BudgetLedger` — already exist, so that layer needs zero new
    # budget plumbing when it lands.
    llm_tokens: int | None = None
    llm_cost_usd: float | None = None


# The conservative built-in default (guardrail 3: "missing/invalid
# budget.yaml falls back to a conservative default ceiling, not
# unlimited"). Sized generously enough that a real, small engagement run
# (SPEC_BRIEF5 §4 test 6, the CyberGym fixture) comfortably finishes
# under it, while still being a real, finite ceiling — an accidentally
# unbounded run is exactly what this brief exists to prevent.
#
# `llm_tokens`/`llm_cost_usd` default to 0, not some generous guess:
# nothing in this codebase charges either dimension today, so the only
# honest "conservative default" for a capability that doesn't exist yet
# is "none spent, none authorized" — an operator has to opt in via
# `budget.yaml` once the agent layer actually needs to spend here.
DEFAULT_BUDGET_LIMITS = BudgetLimits(
    validation_attempts=500,
    tool_invocations=1000,
    wall_clock_seconds=3600.0,
    llm_tokens=0,
    llm_cost_usd=0.0,
)
