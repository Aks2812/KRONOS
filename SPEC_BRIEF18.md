# SPEC_BRIEF18 S8.3 Agent layer — Increment 3 (executor behind the gate, promotion to reachable; hermetic/mock, no live execution)
**Stage:** S8 (research record §6 ladder / §8 "Agent layer design"). This brief is **Increment 3 only**.
**Goal:** G2 + G3 (a reviewer-approved, committed proposal is *executed* behind the gate to produce
evidence that promotes its FINDING from `hypothesis` to `reachable` — and a FINDING only ever becomes
`reachable` when execution evidence is attached, so a promoted finding is always evidence-backed).
**Depends on:** Increment 2 (`src/kronos/agent/reviewer.py` + the two-phase commit gate in
`dispatcher.py`, merged PR #25 @ `a9f37ec`), and the existing `evidence.attach_evidence` +
`lifecycle.advance_finding_status` chokepoints (reused call-only).
**Authorization:** maintainer `/home/void/context.md` (2026-10-23) — S8 Increments 1–3, recorded at SEQ 95;
Increment 3 named autonomous next step at SEQ 104/105. GATE-1 self-approved by Opus after validating this
brief against the researcher's cited findings (`02-research/findings.md`, SEQ 105). **CyberGym only. NO
live-target testing. NO live network in this increment. No scope expansion. No schema/scope_guard/lifecycle
/evidence/graph change.**

**Security-scope boundary (binding).** This increment delivers the executor **abstraction** (`Executor`
protocol) and a **`MockExecutor`**, wired behind the existing gate, tested **hermetically** (no live
network; sockets patched). It does **not** build a concrete live executor and does **not** run against any
target. An actual live CyberGym execution run is a **separate event** that, per CLAUDE.md §4 / the
loop-contract §6, requires current written authorization naming the target, the action, and the time
window — it is explicitly **out of scope here** and is **not** performed.

## §1 — Problem
Increment 2 lets the dispatcher commit a reviewer-approved proposal as a FINDING at `hypothesis` but
executes nothing, so no proposal can ever be shown real. Increment 3 adds the **executor** (record §8:
"executor behind gate, CyberGym range only"): it runs **only** on findings that already passed the
Increment-2 gate (approved + in-scope + committed), produces an outcome carrying **evidence**, and on a
successful, evidence-bearing outcome promotes the FINDING `hypothesis → reachable` via the existing
chokepoints.

Researcher findings this rests on (`02-research/findings.md`, SEQ 105): `FINDING_TRANSITIONS`
(`lifecycle.py:47-54`) permits `hypothesis → reachable` and this transition is **not** evidence-gated —
only `reported` is (`lifecycle.py:228-233`). `derive_confidence` (`lifecycle.py:81-88`) gives `hypothesis`
→ 3, `reachable` → 9 with evidence / 7 without. `attach_evidence(graph, engagement_dir, blob, kind,
target_type, target_id) -> sha256` (`evidence.py:57-81`) creates the EVIDENCE node + `evidences` edge;
`target_type="finding"` is real-used at `invalidation.py:33-41`. The canonical producer pattern
(`invalidation.py:33-44`, `record_secret_finding`) **attaches evidence then advances to `reachable`** — the
model this increment follows. Executor + promotion is **additive**: a new `agent/executor.py` plus one edit
to `dispatcher.py`, calling the existing `attach_evidence` + `advance_finding_status` only — no edit to
`lifecycle.py`/`evidence.py`/`graph.py`/`schema.py`/`scope_guard.py`.

**G3 rail (stricter than lifecycle).** Because `reachable` is not evidence-gated in `lifecycle.py`, this
increment enforces the honesty rail **in the agent layer**: the dispatcher promotes to `reachable` **only
when** the execution outcome both succeeded **and** carries evidence (which it attaches first). A
"succeeded but evidenceless" outcome does **not** promote — the finding stays `hypothesis`.

## §2 — Approach
Additive to `src/kronos/agent/` — **one new module, two small edits**. No edit to `contracts.py`,
`planner.py`, `drivers.py`, `reviewer.py`, or any non-agent source. No `lifecycle.py`/`evidence.py`/
`graph.py`/`schema.py`/`scope_guard.py` change (reused call-only).

**(a) `src/kronos/agent/executor.py` (NEW) — executor boundary + mock + outcome.**
- `@dataclass(frozen=True) class ExecutionOutcome`: `succeeded: bool`, `evidence: bytes | None`,
  `detail: str = ""`. The structured result of running one proposal; untrusted, like the planner/reviewer
  outputs.
- `class Executor(typing.Protocol)`: `def execute(self, intent: Intent) -> ExecutionOutcome: ...` — the
  only surface through which a (future, §6-authorized) live run would occur. **No concrete live executor is
  defined in this increment.**
- `class MockExecutor`: constructed with `scripted: Sequence[ExecutionOutcome]`; each `execute()` pops the
  next; over-consumption raises `RuntimeError("mock executor exhausted")`. Zero LLM, zero network,
  deterministic.
- `EVIDENCE_KIND = "agent_execution_proof"` — the `kind` passed to `attach_evidence`.

**(b) `src/kronos/agent/dispatcher.py` (EDIT) — add the optional executor + promotion (Phase 3).**
- Extend `DispatcherResult` with one defaulted field so existing construction is unaffected:
  `promoted: tuple[str, ...] = ()` (the FINDING ids advanced to `reachable` this step).
- In Phase 2, when a commit lands, record the `(finding_id, intent)` pair (not just the id) so Phase 3 can
  execute the right intent.
- `run_once(engagement, driver, reviewer=None, executor=None, engagement_dir=None) -> DispatcherResult` —
  add optional `executor` and `engagement_dir`. If `executor is not None` and `engagement_dir is None`,
  raise `ValueError("engagement_dir is required when an executor is given")` (evidence storage needs it).
  **Phase 3 (promote), only when `executor is not None`:** for each committed `(finding_id, intent)`:
  `outcome = executor.execute(intent)`; **iff** `outcome.succeeded` **and** `outcome.evidence is not None`:
  `attach_evidence(engagement, engagement_dir, outcome.evidence, kind=EVIDENCE_KIND,
  target_type="finding", target_id=finding_id)` **then** `advance_finding_status(engagement, finding_id,
  "reachable")`, and append `finding_id` to `promoted`. Otherwise do not promote (leave at `hypothesis`).
  Phase 3 runs **only** on already-gated committed findings — the executor is structurally *behind* the
  reviewer/scope gate.
- `run(engagement, driver, *, max_steps, reviewer=None, executor=None, engagement_dir=None)` — thread
  `executor` and `engagement_dir` through to `run_once` (keyword-only; existing callers unaffected).
- Import `attach_evidence` from `kronos.evidence` and `advance_finding_status` from `kronos.lifecycle`,
  and `Executor`/`EVIDENCE_KIND` from `kronos.agent.executor`. Promotion is the **only** new write; it goes
  through those two existing chokepoints — the dispatcher never sets `status`/`confidence` directly.

**(c) `src/kronos/agent/__init__.py` (EDIT) — export the executor surface.** Add `Executor`,
`MockExecutor`, `ExecutionOutcome`, `EVIDENCE_KIND` to the imports and `__all__`. Do not remove or reorder
existing exports.

No new dependency. No `events.py` change. No live network in any module (mock executor/reviewer/driver;
tests monkeypatch sockets to raise and assert none used, and assert no traffic outside the CyberGym range).
No edit to `contracts.py`, `planner.py`, `drivers.py`, `reviewer.py`, `lifecycle.py`, `evidence.py`,
`graph.py`, `schema.py`, `scope_guard.py`, any `validate/*` or `reconcile/*`, `manifest.py`, `.github/`, or
anything under `cybergym/`.

## §2a — Seal the brief-17 scope-audit (cross-brief landmine, per SEQ 72)
`tests/test_agent_commit.py` (brief 17, on `origin/main`) runs its whole-window audit against **`HEAD`**:
`BRIEF_BASE = "f4559a2"` (`test_agent_commit.py:16`) and `test_N_scope_audit` calls `git diff --name-only
f"{BRIEF_BASE}..HEAD"`. On this S8.3 branch `HEAD` includes the Increment-3 files, so it would fail. Seal it
to brief-17's merged footprint, **seal-only** (no other change to that file):
- add `BRIEF_MERGE = "a9f37ec"  # brief 17 merged to main (PR #25 squash); seals this audit to brief 17's footprint`
  (beside the existing `BRIEF_BASE`);
- change **only** the live range call inside `test_N_scope_audit` — `f"{BRIEF_BASE}..HEAD"` →
  `f"{BRIEF_BASE}..{BRIEF_MERGE}"`.

(`f4559a2..a9f37ec` is exactly brief-17's merged paths.) Do **not** touch `test_O_brief16_seal` or
`test_P_no_writer_rail_survives` (their assertion strings legitimately contain `f"{BRIEF_BASE}..HEAD"]`),
or any other line.

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only a9f37ec..HEAD` ⊆ set)
1. `SPEC_BRIEF18.md`
2. `src/kronos/agent/executor.py` (new)
3. `src/kronos/agent/dispatcher.py` (edit: optional `executor`/`engagement_dir` + Phase-3 promotion; `promoted` field)
4. `src/kronos/agent/__init__.py` (edit: export executor surface only)
5. `tests/test_agent_executor.py` (new)
6. `tests/test_agent_commit.py` (edit: §2a brief-17 seal ONLY — two spots)

Base = `origin/main` @ `a9f37ec`. Never `git add -A`; stage explicit paths only.
Do **NOT** edit `contracts.py`, `planner.py`, `drivers.py`, `reviewer.py`, `lifecycle.py`, `evidence.py`,
`graph.py`, `schema.py`, `scope_guard.py`, any `validate/*` or `reconcile/*`, `manifest.py`, `.github/`, or
anything under `cybergym/`. Build the test graph/manifest with existing helpers/fixtures READ-ONLY.

## §8 — Acceptance criteria (tests-as-rules; `tests/test_agent_executor.py`)
Decide PASS/FAIL from pytest's `SUMMARY:` line, never `$?` (CLAUDE.md §3). Expected values derive from this
brief's prose, not observed behaviour.

A. **Outcome + mock contract** — `ExecutionOutcome(succeeded=True, evidence=b"...")` is a frozen dataclass
   with `detail` defaulting to `""`; `MockExecutor([o1,o2])` returns `o1` then `o2`; over-consumption raises
   `RuntimeError`. Zero network.
B. **Promotion happy path** — with a committed FINDING at `hypothesis`, an executor returning
   `ExecutionOutcome(succeeded=True, evidence=b"proof")` causes `run_once(..., reviewer, executor=...,
   engagement_dir=...)` to: attach an EVIDENCE node + an `evidences` edge to the finding (kind
   `agent_execution_proof`), advance the finding to `reachable`, and include its id in
   `DispatcherResult.promoted`; `derive`d confidence is `9` (reachable with evidence).
C. **G3 evidenceless rail** — an outcome `succeeded=True, evidence=None` does **not** promote: the finding
   stays `hypothesis` with its **commit-time confidence unchanged** — the unpromoted finding never passes
   through `advance_finding_status`/`derive_confidence`, so its confidence stays the create value `0`
   (certainly `< 7`, below the `reachable` floor) — no EVIDENCE node/edge is created, and `promoted == ()`.
   (Assert `confidence < 7` and status `hypothesis`, not a specific promoted value.)
D. **Failed execution** — an outcome `succeeded=False` (with or without evidence) does **not** promote:
   finding stays `hypothesis`; `promoted == ()`.
E. **Executor is behind the gate** — a proposal that was rejected or out-of-scope (never committed in
   Phase 2) is **never executed** and never promoted; only committed findings are passed to the executor.
   (Drive with one in-scope approved intent and one out-of-scope/rejected intent; assert the executor saw
   only the committed one and only it is in `promoted`.)
F. **engagement_dir required** — `run_once(engagement, driver, reviewer, executor=MockExecutor([...]))`
   with `engagement_dir=None` raises `ValueError`; nothing is promoted and the graph's promotions are
   untouched.
G. **Backward-compatible** — `executor=None` (with a reviewer) commits as in Increment 2 but promotes
   nothing (`promoted == ()`, findings remain `hypothesis`); `reviewer=None` is the Increment-1 zero-side-
   effect path (`committed == ()`, `promoted == ()`, node+edge counts unchanged).
H. **Atomicity preserved** — a hostile verdict still raises `ReviewViolation` in Phase 1 before any commit
   or execution; the graph is completely unchanged (node+edge counts identical) and no executor call
   occurs.
I. **No live network** — monkeypatch both `socket.socket` and `socket.create_connection` to raise; a full
   `run` with a `MockExecutor` completes (local graph writes + evidence blob only) and asserts no socket was
   used. Assert no traffic outside the CyberGym range.
J. **Chokepoints only** — the promotion path calls `attach_evidence` and `advance_finding_status` and sets
   neither `status` nor `confidence` directly, and passes no `confidence`/`in_scope`/`merged_into`/`id` to
   any `upsert_*` (structural/source assertion on `dispatcher.py`). The assertion must actually fail if a
   direct status/confidence write were introduced — no always-true disjunct.
K. **Mock-driven end-to-end** — `run(engagement, driver, max_steps=N, reviewer=MockReviewer([...]),
   executor=MockExecutor([...]), engagement_dir=...)` with a driver that proposes then returns
   `{"complete": True}` commits each in-scope approved intent, promotes those whose outcome succeeded with
   evidence, stops at the first `complete`, and performs zero LLM calls and zero network.
L. **Scope audit (whole window)** — `git diff --name-only a9f37ec..HEAD` ⊆ the §3 set (whole window). This
   test defines `BRIEF_BASE = "a9f37ec"` and uses `f"{BRIEF_BASE}..HEAD"`.
M. **Brief-17 seal** — `tests/test_agent_commit.py` contains `BRIEF_MERGE = "a9f37ec"` and its
   `test_N_scope_audit` range call uses `f"{BRIEF_BASE}..{BRIEF_MERGE}"` (positives only — do **not** assert
   absence of the bare `f"{BRIEF_BASE}..HEAD"` literal, which legitimately persists inside the
   `test_O`/`test_P` seal-assertion strings).

## §9 — Done when
A–M pass under the project suite with 0 failed (totals refreshed as the final edit, after the last suite
run, per CLAUDE.md §4), the whole-window scope audit holds, the change is additive (one new `executor.py`,
two small edits to Increment-2 agent files, one new test file, plus the brief-17 seal), promotion goes only
through `attach_evidence` + `advance_finding_status`, a FINDING reaches `reachable` only with attached
execution evidence, the executor runs only on gated committed findings, and no non-agent source module is
edited. CyberGym-only, hermetic, no live targets, no live network; no live execution performed.
