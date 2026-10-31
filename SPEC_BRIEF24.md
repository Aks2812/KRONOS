# SPEC_BRIEF24 — S8 Agent layer: dispatcher dependency-DAG (`any_of` / `blocked_by`, hermetic/mock)

**Stage:** S8 agent layer, dependency-DAG rung (maintainer-authorized next direction; lifts pause #2
for this rung only — hermetic/mock, NO §6, NO live network/LLM/budget, NO SECRET/WEB_ENDPOINT
commit/execute work). Global gates, rails, and §4 Hard boundaries bind per `CLAUDE.md` §4 + the v7
contract (R8 — not restated here). CyberGym only.

## §1 — Problem

`Intent(kind, target_id, rationale)` (`contracts.py:16-20`) carries no dependency fields; an intent's
identity downstream is the pair `(kind, target_id)` (e.g. `dispatcher.py:55`). `validate_reason_payload`
ignores unknown keys (`contracts.py:38`), so a driver cannot express that one proposed intent should
only be dispatched after another, or after at least one of a set. `run_once` adjudicates all intents
(phase 1), commits the approved+in-scope ones in list order (phase 2, `dispatcher.py:88-92`), then
executes committed ones (phase 3). `DispatcherResult` (`dispatcher.py:18-26`) has no field to report an
intent that was deliberately not dispatched. This rung adds deterministic intra-batch dependency
gating so a `Driver` can propose a small dependency DAG within one `reason()` batch (≤ `MAX_INTENTS`=4).

## §2 — Approach (fixes the values the repo leaves silent; expected test values derive from this prose)

Scope is **one `run_once` batch** (the ≤4 intents from a single `reason()` call). Dependencies gate
intents **within that batch only** — no cross-step/cross-call dependency state. Hermetic: Mock driver/
reviewer/executor only; no network, no LLM.

- **D1 — reference key.** An intent's canonical key is `f"{kind}:{target_id}"`. `any_of`/`blocked_by`
  entries are such key strings naming **other intents in the same batch**.
- **D2 — new optional intent fields.** `Intent` gains `any_of: tuple[str, ...] = ()` and
  `blocked_by: tuple[str, ...] = ()` (frozen dataclass defaults → absent = empty = unconstrained,
  backward compatible). `validate_reason_payload` reads them when present: each must be a `list`/
  `tuple` of `str`, else `ContractViolation`; they join the known keys (no longer silently ignored).
  `FORBIDDEN_FIELDS` unchanged.
- **D3 — satisfaction signal = committed.** An intent is *satisfied* iff it is **committed** (approved
  by reviewer AND in scope). This is executor-independent and deterministic (promotion needs an
  executor + evidence and is NOT the signal).
- **D4 — gating semantics.** For an intent with dependencies: it is **eligible to commit** iff
  (a) `blocked_by` — **every** referenced intent is satisfied, AND (b) `any_of` (when non-empty) —
  **at least one** referenced intent is satisfied. An eligible intent then still commits only if it is
  itself approved + in scope (the existing phase-2 condition). An intent that is **ineligible** (a
  dependency gate fails, incl. transitively because a dependency was itself withheld or not committed)
  is **withheld**: not committed, not executed.
- **D5 — fail-closed validation (new phase 0, pure, before any adjudication/write).** Build the
  key→intent map for the batch. Then, **only when any intent in the batch carries a non-empty
  `any_of` or `blocked_by`:** (i) if two intents share a canonical key → `ContractViolation`
  (ambiguous reference); (ii) any `any_of`/`blocked_by` entry that is not a key present in the batch →
  `ContractViolation` (**unknown reference, fail-closed** — never dispatch past an unresolved ref);
  (iii) a dependency cycle (including a self-reference) → `ContractViolation`. All three raise before
  phase 1, so the graph is untouched on violation. When no intent carries dependencies, phase 0 adds
  no edges and changes nothing.
- **D6 — deterministic order.** Phase 2 processes intents in a **stable topological order**: Kahn's
  algorithm with original list order as the tie-break for ready nodes (with no edges this equals the
  current list order, preserving today's commit order exactly).
- **D7 — withheld surfaced.** `DispatcherResult` gains `withheld: tuple[str, ...] = ()` — the
  canonical keys of intents withheld by D4 gating (NOT intents merely review-rejected or out of scope;
  those remain, as today, simply absent from `committed`). Default `()` keeps all existing results
  backward compatible.

Phases 1 (adjudicate all, no writes) and 3 (execute committed) keep their current structure and the
"no writes until every verdict is validated" property; only phase 2 gains topological ordering + the
D4 eligibility gate, and phase 0 is prepended.

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only 73cbe8b..HEAD` ⊆ set)

1. `SPEC_BRIEF24.md`
2. `src/kronos/agent/contracts.py` (edit: `any_of`/`blocked_by` on `Intent`; validate them in
   `validate_reason_payload`)
3. `src/kronos/agent/dispatcher.py` (edit: phase-0 validation, topo order + D4 gate in phase 2,
   `withheld` field on `DispatcherResult`)
4. `tests/test_agent_dispatcher.py` (append §8 tests **after `test_O`**; do **NOT** touch `test_L` /
   `test_M` or their constants — they stay frozen and green)
5. `tests/test_agent_contracts.py` (append §8 negative contract tests for the new fields)
6. **`tests/test_agent_live_driver.py` (seal-only edit, amendment):**
   brief23's `test_F2_scope_audit_whole_window` uses the unsealed window `f"{BRIEF_BASE}..HEAD"`
   (`BRIEF_BASE="056f441"`, `test_agent_live_driver.py:38-41`), which trips on every later branch that
   edits `contracts.py`/`dispatcher.py`. Add `BRIEF_MERGE = "73cbe8b"` (brief23's PR #31 squash merge,
   SEQ 140) and change the window to `f"{BRIEF_BASE}..{BRIEF_MERGE}"`, pinning the audit to brief23's
   own footprint — exactly as brief23 §3 item 5 sealed brief22's F2 and as `test_L`/`test_M` seal.
   **No other change to this file.** Mechanically required for suite-green (§8 G2); test_L/test_M
   precedent. (Amendment recorded 2026-10-31; self-approved GATE-1, no scope expansion.)

Base = `origin/main` @ `73cbe8b`. Never `git add -A`; stage explicit paths only. **Add no new
dependency.** Do **NOT** edit `planner.py`, `drivers.py`, `executor.py`, `live_executor.py`,
`live_driver.py`, `reviewer.py`, `schema.py`, `query.py`, `__init__.py`, anything under
`src/kronos/budget/` or `src/kronos/validate/`, `requirements.txt`, `pyproject.toml`, `manifest.py`,
`.github/`, or anything under `cybergym/`. The frozen `test_L`/`test_M` (dispatcher) and brief22/23
seal tests must stay untouched and green.

**Scope-audit test naming (mechanical).** `test_M_brief15_seal` asserts the literal
`f"{BRIEF_BASE}..HEAD"` is **absent** from `test_agent_dispatcher.py`. The new whole-window audit MUST
therefore use a **distinct** base constant (e.g. `B24_BASE = "73cbe8b"`) and window
`f"{B24_BASE}..HEAD"` — never `f"{BRIEF_BASE}..HEAD"` — so `test_M` stays green.

## §8 — Acceptance criteria (tests-as-rules; expected values from §2 prose, not observed behaviour)

Decide PASS/FAIL from pytest's `SUMMARY:` line, never `$?` (`CLAUDE.md` §3). Every test is hermetic:
Mock driver/reviewer/executor, a plain in-memory engagement, a `nonet`-style socket patch on any path
that runs the loop. New dispatcher tests appended after `test_O`; new contract tests appended in
`test_agent_contracts.py`.

A. **`blocked_by` satisfied → dispatched.** Batch `[X, Y]`, Y `blocked_by=["<X key>"]`, reviewer
   approves both, both in scope → both committed; `withheld == ()`.
B. **`blocked_by` unsatisfied → withheld.** Same batch but reviewer rejects X (or X out of scope) →
   X not committed, Y **withheld** (`Y key` in `result.withheld`, not in `committed`).
C. **`any_of` satisfied / unsatisfied.** Z `any_of=["<X key>", "<W key>"]`: if at least one of X/W is
   committed → Z eligible (commits if itself approved+in-scope); if none of X/W committed → Z withheld.
D. **Transitive withholding.** `[X, Y, Z]`, Y `blocked_by=["<X key>"]`, Z `blocked_by=["<Y key>"]`,
   X rejected → Y and Z both withheld.
E. **Unknown reference → `ContractViolation`, no writes.** Y `blocked_by=["nope:0"]` → `run_once`
   raises `ContractViolation`; engagement node count unchanged (non-vacuity: assert count before ==
   after).
F. **Cycle → `ContractViolation`, no writes.** A `blocked_by=["<B key>"]`, B `blocked_by=["<A key>"]`
   → raises; graph untouched. Also self-reference A `blocked_by=["<A key>"]` → raises.
G. **Duplicate key with deps → `ContractViolation`.** Two intents with identical `(kind, target_id)`
   while some intent carries a dependency → raises.
H. **Deterministic topo order.** A batch whose list order differs from dependency order
   (e.g. `[Y(blocked_by X), X]`) commits X before Y; assert the `committed` tuple order is
   `(<X finding id>, <Y finding id>)`.
I. **Backward-compat golden.** A batch with **no** dependency fields yields the **same** `committed`
   and `promoted` tuples as the current behaviour and `withheld == ()` (assert against the pre-change
   list-order expectation).
J. **Contract field validation (negative, `test_agent_contracts.py`).** An intent dict with
   `any_of` not a list (e.g. a str), or with a non-str element, or `blocked_by` likewise →
   `validate_reason_payload` raises `ContractViolation`. A well-formed `any_of`/`blocked_by` of
   `list[str]` is accepted and surfaces on the resulting `Intent` as a `tuple[str, ...]`.
K. **No network** — a `test_K`-style socket assertion proves the loop opens no socket on the paths
   above.
L2. **Scope audit (whole window)** — `git diff --name-only 73cbe8b..HEAD` ⊆ the §3 set, using the
   distinct `B24_BASE` constant per §3's naming note.
F3. **brief23 F2 sealed** — `test_agent_live_driver.py::test_F2_scope_audit_whole_window` uses window
   `f"{BRIEF_BASE}..{BRIEF_MERGE}"` with `BRIEF_MERGE = "73cbe8b"`, **not** `..HEAD`, so it is pinned
   to brief23's footprint and passes on this and later branches (§3 item 6 amendment).
G2. **Suite green** — full `pytest` reports `0 failed` on the final commit (totals refreshed as the
   last edit); `test_L`/`test_M` and the brief22/23 seals untouched and green.

## §9 — Done when

All of §8 holds; `any_of`/`blocked_by` gate intra-batch dispatch per D3–D4 with the D5 fail-closed
validation (unknown ref, cycle, duplicate-keyed ref all raise `ContractViolation` before any write);
`withheld` reports gated-out intents; the backward-compat golden is identical to pre-change behaviour;
no new dependency, no env var, no out-of-§3 path changed; no live network or LLM call occurs; and the
full suite is green on the head commit. No live run, no §6 capability, no budget wiring is part of this
brief.
