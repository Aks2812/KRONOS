# SPEC_BRIEF21 S8.4 Agent layer — Increment 4 (observability: run-level RunSummary; hermetic, no live execution)

**Stage:** S8 agent layer. `KRONOS_RESEARCH_RECORD.md` §8 increment ladder: *"4+ loop-breaker,
conclude-on-timeout, observability."* The loop-breaker + conclude-on-timeout rung shipped in
SPEC_BRIEF20 (merged main `5803bcd`, PR #28). This brief is **the observability rung** — and
**only** run-level observability of the dispatcher loop. Maintainer-authorized (PROGRESS.md SEQ 119);
form **A (run-level summary struct)** chosen by the maintainer at the SEQ 120 PAUSE-DECISION over
form B (events.py emission). CyberGym only; **no live targets, no live execution, zero network**; the
executor stays mock, exactly as Increments 1-3.

## §1 — Problem

`src/kronos/agent/dispatcher.py` `run` (lines 92-116) returns a bare `list[DispatcherResult]` with no
run-level aggregate. A caller wanting to observe what a run did must reconstruct every run-level fact
from the per-step list itself:

- **No total step count.** Each `DispatcherResult.steps` is a per-call constant (`1` from `run_once`,
  `0` on the synthetic timeout result, line 109); nothing sums them.
- **No single conclusion reason.** `run` has three distinct exits — the deadline break (lines
  107-111), the `complete` break (lines 114-115), and falling out of the `for` after `max_steps` —
  but no field distinguishes "exhausted `max_steps`" from the other non-complete ends. The caller
  must inspect `res[-1].complete`, `res[-1].timed_out`, and `len(res)` together.
- **No aggregate committed/promoted.** `committed`/`promoted` are reset per `run_once` call; the run's
  totals are left for the caller to concatenate.

`test_N_conclude_on_timeout` already reconstructs run-level facts manually (`len(res) < 50`,
`not any(r.timed_out for r in res[:-1])`) — direct evidence the aggregate is missing.

## §2 — Approach

Add a **pure, additive, hermetic** run-level summary, realised exactly as the existing
`kronos.agent.planner.summarize(engagement) -> GraphSummary` precedent (`planner.py:13-27`): a frozen
summary dataclass plus a free function that derives it. **`run` and `run_once` are not changed** —
their return types, signatures, and bodies stay byte-identical, so every existing contract
(`test_N`, `test_J_termination`, `test_K_no_network`, frozen `test_L`/`test_M`) is preserved.

- Add a frozen `RunSummary` dataclass to `dispatcher.py`:
  - `results: tuple[DispatcherResult, ...]` — the wrapped per-step results.
  - `total_steps: int` — sum of each result's `steps`.
  - `conclusion: str` — one of `"complete"`, `"timed_out"`, `"max_steps"`.
  - `committed: tuple[str, ...]` — all per-step `committed` ids, concatenated in list order.
  - `promoted: tuple[str, ...]` — all per-step `promoted` ids, concatenated in list order.
- Add `summarize_run(results: list[DispatcherResult]) -> RunSummary` to `dispatcher.py`:
  - `total_steps = sum(r.steps for r in results)`.
  - `conclusion` from the **last** result, with this fixed precedence (derived from the three `run`
    exits): if `results[-1].timed_out` → `"timed_out"`; elif `results[-1].complete` → `"complete"`;
    else → `"max_steps"`.
  - `committed = tuple(c for r in results for c in r.committed)`;
    `promoted = tuple(p for r in results for p in r.promoted)`.
  - `results = tuple(results)`.
  - It operates on the non-empty list `run` returns (`max_steps >= 1` guarantees ≥1 element). Empty
    input is not a supported case and gets no special handling.
- Export `RunSummary` and `summarize_run` from `src/kronos/agent/__init__.py`, exactly as
  `GraphSummary`/`summarize` are exported today.

No new module, no live execution, no network, no change to the promotion chokepoints.

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only 5803bcd..HEAD` ⊆ set)

1. `SPEC_BRIEF21.md`
2. `src/kronos/agent/dispatcher.py` (edit: add `RunSummary` dataclass + `summarize_run` function; do **not** touch `run`/`run_once`/`DispatcherResult`/`_commit`)
3. `src/kronos/agent/__init__.py` (edit: import + `__all__` entries for `RunSummary`, `summarize_run`)
4. `tests/test_agent_dispatcher.py` (edit: add §8-O `test_O_run_summary`)

Base = `origin/main` @ `5803bcd`. Never `git add -A`; stage explicit paths only.
Do **NOT** edit `run`, `run_once`, `DispatcherResult`, `executor.py`, `drivers.py`, `planner.py`,
`reviewer.py`, `contracts.py`, `schema.py`, `scope_guard.py`, `manifest.py`, `.github/`, or anything
under `cybergym/`. Build fixtures with existing helpers READ-ONLY. The existing `test_L`/`test_M`
frozen scope audits (brief-16 window `81796b4..f4559a2`) must stay untouched and green.

## §8 — Acceptance criteria (tests-as-rules; `tests/test_agent_dispatcher.py`)

Decide PASS/FAIL from pytest's `SUMMARY:` line, never `$?` (CLAUDE.md §3). Expected values derive
from this brief's prose, not observed behaviour, and each assertion traces to a §2 clause.

O. **Run-level summary (`summarize_run` / `RunSummary`)** — in a new `test_O_run_summary`:
   - **Conclusion = complete:** a `RunSummary` from a results list whose last element has
     `complete is True, timed_out is False` has `conclusion == "complete"`.
   - **Conclusion = timed_out:** a results list whose last element has `timed_out is True` has
     `conclusion == "timed_out"` (timeout precedence over `complete`).
   - **Conclusion = max_steps:** a results list whose last element has
     `complete is False, timed_out is False` has `conclusion == "max_steps"`.
   - **total_steps:** equals the arithmetic sum of each result's `steps` (construct results with
     distinct `steps` values and assert the exact sum; include a `steps=0` timeout result).
   - **Aggregates:** `committed` and `promoted` equal the in-order concatenation of the per-step
     tuples (construct results carrying distinct `committed`/`promoted` ids and assert exact order).
   - **results wrap:** `RunSummary.results == tuple(input_list)`.
   - **Frozen:** `RunSummary` is a frozen dataclass — assigning to a field raises
     `dataclasses.FrozenInstanceError`.
   - **Composition:** one assertion drives `summarize_run(run(...))` end-to-end with a `MockDriver`
     that returns `{"complete": True}`, showing `conclusion == "complete"` and
     `total_steps == sum(r.steps for r in that run's results)` — hermetic, no network, no live
     execution.
   - Expected `conclusion` values derive from §2's fixed precedence clause, not from observed output.

J/N-regression. **run/run_once unchanged** — `test_J_termination` and `test_N_conclude_on_timeout`
   still pass unchanged (`run` still returns a `list[DispatcherResult]`; this brief adds no parameter
   and changes no return type).

K-regression. **No network** — `test_K_no_network` still passes; `summarize_run` is pure and opens
   no socket.

F. **Scope audit (whole window)** — `git diff --name-only 5803bcd..HEAD` ⊆ the §3 set (verified at
   review). `test_L`/`test_M` frozen audits untouched.

G. **Suite green** — full `pytest` reports `0 failed` on the final commit (totals refreshed as the
   last edit).

## §9 — Done when

All of §8 holds, the whole-window scope audit is clean, the change is additive-only (one new frozen
dataclass, one new pure function, two `__init__` export lines, one new test — no new module, no live
execution, no network, no edit to `run`/`run_once`/`DispatcherResult`), the Increment 1-3 promotion
chokepoints and frozen scope audits are untouched, and the full suite is green on the head commit.
