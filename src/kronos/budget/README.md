# Per-engagement budget governance (`kronos.budget`)

A deterministic, code-enforced ceiling on what a single engagement run
may consume — validation attempts, external tool/HTTP calls,
wall-clock, and (pre-wired, unused today) LLM tokens/cost. Built because
an autonomous agent layer without a fail-closed spending ceiling is the
single biggest cost-and-safety risk in the whole design, and this has
to exist *before* that layer does (SPEC_BRIEF5 §0).

## Design north star

**Fail-closed, deterministic, single chokepoint.** When a budget is
exhausted the run stops cleanly and keeps what it has — it never
silently continues unmetered. No LLM, no heuristic, is ever in a budget
decision: same inputs + same budget ceilings -> the identical stop
point, every time.

## Modules

- **`limits.py`** — `BudgetLimits`, a frozen dataclass of five optional
  ceilings (`validation_attempts`, `tool_invocations`,
  `wall_clock_seconds`, `llm_tokens`, `llm_cost_usd`). `None` means
  unlimited for that one dimension — reachable only by an operator's
  explicit `null` in `budget.yaml`, never by omission.
  `DEFAULT_BUDGET_LIMITS` is the conservative built-in fallback: generous
  enough for a real small engagement to finish comfortably under it,
  but always a real, finite ceiling. `llm_tokens`/`llm_cost_usd` default
  to `0` — nothing charges either dimension yet, so "none spent, none
  authorized" is the only honest default until an operator opts in.
- **`config.py`** — `load_budget_limits(engagement_dir)` reads
  `budget.yaml` from the engagement dir. Missing, empty, unparseable,
  or malformed -> `DEFAULT_BUDGET_LIMITS`, with the reason recorded in
  the returned `BudgetConfigResult` for the ledger/report to carry
  forward. A *valid* file that simply omits a dimension still gets that
  dimension's conservative default, one field at a time — a run is
  never unlimited by accident just because an operator's `budget.yaml`
  happened not to mention `llm_cost_usd`.
- **`ledger.py`** — `BudgetLedger`, the chokepoint. `charge(dimension,
  amount, *, actor, detail)` is the one API every cost-incurring action
  in the codebase spends through. It checks the ceiling BEFORE
  recording anything; a charge that would cross it raises
  `BudgetExceeded` and changes nothing — the action it would have paid
  for is never started. `snapshot()`/`write_ledger_snapshot()` produce
  the audit trail: every dimension's ceiling next to what's actually
  been spent, the append-only entry log, where the limits came from,
  and (when tripped) which dimension stopped the run.

## Wall-clock is special

Every other dimension is a plain running sum of discrete charges.
Wall-clock is real elapsed time since the ledger was created, so
`charge()` re-measures and re-checks it on **every** call — not only
when a caller happens to charge the `wall_clock_seconds` dimension
itself. `check_wall_clock()` exposes that same assertion standalone,
for an orchestrator to call between pipeline phases that charge
nothing at all (e.g. standing up a Docker lab, or a reconciliation
pass — neither is a metered dimension), so a long charge-free gap still
can't blow through the overall ceiling unnoticed until the next charge.

## Why FORK-E's DEFAULT needs no special code

FORK-E asks what happens the moment a ceiling is crossed: let the
in-flight atomic action finish, then stop before the next (the
DEFAULT), or abort it immediately. Because every caller charges
*before* performing its action (never after), and every action KRONOS
performs today runs synchronously to completion before the next one's
charge is even attempted, there is no "abort a half-done action" case
to build: an action whose own charge raises was simply never started,
and any action that already passed its charge keeps running to its
normal, already-correct completion. The DEFAULT falls out of the
calling convention for free.

## Why budget enforcement can't launder the lifecycle

`BudgetLedger` knows nothing about SECRET/FINDING status, evidence, or
scope. `kronos.validate.runner` is the only caller that charges it
today, and it charges at exactly one point — immediately before
invoking a validator — which is strictly *before* any of
`_advance_through`/`attach_evidence`/the `authenticates_to` edge write
run. A `BudgetExceeded` raised there propagates straight out of
`run_validation_pass`, uncaught, before any of that status-advancing
code executes. Nothing under `src/kronos/budget/` calls
`advance_secret_status`, and nothing in the lifecycle module knows the
ledger exists — budget wraps *around* validation; it never reaches
into guardrail 2's territory.

## What's deliberately NOT here

- **No per-tool sub-cap.** SPEC_BRIEF5 §2 calls this a nice-to-have,
  "include only if it falls out cleanly" — it didn't fall out cleanly
  (it would mean a second ceiling dimension per tool name, not a single
  flat dimension set), so it isn't built. `detail` on every
  `BudgetLedgerEntry` still records which tool/target each charge was
  for, so a future brief can add this without touching the entry
  format.
- **No signed budget.** FORK-D's DEFAULT keeps `budget.yaml` outside
  the Ed25519-signed scope manifest on purpose — scope authorization
  (what you may touch) and operational budget (how much you may spend)
  are different concerns, and signing the budget would force a re-sign
  for every token-limit tweak. Worth revisiting once the agent layer
  can self-modify its own config.
- **No charge for reconciliation.** `kronos.reconcile` makes no
  external call and attempts no validation — it isn't a cost-incurring
  action under SPEC_BRIEF5 §2's dimension table, so it isn't charged.
  Wall-clock elapsed during a reconciliation pass is still caught by
  the next `check_wall_clock()`/`charge()` call downstream.
