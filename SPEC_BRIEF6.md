# SPEC_BRIEF6.md — Engagement cleanup / teardown registry

**Status:** build brief (stateless). Start from latest main (must contain `src/kronos/budget/` from
PR #7). New branch, open a PR, do NOT merge. Cloud build.
**Autonomy:** Balanced. Proceed on reversible calls. Escalate only the FORKs below
(FORK / OPTIONS / RECOMMENDATION / DEFAULT); both carry a DEFAULT — if unattended, take it and
record it.

---

## 0. Why this brief exists

The last of the four quick wins. An authorized external-client engagement must leave **nothing
behind** — no live Docker containers, no temp credential files on disk, no orphaned processes,
no scratch state. Today the CyberGym orchestrator tears its range down ad-hoc in a `finally`;
this brief generalizes that into a real registry so every ephemeral artifact an engagement
creates is tracked and guaranteed to be torn down — on success, on a budget stop, and on a crash.

This is also the last guardrail before the agent layer: once autonomous agents start spawning
containers and processes on their own, you want the teardown registry already in place, not
retrofitted onto a system that's already making a mess.

---

## 1. Hard guardrails

1. `src/kronos/scope_guard.py` MUST stay a zero-line diff (FORK-2 / GitHub #2 untouched).
2. Do not weaken the validation lifecycle, the reconciliation pass, or the budget ledger.
   `advance_secret_status` stays the only forward mutator.
3. **Teardown MUST run even when the budget is exhausted.** This is the key cross-module rule:
   cleanup operations do NOT go through `BudgetLedger.charge` and are never blocked by a
   `BudgetExceeded`. An engagement that burns its budget and stops must STILL tear everything
   down — otherwise exhausting the budget leaks artifacts, which is the exact opposite of what
   both briefs are for. (Observability-only logging of cleanup is fine; a charge that can raise
   is not.)
4. **Teardown is best-effort-but-reported, never silently swallowed.** Each teardown attempt is
   recorded; a failure is captured in the report (what couldn't be cleaned + why) so the operator
   can finish by hand. Not fails-open-and-forgets.
5. **Deterministic, no LLM.** Pure bookkeeping.
6. Credential material registered for teardown is **removed from disk** (shredded/unlinked), not
   just logged — never leave cred files behind.

---

## 2. Design

New module `src/kronos/cleanup/`:

- `registry.py` — `CleanupRegistry` and `TeardownReport`.
  - `register(kind, handle, teardown, *, detail)` records an artifact and the zero-arg callable
    that disposes it. Registration is append-only; order is preserved.
  - `teardown_all()` disposes everything in **LIFO** order (reverse of creation — containers
    before the network they attach to, files before their parent dir), catching each item's
    errors independently so one failure never blocks the rest, and returns/records a
    `TeardownReport` (each item: kind, detail, outcome=done|already_gone|failed, error if any).
  - Idempotent: a second `teardown_all()` is a no-op; an already-gone artifact counts as success,
    not failure.
  - Context-manager form: `with CleanupRegistry() as reg:` runs `teardown_all()` on exit
    **including when the body raises** (the artifacts still get cleaned, then the exception
    propagates). This is the crash-safety mechanism (FORK-G).
- `kinds.py` — teardown callables for the artifact kinds, each idempotent and safe on
  already-gone input:
  - **docker** — container / network / volume removal (the real integration point; the CyberGym
    range uses these today). Use `docker rm -f` / `network rm` / `volume rm` semantics that treat
    "no such object" as success.
  - **filesystem** — temp file / dir removal.
  - **credential** — unlink a temp cred file (shred); treat missing as success.
  - **process** — terminate a spawned background process (pre-wired for the agent layer; nothing
    spawns long-lived procs today, but the kind + teardown exist so that layer needs no new
    cleanup plumbing).
- `README.md`.

### Integration

Wire into `cybergym/kronos_validation_run.py`: wrap the engagement body in a `CleanupRegistry`
(context-manager), register the Docker range resources + any temp files as they're created, and
let teardown run on exit — on the happy path, on the `BudgetExceeded` wind-down, and on any
exception. Write the `TeardownReport` to the engagement dir alongside the budget ledger. The
existing ad-hoc `finally` teardown is replaced by (or delegates to) the registry — don't leave
two competing teardown paths.

---

## 3. FORKs (pre-resolved)

**FORK-F — does teardown charge the budget?**
- OPTIONS: (1) teardown is budget-exempt — never charges, never blocked by `BudgetExceeded`.
  (2) teardown charges `tool_invocations` like any other action.
- RECOMMENDATION / **DEFAULT: option 1 (exempt).** Guardrail 3 — cleanup must run even when the
  budget is exhausted, so it cannot depend on spare budget. (Optional: log cleanup actions for
  observability, but never via a charge that can raise.)

**FORK-G — crash-safety mechanism**
- OPTIONS: (1) context-manager / explicit `try/finally` owned by the orchestrator.
  (2) `atexit` / signal handlers.
- RECOMMENDATION / **DEFAULT: option 1.** Deterministic and testable; teardown is tied to the
  engagement scope, not process exit. Do not rely on `atexit`/signal handlers as the primary
  mechanism (unreliable under hard kills, hard to test) — at most a secondary backstop, and only
  if it falls out cleanly.

---

## 4. Acceptance tests

1. **LIFO teardown:** register several artifacts; `teardown_all()` disposes them in reverse order
   (assert the recorded order).
2. **Teardown on exception:** inside `with CleanupRegistry() as reg:`, register artifacts, then
   raise mid-body; assert every artifact was torn down and the original exception still propagated.
3. **Teardown after budget exhaustion (the key cross-module test):** simulate a run that raises
   `BudgetExceeded`; assert cleanup still ran fully and the teardown report is written — cleanup
   is not gated by budget.
4. **Idempotent:** `teardown_all()` twice is safe; an already-gone artifact is reported
   `already_gone`/success, not `failed`.
5. **Partial failure reported, not fatal:** one teardown callable raises; the others still run,
   the report records the failure + reason, and `teardown_all()` itself does not raise.
6. **Credential shred:** a registered temp cred file is actually removed from disk after teardown.
7. **Live CyberGym end-to-end:** after the run finishes (happy path), assert no leftover KRONOS
   range containers/networks remain (`docker ps -a` / `network ls` show none), and X-score is
   still **3/3**. If feasible, also assert teardown ran on a forced early stop.
8. **Guardrail diffs:** `scope_guard.py` zero-line; lifecycle/budget mutators unchanged; cleanup
   makes no `BudgetLedger.charge` call that can block teardown.

---

## 5. Output expected back

- Branch + PR link (not merged); diff summary; full test-suite count.
- Confirmation of guardrail diffs (scope_guard zero-line; lifecycle + budget untouched).
- Which FORK options were taken (DEFAULT or escalated).
- Explicit confirmation that teardown runs even on `BudgetExceeded` (name the test), and that no
  cleanup path can be blocked by an exhausted budget.
- Confirmation the live CyberGym run still earns X-score 3/3 AND leaves zero range artifacts
  behind, with the `TeardownReport` from that run.
