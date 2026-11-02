# SPEC_BRIEF30 (APPROVED rev5 — GATE-1 self-approved; rev5 clarifies fail-closed torn-first-line per review attempt 2) — Shared Stop Primitive + Independent Watchdog: Hermetic G2

> **rev5 (checkpoint SEQ 207; review attempt 2 FAIL — N1 MEDIUM).** §4.1 clarified: `is_stopped` must
> **fail CLOSED** on a non-empty but unparsable FIRST line (a stop is never lost to a torn write); lines
> are newline-terminated. This corrects the rev4 F6 wording, which the builder over-applied to the first
> line (fail-open). Also N2 (LOW): `nonet` required on every new test (brief §12 C10). Both are builder
> fixes; no scope/goal change.

> **rev4 (checkpoint SEQ 205; review attempt 1 FAIL).** Softens four LOW brief over-claims to match a
> testable/implemented reality — no scope/goal change: (F4) §12 C3 is **counts-based** (no byte-identical
> Kùzu-DB claim); (F5) the stop-record field is **`timestamp`** and later appended lines **are** the
> audit trail (no separate named `also_requested` list); (F7) D1 budget→stop adaptation is the
> **dispatcher's executor boundary** (the only in-scope budget site); (F8) a persisted stop is **durable
> by design** (safety) and not auto-cleared. The HIGH finding **F1** (run()-loop stop read, already
> required by §4.2) and MED **F2/F3** + LOW **F6** are **builder fixes**, not brief changes.

> **rev3 corrections (checkpoint SEQ 203; verified against `autonomy.py`/`test_autonomy.py` on
> `main@93fb05e`).** (1) `EffectiveEnvelope` has **no** `watchdog` field (`autonomy.py:70-82`); the
> signed policy lives only on `AutonomyEnvelope.watchdog` (`manifest.py:92-109`), reached via a
> `VerifiedManifest`. The watchdog therefore consumes the **verified in-force `VerifiedManifest`** and
> reads `.autonomy.watchdog` — `autonomy.py` is **not** edited (§4.4/§9). (2) The prior-brief
> whole-window scope-audit seal is `tests/test_autonomy.py::test_B29_Q_scope_audit`
> (`B29_BASE=55b4b7f..HEAD`), **not** `tests/test_query.py`; §10 seals it there (seal only).
>
> Fully hermetic: no live targets, no §6 run, no providers, no network execution, and
> **no wiring of autonomous action execution**. Builds on SPEC_BRIEF29 (merged `main` @ 93fb05e,
> PR #37): the signed `WatchdogPolicy` (`may_auto_stop`, `confirm_window_seconds`) now exists but has
> **no runtime consumer** — this brief proposes that consumer and the shared stop mechanism it drives.
>
> **rev2 — operator decisions D1–D5 applied + two P0 resolved (context.md 2026-11-01; checkpoint
> SEQ 200–201; researcher claude-sonnet-5).** D1 budget→idempotent `request_stop(source="budget")`
> preserving the original `BudgetExceeded` reason/event; D2 existing event kinds only; D3 defer
> `events.py`; D4 dispatcher owns one `try/finally` cleanup boundary running exactly once; D5
> `confirm_window_seconds` = persistent-condition grace period, then auto-stop iff `may_auto_stop`,
> else alert-only. **P0-1 (cross-process):** the stop primitive is **filesystem-backed**, not
> in-memory — operator and watchdog are separate processes. **P0-2 (race):** the "no graph/evidence
> state" claim is **narrowed** to evidence/promotion writes, with the atomic-commit prerequisite named
> (§3 A2, §4.2, §12 C4b). Both resolved **within the existing §10 allowlist** (no new files; no
> architecture delta beyond a filesystem-backed primitive in `stop.py`).

## §1 — Objective and relationship to G2

Deliver two hermetic, test-backed components that complete the control spine G2 needs before any
future unattended operation:

1. **One shared stop primitive** used identically by the operator and by the watchdog — a single
   cooperative cancellation object, **no separate kill path**.
2. **An independent watchdog** that consumes the *existing* event stream read-only and, only when the
   signed `may_auto_stop` permits and the signed `confirm_window_seconds` has elapsed, requests a stop
   through that same primitive.

This brief wires neither live execution nor autonomous action. It defines the primitive, the two
stop-check insertion points, the cancellation/cleanup semantics, and the watchdog, each proven by
hermetic tests. Autonomous *action execution* remains unwired (a later brief).

## §2 — Verified current-state baseline (main @ 93fb05e; cited, researcher claude-sonnet-5)

- **Signed watchdog policy (exists):** `src/kronos/manifest.py:92-100` `class WatchdogPolicy` —
  `may_auto_stop: bool = False`, `confirm_window_seconds: _NonNegInt = 0`; validator requires
  `1 <= confirm_window_seconds <= WATCHDOG_CONFIRM_WINDOW_MAX` when `may_auto_stop` is true.
  `WATCHDOG_CONFIRM_WINDOW_MAX = 300` (`manifest.py:38-39`). Carried on
  `AutonomyEnvelope.watchdog: WatchdogPolicy | None` (`manifest.py:103-109`). **`EffectiveEnvelope`
  has no `watchdog` field** (`autonomy.py:70-82`); `autonomy.py:295/310/336` read
  `AutonomyEnvelope.watchdog` in `_axes`/`_classify`, not an envelope field. **No runtime consumer of
  the signed watchdog policy exists** — this brief adds it, reading from the verified in-force
  `VerifiedManifest`.
- **No stop/cancel/kill/abort/halt/shutdown function exists** anywhere under `src/kronos` (grep).
  The only interruption today is `BudgetExceeded` (`src/kronos/budget/ledger.py:45`, raised at
  `:124`/`:146`, sets `_stopped_reason` at `:145`) — raised at a charge boundary, caught nowhere in
  `dispatcher.py`. `src/kronos/cleanup/kinds.py:125` `proc.kill()` is one per-artifact teardown
  action, not a general stop. **No watchdog/supervisor runtime exists.**
- **Action lifecycle (`src/kronos/agent/dispatcher.py`):** `run_once` — Phase 1 adjudicate
  (`:120-126`, no writes); **Phase 2 state-commit** `_commit(...)` (`:55-66` → `upsert_node`/
  `upsert_edge`) at `:127-141`; **Phase 3 action-start** `executor.execute(intent)` at `:145`, then
  `attach_evidence(...)` (`:147-154`) and `advance_finding_status(...)` (`lifecycle.py:219`) at
  `:155`. Outer `run()` loop `:164-192` checks a `deadline` at `:183` (the only existing per-step
  stop analog). **The two stop-check insertion points are: before Phase 2 (commit) and before
  Phase 3 (action start).**
- **Cleanup:** `src/kronos/cleanup/registry.py` `CleanupRegistry.teardown_all()` (`:112-140`) disposes
  LIFO, catches per-item exceptions and continues; `__exit__` (`:149-155`) runs `teardown_all()`
  unconditionally and never swallows the body exception; budget-decoupled by design (`:1-23`,
  `:9-11`). **But `dispatcher.py` does not use `CleanupRegistry` at all** — its action path is
  currently unwrapped (see §16 D4).
- **Event stream:** `src/kronos/events.py` `emit(stream, kind, **fields)` (`:53-76`) appends one JSON
  line to append-only `events.jsonl` (`:37`). `ALLOWED_KINDS` (`:42-50`) = only
  `ingest_started/ingest_finished/ingest_declined/reconcile_merged/reconcile_skipped_uncertain_key`
  — **no dispatcher/action/stop kinds today**. `emit` failures degrade to a warning, never raise
  (`:20-24`) — explicitly **not** load-bearing. **No reader/consumer function exists**; a reader
  opens the JSONL directly (see §16 D2/D3).
- **Budget:** `src/kronos/budget/limits.py:29-39` `BudgetLimits` (5 dims, `:20-26`);
  `DEFAULT_BUDGET_LIMITS` `:54-60`. `ledger.charge()` `:133-146` raises `BudgetExceeded`.
- **Hermetic test idiom:** the `nonet` fixture (monkeypatch `socket.socket` + `socket.create_connection`
  to raise `AssertionError`, assert unused) — `tests/test_agent_live_driver.py:42-61`,
  `tests/test_autonomy.py:80-86`, and ~9 other test files. New tests MUST follow it.

## §3 — Threat model and abuse cases

- **A1 — Unstoppable run.** An action continues after the operator (or watchdog) asks to stop.
  Mitigation: cooperative `StopToken` checked before every state-commit and every action-start.
- **A2 — Partial state on cancel (narrowed; P0-2).** Claim: *a cancelled action produces no
  **evidence or promotion** state* — no `EVIDENCE` node, no `evidences` edge, and no
  `hypothesis→reachable` status transition (`evidence.py` store_evidence/attach_evidence;
  `lifecycle.py:219` `advance_finding_status`). This is enforced by the pre-Phase-3 stop-check.
  **Explicitly NOT claimed:** that a cancelled step leaves *zero* graph writes. Phase-2 `_commit`
  (`dispatcher.py:55-66`) writes a `FINDING` node at status `"hypothesis"` (`reviewer.py:14`
  `COMMIT_STATUS`) *before* Phase 3 on every path — it is a reviewer **decision** record (adjudicated
  approved + in-scope), not an action **result**. A stop landing between Phase 2 and Phase 3 leaves
  exactly that already-committed hypothesis FINDING, identical to what already happens today when
  `executor.execute` fails or returns no evidence (researcher item 9: no distinct lifecycle status
  marks it). **This race is not hidden behind two checks:** the two checks provide two *distinct*
  guarantees — a stop before Phase 2 avoids the decision commit entirely; a stop before Phase 3 avoids
  the evidence/promotion write. Making even the Phase-2 decision atomic with (or rollback-able against)
  execution is the **later prerequisite** — an atomic `commit+execute` or an `EngagementGraph` rollback
  method, **neither of which exists today** (`graph.py` public surface is only
  `upsert_node`/`upsert_edge`/`get_node`/`execute`; no transaction/rollback). That prerequisite is
  out of scope for brief 30 and is required only when autonomous action execution is later wired.
- **A3 — Leaked resources on stop/budget-exhaustion.** Teardown skipped when budget is gone or on
  cancel. Mitigation: cleanup is budget-decoupled and runs on every exit path (normal, `BudgetExceeded`,
  stop).
- **A4 — Rogue/forged auto-stop authority.** Watchdog auto-stops without signed permission, or ignores
  the confirm window. Mitigation: watchdog honours only signed `may_auto_stop`; auto-stop is gated on
  `confirm_window_seconds` elapsed; policy reaches the watchdog only via the SPEC_BRIEF29 verified
  in-force `VerifiedManifest` (unforgeable — brief29 construction guard), from `.autonomy.watchdog`.
- **A5 — Second kill path.** A divergent stop/kill mechanism bypasses the shared primitive's checks.
  Mitigation: a single `request_stop` entry point; a structural test asserts no other stop/kill
  function is introduced.
- **A6 — Watchdog writes state.** The "independent" watchdog mutates graph/evidence/events.
  Mitigation: watchdog is read-only over `events.jsonl`; its only write effect is `request_stop` on
  the shared token. A test asserts it performs no graph/evidence/event write and no network.

## §4 — Architecture (proposed)

### §4.1 Shared stop primitive — `src/kronos/stop.py` (new) — FILESYSTEM-BACKED, cross-process (P0-1)

The operator and the watchdog are **separate processes**, so an in-memory object cannot be shared. The
primitive is a single **append-only on-disk stop record** under the engagement directory — the sole
stop entry point for every caller, with no second kill path.

- **Location.** `<engagement_dir>/stop.jsonl`, where `engagement_dir == EngagementGraph.db_path.parent`
  — the established flat location for every engagement-scoped file (events.jsonl, evidence/,
  budget_ledger.json, teardown report; researcher: `graph.py:70`, `events.py:71`,
  `ingest/web/parser.py:32`). Append-only, reusing the one durable idiom the repo already has
  (`events.py:73-74` `open(path, "a")`); **no atomic-rename/tempfile/flock machinery** is introduced —
  none exists in the repo to reuse, and append-only first-line-wins needs none.
- `request_stop(engagement_dir, source, reason, *, now)` — appends one JSON line
  `{timestamp, source, reason}`. `StopSource` ∈ {`operator`, `watchdog`, `budget`, `deadline`}.
  **Idempotent & first-wins:** the *first* line is authoritative for `(source, reason)`; every later
  appended line **is** the audit trail and never overrides the first (no separate named list). **This
  is the only function that sets a stop.** The file itself is the audit log (auditable by construction).
- `is_stopped(engagement_dir)` → `StopState | None` — reads the record: present/non-empty ⇒ stopped,
  returning the first line's `(source, reason)`. `raise_if_stopped(engagement_dir)` raises a new
  `Stopped(Exception)` (own module-scoped subclass — the repo has no shared `KronosError` base;
  researcher item 5) carrying `(source, reason)`.
- **One primitive, both processes.** The dispatcher (operator) and the watchdog both read/write this
  one file. `BudgetExceeded` is adapted at the dispatcher boundary into
  `request_stop(..., source="budget")` **preserving the original reason/event** (D1): the ledger keeps
  its own raise/`_stopped_reason` contract; the dispatcher translates it into the shared record rather
  than a second cancellation concept. **(F7)** This adaptation is at the dispatcher's **executor
  boundary** (`executor.execute`), the only in-scope site that charges budget; budget raised deeper
  (driver/reviewer) is out of this brief's dispatcher boundary.
- **No concurrency primitives.** Each process does single short appends, each **newline-terminated**;
  readers (`is_stopped`) read the first line and tolerate a concurrently-growing file, ignoring a
  torn/partial **trailing** line (F6). **Fail-closed on a torn FIRST line (N1):** if the file is
  non-empty but its first line is not yet a complete, parseable record, `is_stopped` returns
  **stopped** (per §4.1 "present/non-empty ⇒ stopped"), with `source="unknown"`,
  `reason="unparsable stop record"` — it must **never** return not-stopped for a non-empty file. A
  stop is a safety signal; ambiguity resolves to stopped, never lost. The repo is strictly sequential within a
  process (researcher: no threading/asyncio); cross-process coordination is the append-only file only.

### §4.2 Stop-check insertion points — proposed edits to `src/kronos/agent/dispatcher.py`

- **Before Phase 2 commit** (`dispatcher.py:127`, before `_commit`): `if is_stopped(engagement_dir): break`
  — a stopped step commits **no** `upsert_node`/`upsert_edge` (A2, stronger guarantee).
- **Before Phase 3 action-start** (`dispatcher.py:145`, before `executor.execute`):
  `if is_stopped(engagement_dir): break` — a stopped step executes nothing and writes **no
  evidence/promotion** state (A2, narrowed guarantee; this is the check the narrowed claim depends on).
- **`run()` MUST read `is_stopped(engagement_dir)` at the top of each step** (beside the existing
  `deadline` check, `:183`) and break **before** calling `_step`/`run_once` for that step — a pre-set
  stop must cause the planner/driver to be invoked **zero** times (not merely blocked inside the step).
  This is a THIRD stop-read, additional to the two phase-gate reads above; a mandatory acceptance test
  asserts zero driver calls after a pre-set stop. Deadline expiry calls `request_stop(source="deadline")`
  so the existing deadline folds into the one primitive. The dispatcher already receives
  `engagement_dir`, so **no new parameter plumbing** is needed.
- **(F8)** A persisted stop (`stop.jsonl`) is **durable by design** — once set it is not auto-cleared;
  a fresh engagement uses a fresh `engagement_dir`. `run_once` returning on a stop without raising
  `Stopped` is intentional (the stop is cooperative, not an exception-driven abort).
- **No new execution is wired** — only cancellation reads are added around the *existing* calls.

### §4.3 Cleanup-always (D4 — one dispatcher `try/finally`, runs exactly once)

Teardown must run on every exit path — normal completion, `BudgetExceeded`/budget stop, operator stop,
watchdog stop. Per D4, the **dispatcher owns one `try/finally` cleanup boundary** around its action
loop; the `finally` invokes teardown **exactly once** (a run-once guard, so nested/early returns cannot
double-fire it). Cleanup stays budget-decoupled (`cleanup/registry.py` already imports no budget;
researcher `:9-11`), so teardown completes even when budget is exhausted. The `finally` runs the
existing `CleanupRegistry.teardown_all()` once; no new teardown logic is introduced.

### §4.4 Independent watchdog — `src/kronos/watchdog.py` (new)

- A **read-only** consumer: given a path to an engagement's append-only `events.jsonl` and a verified
  verified **in-force `VerifiedManifest`** (from which it reads `.autonomy.watchdog`, a
  `WatchdogPolicy | None`; the caller selects it via `in_force_manifest(...)` per brief29 §8.1), it
  reads events and decides whether to request a stop. It does **not** take or need an
  `EffectiveEnvelope`, and `autonomy.py` is not touched. The policy is genuinely signed because
  `VerifiedManifest` is unforgeable (brief29 construction guard, `manifest.py` `load_and_verify`). It **never** writes graph, evidence, or events; its only effect is
  `request_stop(token, source="watchdog", reason=...)` on the shared token.
- **Signed-policy enforcement (D5 — persistent-condition grace):** if `watchdog is None` or
  `may_auto_stop is False`, the watchdog **never** auto-stops — it emits an **alert only**. If
  `may_auto_stop is True`, when its trigger condition first holds it starts the
  `confirm_window_seconds` grace period; at the end of the window it **re-checks the condition**, and
  auto-stops (`request_stop(source="watchdog")`) **only if the condition still persists**. A condition
  that clears within the window ⇒ stand down, no stop. The window uses an **injected clock** (`now()`
  callable) so tests are deterministic and hermetic — no real sleep, no wall-clock, no network. An
  operator stop during the window pre-empts via first-wins (§4.1).
- **Trigger source (D2/D3):** the watchdog observes the *existing* `events.jsonl` kinds only
  (ingest/reconcile; `events.py:42-50`). `events.py` is **not** modified and `ALLOWED_KINDS` is **not**
  extended in this brief (D3 deferred). New action/step event kinds are a later brief.

## §9 — Integration boundaries

- `stop.py` depends on nothing but `errors`/typing. `watchdog.py` depends on `stop`, `manifest`
  (`VerifiedManifest`/`WatchdogPolicy` types), and read-only file I/O over `events.jsonl`. It does
  **not** depend on `autonomy.EffectiveEnvelope`; `autonomy.py` is not modified.
- `dispatcher.py` gains an optional `token` parameter and the two checks; default behaviour
  (no token passed → fresh token, never stopped) is **unchanged** for all existing callers/tests.
- No change to `manifest.py`, `autonomy.py`, `events.py` emit contract, `budget/*`, scope rails,
  `.github/`, or `cybergym/`.

## §10 — Expected files to change (PROPOSED allowlist; binding on the future build only)

Brief file (committed to the branch, as SPEC_BRIEF29.md was):
- `SPEC_BRIEF30.md` — this brief.

New:
- `src/kronos/stop.py` — the shared stop primitive.
- `src/kronos/watchdog.py` — the independent read-only watchdog.
- `tests/test_stop.py` — primitive + insertion-point + cancellation + cleanup-always tests.
- `tests/test_watchdog.py` — watchdog read-only + signed-policy + confirm-window tests.

Modified (surgical):
- `src/kronos/agent/dispatcher.py` — two `is_stopped(engagement_dir)` reads (before Phase-2 commit,
  before Phase-3 action-start) + D1 `BudgetExceeded`→`request_stop(source="budget")` adaptation + D4
  one `try/finally` run-once cleanup boundary. Default (no `stop.jsonl`) behaviour unchanged.
- `tests/test_agent_dispatcher.py` — add stop-check coverage for the dispatcher.
- `src/kronos/__init__.py` — permitted only if `stop`/`watchdog` need exporting (confirm at build time).
- **Whole-window scope seal — `tests/test_autonomy.py` (seal only):** re-pin
  `test_B29_Q_scope_audit` upper bound from `..HEAD` to the brief29 merge (`..93fb05e`) so it stops at
  brief29's own window (`B29_BASE=55b4b7f`). This is the only edit to `test_autonomy.py`. The brief-30
  **own** whole-window audit (`B30_BASE=93fb05e..HEAD` ⊆ this §10 list) is a NEW test placed in
  `tests/test_stop.py`.

Explicitly **NOT** in scope: `src/kronos/manifest.py`, `src/kronos/autonomy.py`, `src/kronos/events.py`,
`.claude/`, `.github/`, `cybergym/`. (§16 D3 could add `events.py` to this list **only** on an explicit
operator decision to extend `ALLOWED_KINDS`.)

## §11 — Explicit non-goals

- No autonomous action execution wiring; no live targets; no §6 run; no providers; no network.
- No concurrency/threads/async. No new event kinds (unless D3 approved). No real sleeping/wall-clock in
  tests. No change to the SPEC_BRIEF29 schema or evaluator. N1/N2 remain backlog (not addressed here).

## §12 — Acceptance criteria (tests-as-rules; expected values from this brief's prose, not observed behavior)

- **C1 — single stop entry.** `request_stop` is the only setter of a stop; a structural test asserts no
  other `def stop`/`cancel`/`kill`/`abort`/`halt`/`shutdown` is introduced under `src/kronos` by this
  change (grep over the whole-window diff). (A5)
- **C2 — idempotent, first-wins, auditable.** Two `request_stop` calls on the same `engagement_dir`:
  `is_stopped` reports stopped with the **first** caller's `(source, reason)`; the second line is
  appended to `stop.jsonl` as audit, never overriding. (A1)
- **C2b — cross-process.** `request_stop` from one handle and `is_stopped` from a **separate** handle
  over the same `engagement_dir` (two independent in-test instances, no shared memory) observe the same
  stop — proving the primitive is filesystem-backed, not in-memory. (P0-1)
- **C3 — stop before commit ⇒ no state.** With `stop.jsonl` present before Phase 2, `run_once` performs
  **zero** `upsert_node`/`upsert_edge` (asserted by node/edge **counts** unchanged pre/post — not a
  byte-identical Kùzu-DB claim). (A2 strong)
- **C4 — stop before action ⇒ no evidence/promotion.** With the stop present before Phase 3,
  `executor.execute` is not called, no `EVIDENCE` node/`evidences` edge written, no finding status
  advanced. (A1/A2 narrowed)
- **C4b — stop between commit and action (the race; P0-2).** Stop arrives after Phase-2 `_commit` but
  before Phase-3 start: assert the already-committed `FINDING` node exists at status `"hypothesis"`
  (decision record) **and** that **no** `EVIDENCE` node, `evidences` edge, or `hypothesis→reachable`
  transition occurs. A paired control asserts the **same** end-state arises today from an ordinary
  `executor.execute` failure (no stop) — proving the brief relies on existing accepted behavior, not a
  new hazard. The test docstring names the later prerequisite (atomic commit+execute / graph rollback,
  absent today). (A2)
- **C5 — cleanup runs exactly once.** Parametrized over {normal end, `BudgetExceeded`, operator stop,
  watchdog stop}: the dispatcher `try/finally` runs teardown **exactly once** on every path (run-once
  guard asserted — never zero, never twice). (A3, D4)
- **C5b — budget stop preserves reason.** `BudgetExceeded` on a charge ⇒ a `stop.jsonl` record with
  `source="budget"` whose `reason` preserves the ledger's `_stopped_reason`/original event. (D1)
- **C6 — watchdog read-only.** Watchdog run attaches the `nonet` fixture and asserts: no graph write,
  no evidence write, no `events.jsonl` write, network unused. Its sole state effect on auto-stop is a
  `stop.jsonl` line with `source="watchdog"`. (A6)
- **C7 — unsigned/absent policy ⇒ alert only.** `watchdog is None` or `may_auto_stop is False`:
  the watchdog **never** writes a stop under any observed events (alert-only). (A4)
- **C8 — persistent-condition grace window (D5).** `may_auto_stop is True`, injected clock: no stop
  before `confirm_window_seconds` elapses; at window end, stop **iff the condition still persists**; a
  condition that clears within the window ⇒ **no** stop (stand down); an operator stop during the
  window pre-empts (first-wins). Boundary cells (window−1, window, window+1, and cleared-mid-window)
  derive from §4.4 prose and the `manifest.py` validator (`1 <= confirm_window_seconds <= 300`). (A4)
- **C9 — default unchanged.** `run()`/`run_once` with no `stop.jsonl` present behave exactly as
  pre-brief for every existing dispatcher test. (regression)
- **C10 — hermetic.** Every new/changed test uses `nonet`; no network, no live target, no §6.

## §13 — Test plan (unit · integration · property · adversarial · regression)

- **Unit:** `StopToken`/`request_stop`/`is_stopped`/`raise_if_stopped` (C1/C2); watchdog policy gate
  (C7), confirm-window boundary cells with injected clock (C8).
- **Integration:** `run_once`/`run` with a token across the two insertion points (C3/C4); cleanup-always
  parametrized (C5); default-unchanged regression over existing dispatcher tests (C9).
- **Adversarial:** forged/absent policy (C7); attempt a second kill path (C1 structural); watchdog
  write attempt is absent by construction (C6).
- **Property:** idempotence of `request_stop` over arbitrary call sequences (first-wins invariant).
- **Hermetic:** `nonet` everywhere (C10).

## §14 — Migration risks

- Adding a `token` param to `dispatcher.run`/`run_once` must default to a fresh token so all existing
  callers compile and behave identically (C9 guards this).
- Wrapping the dispatcher in `CleanupRegistry` (D4) must not change ordering of existing writes on the
  normal path — covered by C9.

## §15 — Rollback strategy

Two new modules + a surgical, default-preserving dispatcher change. Rollback = revert the brief-30
commits; no schema/data migration, nothing persisted, no external effect.

## §16 — Operator decisions (RESOLVED; context.md 2026-11-01)

All five are decided; no open PAUSE-DECISION remains.

- **D1 — RESOLVED:** budget exhaustion calls idempotent `request_stop(source="budget")` preserving the
  original `BudgetExceeded` reason/event (§4.1, C5b).
- **D2 — RESOLVED:** watchdog observes existing event kinds only (§4.4).
- **D3 — RESOLVED:** defer `events.py` changes; `ALLOWED_KINDS` unchanged; `events.py` stays out of
  the allowlist.
- **D4 — RESOLVED:** the dispatcher owns one `try/finally` cleanup boundary; cleanup runs exactly once
  (§4.3, C5).
- **D5 — RESOLVED:** `confirm_window_seconds` is a persistent-condition grace period, then auto-stop
  iff `may_auto_stop`, else alert-only (§4.4, C8).

**P0-1 (RESOLVED, §4.1):** the primitive is filesystem-backed (`<engagement_dir>/stop.jsonl`,
append-only, first-wins, auditable), cross-process by construction — within the existing allowlist
(new data file, no new code file). **P0-2 (RESOLVED, §3 A2 / §4.2 / C4b):** the "no graph/evidence
state" claim is narrowed to evidence/promotion writes; the Phase-2 hypothesis FINDING is a decision
record (identical to today's executor-failure case); the later prerequisite (atomic commit+execute or
graph rollback) is named and left out of scope.

## Deliverable summary

Two hermetic modules (`stop.py` filesystem-backed cross-process primitive, `watchdog.py` read-only),
a surgical default-preserving dispatcher change (two stop-reads + one `try/finally`), and two+ test
files proving C1–C10 (incl. C2b cross-process, C4b race, C5b budget-reason, C8 persistent grace). No
implementation performed; **no builder dispatched** (context.md "No builder dispatch yet").

**Recommended GATE-1 status: PASS — ready to self-approve, builder held by operator instruction.**
D1–D5 are resolved and both P0 are resolved **within the existing §10 allowlist** — no new files
(`stop.jsonl` is engagement data, not a code path), no architecture delta beyond a filesystem-backed
primitive, no scope expansion, `events.py`/`manifest.py`/`autonomy.py` untouched. The brief states in
full every scope item, permitted file, behavior, negative case, acceptance criterion, and the one
named out-of-scope prerequisite. Opus's recommendation is that routine GATE-1 may be self-approved on
this rev2; per the operator's standing "No builder dispatch yet," the loop pauses after GATE-1 for the
operator's go-ahead to dispatch the Sonnet 5.5 builder.
