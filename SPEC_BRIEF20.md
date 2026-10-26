# SPEC_BRIEF20 S8.4 Agent layer — Increment 4 (loop-breaker + conclude-on-timeout; hermetic/mock, no live execution)

**Stage:** S8 agent layer. `KRONOS_RESEARCH_RECORD.md` §8 increment ladder: *"4+ loop-breaker,
conclude-on-timeout, observability."* This brief is **the first rung of Increment 4 only** —
loop-breaker + conclude-on-timeout. Observability is a later rung and is **out of scope here**.
Maintainer-authorized option A (PROGRESS.md SEQ 114). CyberGym only; **no live targets, no live
execution, zero network**; the executor stays mock, exactly as Increments 1-3.

## §1 — Problem

`src/kronos/agent/dispatcher.py` `run` (lines 85-102) bounds the loop only by a caller-supplied
`max_steps` iteration cap, breaking early when the planner returns `complete`. There is **no
time-based loop-breaker**: a doomed task that never returns `complete` runs until `max_steps` is
exhausted. `KRONOS_RESEARCH_RECORD.md` §8 records the gap — the budget ledger caps *total* spend
but cannot stop one doomed task consuming it — and prescribes **conclude-on-timeout**, which per
the same section *"yields hypotheses only"* (the timed-out conclusion promotes nothing).

## §2 — Approach

Add a deterministic, hermetic conclude-on-timeout loop-breaker to `run`, leaving `run_once` and the
Increment 1-3 promotion chokepoints untouched.

- Add a `timed_out: bool = False` field to `DispatcherResult` (new field, default `False` — existing
  constructions and callers are unaffected).
- `run` gains two keyword-only parameters:
  - `deadline: float | None = None` — maximum elapsed seconds; `None` keeps today's behaviour
    exactly. `deadline <= 0` raises `ValueError`.
  - `clock: Callable[[], float] | None = None` — an injectable monotonic time source for
    deterministic tests; defaults to `time.monotonic`. No real sleeping, no wall-clock dependence in
    tests.
- Loop-breaker: at the **top of each iteration**, if `deadline is not None` and
  `clock() - start >= deadline`, `run` concludes on timeout — it appends one terminal
  `DispatcherResult(complete=False, proposed_intents=(), steps=0, committed=(), promoted=(),
  timed_out=True)` and breaks **without** calling `run_once` that step. This realises *"hypotheses
  only"*: the timeout step plans nothing, commits nothing, and promotes nothing; findings committed
  by earlier steps keep whatever status they already had.
- The `complete` early-break and the `max_steps` cap are unchanged; `timed_out` is `False` on every
  result of a run that finishes by `complete` or by exhausting `max_steps`.

No new module, no new public export (both `run` and `DispatcherResult` are already exported); only a
`time` import and the `Callable` type are added.

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only 5cf93c9..HEAD` ⊆ set)

1. `SPEC_BRIEF20.md`
2. `src/kronos/agent/dispatcher.py` (edit: `timed_out` field; `deadline`/`clock` params; conclude-on-timeout loop-breaker)
3. `tests/test_agent_dispatcher.py` (edit: add §8-N conclude-on-timeout test)

Base = `origin/main` @ `5cf93c9`. Never `git add -A`; stage explicit paths only.
Do **NOT** edit `run_once`'s body promotion path, `executor.py`, `drivers.py`, `planner.py`,
`reviewer.py`, `contracts.py`, `__init__.py`, `schema.py`, `scope_guard.py`, `manifest.py`,
`.github/`, or anything under `cybergym/`. Build fixtures with existing helpers READ-ONLY. The
existing `test_L`/`test_M` frozen scope audits (brief-16 window `81796b4..f4559a2`) must stay
untouched and green.

## §8 — Acceptance criteria (tests-as-rules; `tests/test_agent_dispatcher.py`)

Decide PASS/FAIL from pytest's `SUMMARY:` line, never `$?` (CLAUDE.md §3). Expected values derive
from this brief's prose, not observed behaviour.

N. **Conclude-on-timeout (loop-breaker, hypotheses only)** — in a new `test_N_conclude_on_timeout`:
   - **Timeout fires:** with a `MockDriver` that never returns `complete`, a `deadline`, and an
     injected fake `clock` that advances past the deadline, `run(..., max_steps=<large>,
     deadline=d, clock=fake)` returns a result list whose **last** element has `timed_out is True`
     and `complete is False`, and that terminal element has `committed == ()` and `promoted == ()`
     (hypotheses only — the timeout step promotes nothing). The run stops before `max_steps` is
     exhausted (`len(results) < max_steps`).
   - **No premature timeout:** a `MockDriver` that returns `{"complete": True}` before the fake
     clock reaches the deadline yields a last result with `complete is True` and `timed_out is
     False`; no terminal timeout element is appended.
   - **Backward compatibility:** `run(...)` with `deadline=None` (default) behaves exactly as today
     — every result has `timed_out is False`, and termination is by `complete` or `max_steps`
     (this preserves the existing `test_J_termination` contract).
   - **Validation:** `deadline <= 0` raises `ValueError`.
   - **Hermetic:** the test injects `clock`; it does not sleep, read wall-clock time, or use the
     network.

K-regression. **No network** — the existing `test_K_no_network` still passes; the timeout path adds
   no socket or live-target traffic.

F. **Scope audit (whole window)** — `git diff --name-only 5cf93c9..HEAD` ⊆ the §3 set (verified at
   review).

G. **Suite green** — full `pytest` reports `0 failed` on the final commit (totals refreshed as the
   last edit).

## §9 — Done when

All of §8 holds, the whole-window scope audit is clean, the change is additive-only (one new field,
two new keyword params, one new test — no new module, no live execution, no network), the Increment
1-3 promotion chokepoints and frozen scope audits are untouched, and the full suite is green on the
head commit.
