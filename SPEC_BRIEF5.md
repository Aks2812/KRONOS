# SPEC_BRIEF5.md — Per-engagement budget governance

**Status:** build brief (stateless). Build only after PR #6 (reconciliation) is merged to main;
start from main, new branch, open a PR, do NOT merge.
**Autonomy:** Balanced. Proceed on reversible calls. Escalate only the FORKs below
(FORK / OPTIONS / RECOMMENDATION / DEFAULT); both carry a DEFAULT — if unattended, take it and
record it.

---

## 0. Why this brief exists (read first)

KRONOS needs a deterministic, code-enforced ceiling on what a single engagement run may consume —
validation attempts, tool invocations, wall-clock, and (pre-wired for the agent layer) LLM
tokens/cost. Two reasons this is the next quick win rather than EPSS/KEV enrichment:

- It meters actions that already happen today (validation attempts, tool/HTTP calls, wall-clock),
  so it is useful immediately — not infrastructure waiting on data that doesn't exist yet.
- It is a **hard prerequisite for the agent layer.** An autonomous planner/executor without a
  fail-closed budget ceiling is the single biggest cost-and-safety risk in the whole design. This
  must exist before that phase.

Design north star: **fail-closed, deterministic, single chokepoint.** When a budget is exhausted
the run stops cleanly and writes what it has — it never silently continues unmetered (explicitly
NOT Pentest-Swarm's fails-open behavior), and no LLM is ever in a budget decision.

---

## 1. Hard guardrails

1. `src/kronos/scope_guard.py` MUST stay a zero-line diff (FORK-2 / GitHub #2 untouched).
2. Do not weaken the validation lifecycle or the secret-validation path. `advance_secret_status`
   stays the only forward mutator; budget enforcement wraps *around* validation, never inside its
   status/evidence logic.
3. **Fail-closed, never fail-open.** A charge that would exceed a ceiling stops the run; it never
   downgrades to "continue without metering." A missing/invalid budget config → a conservative
   built-in default ceiling, not unlimited.
4. **Deterministic only.** No LLM, no heuristic, in any budget decision. Same inputs + same budget
   → same stop point (add a test).
5. **Single chokepoint**, like scope_guard: every cost-incurring action charges the ledger through
   one API. No scattered per-caller counting.
6. Budget exhaustion produces a clean stop + a partial report + the ledger. Never a crash, never a
   half-finished atomic action (see FORK-E), never an unmetered continuation.

---

## 2. Design

New module `src/kronos/budget/`:

- `limits.py` — a frozen `BudgetLimits` dataclass: the ceilings (all optional; `None` = unlimited
  for that dimension, but the loader supplies conservative defaults so a run is never fully
  unlimited by accident).
- `config.py` — load per-engagement limits from `budget.yaml` in the engagement dir; on
  missing/invalid, fall back to the built-in conservative default and record that it did.
- `ledger.py` — `BudgetLedger`: the chokepoint. `charge(dimension, amount, *, actor, detail)`
  accumulates spend and raises `BudgetExceeded` when a charge would cross a ceiling. Append-only
  entries (dimension, amount, running total, actor, detail, timestamp). A `snapshot()` for the
  audit trail and the partial-report footer.

### Dimensions to meter (start with what exists today; pre-wire the rest)

| Dimension            | Metered today? | Notes |
|----------------------|----------------|-------|
| `validation_attempts`| yes            | charged once per candidate validation attempt in `validate.runner` |
| `tool_invocations`   | yes            | charged per external tool / HTTP auth call |
| `wall_clock_seconds` | yes            | engagement elapsed time; checked at each charge and between phases |
| `llm_tokens`         | pre-wired      | no LLM calls today; the dimension + charge API exist so the agent layer plugs in with zero new budget plumbing |
| `llm_cost_usd`       | pre-wired      | same |

Keep per-dimension ceilings AND an optional overall wall-clock cap. A per-tool sub-cap
(`max per tool`) is a nice-to-have — include it only if it falls out cleanly; don't over-build.

### Enforcement flow

- The ledger is created once per run from the loaded `BudgetLimits`, passed to the components that
  spend (validation runner today; agent executor later).
- Each component calls `ledger.charge(...)` BEFORE performing the action. If it raises
  `BudgetExceeded`, the component stops starting new work and lets the run wind down cleanly.
- At wind-down: write the ledger snapshot to the engagement dir, emit the partial report/X-score
  with a clear "stopped early: budget <dimension> exhausted" marker, and exit non-crash.

---

## 3. FORKs (pre-resolved)

**FORK-D — where budget limits live**
- OPTIONS: (1) a separate `budget.yaml` in the engagement dir, code-enforced, limits echoed into
  the ledger at run start. (2) a signed section inside the Ed25519 manifest.
- RECOMMENDATION / **DEFAULT: option 1 (`budget.yaml`).** Scope authorization (what you may touch)
  and operational budget (how much you may spend) are different concerns; coupling them forces a
  re-sign for a token-limit tweak. Keep the signed manifest about scope only. (Signing the budget
  can be revisited once the agent layer can self-modify config — note it as a future item.)

**FORK-E — behavior at the moment a ceiling is crossed**
- OPTIONS: (1) let the current in-flight atomic action finish, then stop before the next.
  (2) abort the in-flight action immediately.
- RECOMMENDATION / **DEFAULT: option 1.** Charging happens before an action; if a mid-action check
  trips, aborting could leave a half-done validation / dangling edge. Finishing the current atomic
  action then stopping keeps the graph consistent. (The charge-before-start design means the
  overshoot is at most one action.)

---

## 4. Acceptance tests

1. **Fail-closed enforcement:** a run with a tiny `validation_attempts` cap stops exactly at the
   cap; assert the over-cap attempt never ran (no extra `authenticates_to` edge, no extra attempt
   in the result), and the ledger shows the cap hit.
2. **Never fails open:** with an exhausted budget, assert the run stopped and performed zero
   further charged actions — not that it continued unmetered.
3. **Determinism:** same graph + same budget → identical stop point and identical ledger
   (timestamps aside) across two runs.
4. **Wall-clock cap:** a near-zero wall-clock cap triggers a clean stop with the right marker.
5. **Missing/invalid `budget.yaml`:** falls back to the conservative default ceiling (not
   unlimited) and records that it did.
6. **Non-interference:** the full CyberGym run with a generous budget still earns **X-score 3/3**,
   and the ledger reports consumption below every ceiling.
7. **Audit:** the ledger snapshot is written to the engagement dir, is append-only, and is
   queryable/parseable; the partial-report path carries the "stopped early" marker when tripped.
8. **Guardrail diffs:** `scope_guard.py` zero-line; `advance_secret_status` still the only forward
   mutator, still called only by the validation runner (grep-assert or state it).

---

## 5. Output expected back

- Branch + PR link (not merged); diff summary; full test-suite count.
- Confirmation of both guardrail diffs (scope_guard zero-line; lifecycle mutator unchanged).
- Which FORK options were taken (DEFAULT or escalated).
- Confirmation the CyberGym run still earns X-score 3/3 with a generous budget, plus the ledger
  snapshot from that run (consumption vs each ceiling).
- Confirmation that `BudgetExceeded` is fail-closed everywhere it's raised (no catch-and-continue),
  and that the `llm_tokens`/`llm_cost_usd` dimensions exist and are chargeable even though nothing
  charges them yet.
