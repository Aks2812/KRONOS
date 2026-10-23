# SPEC_BRIEF16 S8.1 Agent layer — Increment 1 (dispatcher skeleton + read-only planner, zero side effects)
**Stage:** S8 (research record §6 ladder / §8 "Agent layer design" — Increments 1–3). This brief is
**Increment 1 only**.
**Goal:** G2 (plan across the five built domains without the LLM ever being able to write the graph,
spend budget, or touch scope). Increment 1 proves the orchestration *shape* is deterministic and
side-effect-free before any writer or executor exists.
**Depends on:** the existing EngagementGraph (`graph.py`), read-only query surface (`query.py`),
and the FINDING/SECRET statuses (`lifecycle.py`). Reads only; writes nothing.
**Authorization:** maintainer `/home/void/context.md` (2026-10-23) — "Authorize A: begin S8 as the
next KRONOS milestone … Start S8 with a bounded research and architecture-definition phase … then
continue the established autonomous … workflow within that approved direction", recorded at
checkpoint SEQ 95. GATE-1 self-approved by Opus after validating this brief against the researcher's
cited findings and the research record §8 design. **CyberGym only. NO live-target testing. NO live
network. No scope expansion. No schema or graph-write in this increment.**

## §1 — Problem
The research record §8 pins the agent layer: a single deterministic **dispatcher loop** is the sole
graph-writer; a read-only **planner** (`reason`) and an **executor** (`explore`) are structured-output
proposers; `scope_guard`/lifecycle/budget/cleanup are hard rails the LLM can never override; strict
JSON contracts plus a **mock driver** give deterministic, zero-model-cost tests (RR.md:1649-1665).
The increment ladder (RR.md:1663) builds this safely: **Increment 1 = dispatcher skeleton + read-only
planner, zero side effects, strict contracts, mock driver.** Increments 2 (reviewer + rails as commit
gate) and 3 (executor behind the gate) are **out of scope here**.

Nothing of this exists yet (`git ls-tree origin/main src/kronos/` has no `agent/`). Increment 1
delivers the orchestration skeleton and the contract boundary with the invariant that a dispatcher
run performs **zero side effects**: the planner is read-only, and the dispatcher — though it is
*defined* as the sole future writer — writes nothing in this increment. Writes arrive in Increment 2
behind the reviewer/rails commit gate; execution in Increment 3.

Researcher findings this rests on (see `02-research/findings.md`, SEQ 95): FINDING creation today
always funnels through `upsert_node` + `upsert_edge` + the lifecycle chokepoint (`web_validator.py:44`,
`infra_validator.py:43`, `invalidation.py:17`); `schema.py:101-135 EDGE_PAIRS` is a closed typed set;
`NODE_PROPS_FORBIDDEN` (`schema.py:212`) names `confidence`/`in_scope`/`merged_into`. The §4.8 Cairn
"control plane sole writer" decision (RR.md:784-791) requires a hostile proposal that tries to set
`status`/`in_scope`/`confidence` to be **rejected at the contract boundary** — the agent-layer analogue
of the existing C1 hostile-input test.

## §2 — Approach
New package `src/kronos/agent/` — five new source files, zero edits to any existing source module.
No new graph node type, no new edge label, **no `schema.py` / `scope_guard.py` / `lifecycle.py`
change** (Increment 1 writes nothing to the graph, so no node-type shape row is needed).

**(a) `src/kronos/agent/contracts.py` (NEW) — strict structured-output contract.**
The planner's raw output is an untrusted `dict` (in real use, LLM-authored; here, mock-authored).
- `MAX_INTENTS = 4` (module constant; the intent-count cap, RR.md:801).
- Frozen result types: `Intent` (frozen dataclass: `kind: str`, `target_id: str`, `rationale: str`)
  and `ReasonResult` (frozen: `complete: bool`, `intents: tuple[Intent, ...]`).
- `FORBIDDEN_FIELDS = frozenset({"status", "in_scope", "confidence", "merged_into"})` — authoritative
  fields the proposer may never set (RR.md:787-791; mirrors `NODE_PROPS_FORBIDDEN`).
- `class ContractViolation(ValueError)`.
- `validate_reason_payload(payload: dict) -> ReasonResult` — pure; raises `ContractViolation` when:
  (i) `payload` is not a dict; (ii) **both** `complete` truthy **and** a non-empty `intents` present
  ("complete and intents cannot coexist", RR.md:800); (iii) **neither** a truthy `complete` nor any
  intent is present; (iv) `len(intents) > MAX_INTENTS`; (v) any intent is not a dict or is missing
  any of `kind`/`target_id`/`rationale`, or has a non-str value for them; (vi) **any** key in
  `FORBIDDEN_FIELDS` appears anywhere in the payload top level **or** in any intent dict (the
  hostile-output rejection). On success returns a `ReasonResult`; when `complete` is truthy the
  `intents` tuple is empty. The function performs no I/O and no graph access.

**(b) `src/kronos/agent/drivers.py` (NEW) — driver boundary + mock.**
- `class Driver(typing.Protocol)`: `def reason(self, summary: "GraphSummary") -> dict: ...` — the only
  surface through which a model (later) is consulted. Returns a raw, unvalidated payload.
- `class MockDriver`: constructed with `scripted: Sequence[dict]`; each `reason()` call pops and
  returns the next scripted payload (raises `IndexError`/`StopIteration`-style `ContractViolation`-free
  `RuntimeError("mock driver exhausted")` if over-consumed). **Zero LLM, zero network, deterministic.**
  This is the single highest-leverage testing device (RR.md:804-807): the whole loop is exercised at
  zero model cost.

**(c) `src/kronos/agent/planner.py` (NEW) — read-only planner (`reason`).**
- `@dataclass(frozen=True) class GraphSummary`: a read-only projection derived *from the graph*
  (RR.md:703-704, summarise from graph not transcript). Minimal fields for Increment 1:
  `finding_count: int`, `secret_count: int`, `findings_by_status: tuple[tuple[str, int], ...]`.
- `def summarize(engagement) -> GraphSummary`: reads the engagement via the existing read-only query
  surface only (counts); performs **no** write of any kind. If the project exposes a counts/query
  helper use it read-only; otherwise count via a read-only `MATCH … RETURN count(...)` query. Must not
  call `upsert_*`, `advance_*`, `charge`, or any writer.
- `def plan(summary: GraphSummary, driver: Driver) -> ReasonResult`: calls `driver.reason(summary)`,
  passes the raw payload through `validate_reason_payload`, returns the validated `ReasonResult`.
  The planner **never writes the graph** — it only reads (via `summarize`, called by the dispatcher)
  and proposes.

**(d) `src/kronos/agent/dispatcher.py` (NEW) — deterministic loop skeleton, sole writer, zero writes.**
- `@dataclass(frozen=True) class DispatcherResult`: `complete: bool`, `proposed_intents:
  tuple[Intent, ...]`, `steps: int`. Records the decision; it is **not** a graph write.
- `def run_once(engagement, driver: Driver) -> DispatcherResult`: `summary = summarize(engagement)`
  (read-only) → `result = plan(summary, driver)` → return a `DispatcherResult` reflecting `result`.
  Performs **zero side effects**: no `upsert_node`/`upsert_edge`/`advance_*`/budget charge/cleanup
  registration. (The dispatcher is *defined* as the sole future graph-writer — Increment 2 adds the
  reviewer/rails commit gate before any write — but in Increment 1 it writes nothing.)
- `def run(engagement, driver: Driver, *, max_steps: int) -> list[DispatcherResult]`: the loop
  skeleton. Repeatedly `run_once`, appending each result, stopping when a result is `complete` **or**
  `max_steps` is reached (`max_steps >= 1`; guard rejects `< 1` with `ValueError`). Returns the list.
  Still zero graph writes at every step. This is the single in-loop skeleton (RR.md:1659-1661) — no
  sub-agent pool, no second loop.

**(e) `src/kronos/agent/__init__.py` (NEW)** — export `validate_reason_payload`, `ReasonResult`,
`Intent`, `ContractViolation`, `MAX_INTENTS`, `FORBIDDEN_FIELDS`, `Driver`, `MockDriver`,
`GraphSummary`, `summarize`, `plan`, `DispatcherResult`, `run_once`, `run`. Set `__all__`.

No new dependency. No `events.py` change (no new event kind this increment). No network in any module
(mock driver only; tests assert sockets unused and no traffic outside the CyberGym range). No edit to
`schema.py`, `scope_guard.py`, `lifecycle.py`, `runner.py`, any `validate/*`, `reconcile/*`, `graph.py`
(read-only use only), `manifest.py`, `.github/`, or `cybergym/`.

## §2a — Seal the brief-15 scope-audit (cross-brief landmine, per SEQ 72)
`tests/test_invalidation.py` (brief 15, now on `origin/main`) still runs its whole-window audit against
**`HEAD`**: `BRIEF_BASE = "17d38a8"` (`test_invalidation.py:29`) and
`["git","diff","--name-only", f"{BRIEF_BASE}..HEAD"]` (`:227`). On this S8 branch `HEAD` includes the
Increment-1 files, so that audit would fail. Seal it to brief-15's merged footprint, **seal-only**
(no other change to that file):
- add `BRIEF_MERGE = "81796b4"  # brief 15 merged to main (PR #23 squash); seals this audit to brief 15's footprint`
  (beside the existing `BRIEF_BASE`);
- change the diff range `f"{BRIEF_BASE}..HEAD"` → `f"{BRIEF_BASE}..{BRIEF_MERGE}"`.

(`17d38a8..81796b4` is exactly brief-15's merged paths.) `test_invalidation.py:234-235` already assert
the brief-14 seal on `test_web_validator.py` (an unrelated file) — do **not** touch those lines or any
other assertion. Change only the two spots named above.

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only 81796b4..HEAD` ⊆ set)
1. `SPEC_BRIEF16.md`
2. `src/kronos/agent/__init__.py` (new)
3. `src/kronos/agent/contracts.py` (new)
4. `src/kronos/agent/drivers.py` (new)
5. `src/kronos/agent/planner.py` (new)
6. `src/kronos/agent/dispatcher.py` (new)
7. `tests/test_agent_contracts.py` (new)
8. `tests/test_agent_dispatcher.py` (new)
9. `tests/test_invalidation.py` (edit: §2a brief-15 seal ONLY — two spots)

Base = `origin/main` @ `81796b4`. Never `git add -A`; stage explicit paths only.
Do **NOT** edit `schema.py`, `scope_guard.py`, `lifecycle.py`, `runner.py`, `events.py`, `graph.py`,
`evidence.py`, `query.py`, any other `validate/*` or `reconcile/*`, `manifest.py`, `.github/`, or
anything under `cybergym/`. Build the test graph with existing helpers/fixtures READ-ONLY.

## §8 — Acceptance criteria (tests-as-rules)
Decide PASS/FAIL from pytest's `SUMMARY:` line, never `$?` (CLAUDE.md §3). Expected values derive from
this brief's prose, not from observed behaviour. Contract tests live in `tests/test_agent_contracts.py`;
orchestration/invariant tests in `tests/test_agent_dispatcher.py`.

A. **Valid `complete` payload** — `validate_reason_payload({"complete": True})` returns a `ReasonResult`
   with `complete is True` and `intents == ()`.
B. **Valid `intents` payload** — a payload with 1..`MAX_INTENTS` well-formed intents (each with
   `kind`/`target_id`/`rationale` strings) returns `complete is False` and a tuple of `Intent` of the
   same length, order preserved.
C. **Mutual-exclusion** — a payload with both truthy `complete` and a non-empty `intents` raises
   `ContractViolation`; a payload with neither raises `ContractViolation`.
D. **Intent cap** — a payload with `MAX_INTENTS + 1` intents raises `ContractViolation`; exactly
   `MAX_INTENTS` is accepted.
E. **Malformed intent** — an intent missing any of `kind`/`target_id`/`rationale`, or with a non-str
   value, or not a dict, raises `ContractViolation`.
F. **Hostile-output rejection** — a payload setting any `FORBIDDEN_FIELDS` member
   (`status`/`in_scope`/`confidence`/`merged_into`) at the top level **or inside any intent** raises
   `ContractViolation`. `FORBIDDEN_FIELDS` equals `{"status","in_scope","confidence","merged_into"}`.
G. **Mock driver determinism** — `MockDriver([p1, p2])` returns `p1` then `p2` on successive `reason()`
   calls, with no network and no LLM; over-consumption raises `RuntimeError`.
H. **Read-only planner** — given an engagement with known findings/secrets, `summarize(engagement)`
   returns a `GraphSummary` whose counts match the graph, and the engagement's node and edge counts are
   **identical before and after** the call (planner reads, never writes).
I. **Mock-driven end-to-end, zero side effects (the Increment-1 invariant)** — building an engagement,
   recording its node+edge counts, then `run(engagement, MockDriver([...,{"complete": True}]),
   max_steps=K)` returns a list whose last result has `complete is True`, and the engagement's node and
   edge counts are **unchanged** (byte-for-byte count equality) — the dispatcher wrote nothing. Zero LLM
   calls occur (asserted via the mock).
J. **Loop termination** — `run` stops at the first `complete` result (list length == index of first
   complete + 1); with a driver that never returns `complete`, `run(..., max_steps=N)` returns exactly
   `N` results; `max_steps < 1` raises `ValueError`.
K. **No live network** — monkeypatch both `socket.socket` and `socket.create_connection` to raise; the
   full `run` (summarize + plan + loop) still completes and asserts no socket was used. Assert no traffic
   outside the CyberGym range.
L. **Scope audit (whole window)** — `git diff --name-only 81796b4..HEAD` ⊆ the §3 set (audit the whole
   window, not just expected files). This test defines `BRIEF_BASE = "81796b4"` and uses
   `f"{BRIEF_BASE}..HEAD"`.
M. **Brief-15 seal** — `tests/test_invalidation.py` contains `BRIEF_MERGE = "81796b4"`, uses
   `f"{BRIEF_BASE}..{BRIEF_MERGE}"`, and no longer contains `f"{BRIEF_BASE}..HEAD"` (the §2a seal landed,
   seal-only).
N. **No writer imported in planner/contracts** — `contracts.py` and `planner.py` source never call
   `upsert_node`/`upsert_edge`/`advance_secret_status`/`advance_finding_status`/`charge`; the dispatcher
   module performs no such call either (structural/source assertion backing the zero-side-effect claim).

## §9 — Done when
A–N pass under the project suite with 0 failed (totals refreshed as the final edit, after the last
suite run, per CLAUDE.md §4), the whole-window scope audit holds, the change is purely additive (one
new `src/kronos/agent/` package of five modules + two new test files, plus the brief-15 seal), the
dispatcher run performs zero graph side effects, and no existing source module is edited. CyberGym-only,
hermetic, no live targets, no live network.
