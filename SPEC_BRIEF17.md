# SPEC_BRIEF17 S8.2 Agent layer — Increment 2 (reviewer + rails as the commit gate, no live execution)
**Stage:** S8 (research record §6 ladder / §8 "Agent layer design"). This brief is **Increment 2 only**.
**Goal:** G2 + G3 (the agent may propose, but a proposal reaches the graph only through a downgrade-only
reviewer and the existing hard rails, at the lowest tier, with no live execution — so the LLM can never
write a validated finding or touch an out-of-scope target).
**Depends on:** Increment 1 (`src/kronos/agent/`, merged PR #24 @ `f4559a2`): the read-only planner, the
strict `Intent`/`ReasonResult` contract, the `MockDriver`, and the zero-side-effect dispatcher skeleton.
**Authorization:** maintainer `/home/void/context.md` (2026-10-23) — "Authorize A: begin S8 … continue the
established autonomous … workflow within that approved direction" (Increments 1–3), recorded at SEQ 95; S8
Increment 2 named as the autonomous next step at SEQ 98/99. GATE-1 self-approved by Opus after validating
this brief against the researcher's cited findings (`02-research/findings.md`, SEQ 99) and the record §8 +
locked decision 9. **CyberGym only. NO live-target testing. NO live network. No scope expansion. No schema
or scope_guard change.**

## §1 — Problem
Increment 1 gave a dispatcher that plans but writes nothing. Increment 2 adds the first graph write, behind
two gates that the LLM can never override (record §8, RR.md:1649-1665): a **reviewer** that fills Cairn's
evidenceless slot and **may downgrade, never upgrade** (locked decision 9, RR.md:663), and the existing
**hard rails** (`scope_guard` inside `upsert_node`, the lifecycle status model). A reviewer-approved
proposal is committed only as a **FINDING at `status="hypothesis"`** (the lowest, unvalidated tier) linked
to its target — **no live execution** (the executor is Increment 3; nothing runs against a target, no
network, no promotion past `hypothesis`). Rejected, out-of-scope, or "upgraded" proposals write nothing.

Researcher findings this rests on (`02-research/findings.md`, SEQ 99): a hypothesis-tier FINDING is created
by a plain `upsert_node("FINDING", id, {"status":"hypothesis",…})` (status is create-only,
`schema.py:188-196`), never via `advance_finding_status`; `upsert_node` **stamps** `in_scope` via
`self.scope.is_in_scope(id, node_type=type, target_kind="id")` (`graph.py:147-151`) but does **not** reject
an out-of-scope node, so the commit gate must check scope **explicitly and skip the write** when out of
scope; `vulnerable_to` is schema-legal from the seven asset types to FINDING and `derived_from` from FINDING
to SECRET (`schema.py:124-128`, `:134`); `NODE_PROPS_FORBIDDEN` (`schema.py:212`) =
`{id,in_scope,confidence,scope_note,merged_into}`; the existing producers' shape is
`invalidation.py:17-32` / `web_validator.py:44-56`. No reviewer exists in code yet. The only live unsealed
`..HEAD` scope audit on `origin/main` is `tests/test_agent_dispatcher.py:109` (brief-16).

## §2 — Approach
Additive to `src/kronos/agent/` — **one new module, two small edits to Increment-1 agent files**. No edit
to `contracts.py`, `planner.py`, `drivers.py`, or any non-agent source. **No `schema.py` / `scope_guard.py`
/ `lifecycle.py` / `graph.py` change** — the commit reuses the existing node type, edge labels, status, and
scope rail. `Intent` (the planner's contract) is left **unchanged**; the commit parameters live on the new
reviewer contract, so Increment 1's merged tests keep passing.

**(a) `src/kronos/agent/reviewer.py` (NEW) — the reviewer contract + mock.**
- `LEGAL_TARGET_TYPES = frozenset({"HOST","SERVICE","WEB_ENDPOINT","API_ENDPOINT","CLOUD_RESOURCE",
  "MOBILE_APP","MOBILE_COMPONENT","SECRET"})` — exactly the types for which `vulnerable_to`
  (asset→FINDING) or `derived_from` (FINDING→SECRET) is schema-legal today. Any other target type is
  out of scope for Increment 2.
- `COMMIT_STATUS = "hypothesis"` — the only status a committed proposal may carry (the lowest tier; the
  "never upgrade" invariant made concrete).
- `class ReviewViolation(ValueError)`.
- `@dataclass(frozen=True) class ReviewVerdict`: `approved: bool`, `target_type: str`, `status: str`. The
  reviewer's structured output; it is *untrusted* exactly like the planner payload.
- `class Reviewer(typing.Protocol)`: `def review(self, intent: Intent) -> ReviewVerdict: ...`.
- `class MockReviewer`: constructed with `scripted: Sequence[ReviewVerdict]`; each `review()` pops the next;
  over-consumption raises `RuntimeError("mock reviewer exhausted")`. Zero LLM, zero network.
- `def validate_verdict(verdict: ReviewVerdict) -> None`: pure; raises `ReviewViolation` when a verdict is
  not a `ReviewVerdict`, or — **for an approved verdict** — when `target_type not in LEGAL_TARGET_TYPES`,
  or `status != COMMIT_STATUS` (this is the **downgrade-only / never-upgrade rail**: a verdict that tries to
  commit at `reachable`/`exploited`/`reported` or any non-`hypothesis` status is rejected and writes
  nothing). A rejected verdict (`approved is False`) is always valid (it commits nothing).

**(b) `src/kronos/agent/dispatcher.py` (EDIT) — add the optional reviewer + commit gate.**
- Extend `DispatcherResult` with one field **with a default** so Increment-1 construction is unaffected:
  `committed: tuple[str, ...] = ()` (the FINDING ids committed this step).
- `run_once(engagement, driver, reviewer=None) -> DispatcherResult` — add the optional `reviewer`
  parameter. When `reviewer is None`, behaviour is **exactly Increment 1** (plan only; `committed == ()`;
  zero side effects). When a `reviewer` is given and the result is not `complete`, for each proposed
  `Intent`: `verdict = reviewer.review(intent)`; `validate_verdict(verdict)`; **commit iff**
  `verdict.approved` **and** `engagement.scope.is_in_scope(intent.target_id,
  node_type=verdict.target_type, target_kind="id")` is true — otherwise write nothing for that intent.
- `run(engagement, driver, *, max_steps, reviewer=None)` — thread `reviewer` through to `run_once`
  (keyword-only addition; existing callers unaffected).
- **Commit** (new private helper `_commit(engagement, intent, verdict) -> str`): deterministic
  `finding_id = f"finding:agent-proposal:{intent.kind}:{intent.target_id}"`;
  `engagement.upsert_node("FINDING", finding_id, {"source":"agent_dispatcher", "title": intent.rationale,
  "severity":"info", "status":"hypothesis"})` — **never** pass `confidence`/`in_scope`/`merged_into`/`id`
  (`NODE_PROPS_FORBIDDEN`); then one edge by target type: for `SECRET`,
  `upsert_edge("derived_from", finding_id, "FINDING", intent.target_id, "SECRET")`; for any other legal
  (asset) type, `upsert_edge("vulnerable_to", intent.target_id, verdict.target_type, finding_id,
  "FINDING")`. Return `finding_id`. No `advance_finding_status`, no budget charge, no network, no execution.

**(c) `src/kronos/agent/__init__.py` (EDIT) — export the reviewer surface.** Add
`Reviewer`, `MockReviewer`, `ReviewVerdict`, `ReviewViolation`, `validate_verdict`, `LEGAL_TARGET_TYPES`,
`COMMIT_STATUS` to the imports and `__all__`. Do not remove or reorder existing exports.

No new dependency. No `events.py` change. No live network in any module (mock reviewer/driver; tests
monkeypatch sockets to raise and assert none used, and assert no traffic outside the CyberGym range).
No edit to `contracts.py`, `planner.py`, `drivers.py`, `schema.py`, `scope_guard.py`, `lifecycle.py`,
`graph.py`, any `validate/*` or `reconcile/*`, `manifest.py`, `.github/`, or anything under `cybergym/`.

## §2a — Seal the brief-16 scope-audit (cross-brief landmine, per SEQ 72)
`tests/test_agent_dispatcher.py` (brief 16, on `origin/main`) still runs its whole-window audit against
**`HEAD`**: `BRIEF_BASE = "81796b4"` (`:23`) and `f"{BRIEF_BASE}..HEAD"` (`:109`). On this S8.2 branch
`HEAD` includes the Increment-2 files, so that audit would fail. Seal it to brief-16's merged footprint,
**seal-only** (no other change to that file):
- add `BRIEF_MERGE = "f4559a2"  # brief 16 merged to main (PR #24 squash); seals this audit to brief 16's footprint`
  (beside the existing `BRIEF_BASE`);
- change the diff range `f"{BRIEF_BASE}..HEAD"` → `f"{BRIEF_BASE}..{BRIEF_MERGE}"`.

(`81796b4..f4559a2` is exactly brief-16's merged paths.) Do **not** touch `test_agent_dispatcher.py:117-118`
(the brief-15-seal assertion strings for `test_invalidation.py`) or any other line.

## §2c — Retire the dispatcher from the Increment-1 no-writer rail (AMENDMENT, SEQ 101)
Increment 1 shipped `tests/test_agent_contracts.py::test_N_no_writer_calls`, parametrized over
`["contracts.py", "planner.py", "dispatcher.py"]` (`test_agent_contracts.py:117`), asserting none of the
three contains a writer call (`upsert_node(`/`upsert_edge(`/`advance_*`/`charge`). Increment 2 makes the
dispatcher the **sole graph-writer** (record §8 "control plane sole writer") via `_commit` in §2(b), so
`dispatcher.py` must now contain `upsert_node(`/`upsert_edge(`. The no-writer rail's real intent — that the
planner and the contract layer never write — is **preserved and still enforced**: edit `test_N`'s
`parametrize` list to drop **only** `"dispatcher.py"`, leaving `["contracts.py", "planner.py"]`. Change
**only** that one list; do not weaken the assertion body, and do not remove `contracts.py` or `planner.py`.
The dispatcher's write discipline is instead enforced by §8-J (no forbidden columns; `status` set only at
create) and by the commit gate's scope/verdict checks.

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only f4559a2..HEAD` ⊆ set)
1. `SPEC_BRIEF17.md`
2. `src/kronos/agent/reviewer.py` (new)
3. `src/kronos/agent/dispatcher.py` (edit: optional `reviewer` + commit gate; `committed` field)
4. `src/kronos/agent/__init__.py` (edit: export reviewer surface only)
5. `tests/test_agent_reviewer.py` (new)
6. `tests/test_agent_commit.py` (new)
7. `tests/test_agent_dispatcher.py` (edit: §2a brief-16 seal ONLY — two spots)
8. `tests/test_agent_contracts.py` (edit: §2c — drop `"dispatcher.py"` from `test_N`'s `parametrize` list ONLY)

Base = `origin/main` @ `f4559a2`. Never `git add -A`; stage explicit paths only.
Do **NOT** edit `contracts.py`, `planner.py`, `drivers.py`, `schema.py`, `scope_guard.py`, `lifecycle.py`,
`graph.py`, `events.py`, `evidence.py`, `query.py`, any `validate/*` or `reconcile/*`, `manifest.py`,
`.github/`, or anything under `cybergym/`. Build the test graph/manifest with existing helpers/fixtures
READ-ONLY.

## §8 — Acceptance criteria (tests-as-rules)
Decide PASS/FAIL from pytest's `SUMMARY:` line, never `$?` (CLAUDE.md §3). Expected values derive from this
brief's prose, not observed behaviour. Reviewer-contract tests in `tests/test_agent_reviewer.py`;
commit-gate/rails tests in `tests/test_agent_commit.py`.

A. **Verdict contract — approved happy path** — `validate_verdict(ReviewVerdict(approved=True,
   target_type=t, status="hypothesis"))` returns None (no raise) for every `t` in `LEGAL_TARGET_TYPES`.
B. **No-upgrade rail** — an approved verdict with `status` in
   `{"reachable","exploited","reported","discarded","validated",""}` raises `ReviewViolation`. Only
   `"hypothesis"` is accepted. `COMMIT_STATUS == "hypothesis"`.
C. **Illegal target type** — an approved verdict with `target_type` not in `LEGAL_TARGET_TYPES`
   (e.g. `"IDENTITY"`, `"PARAMETER"`, `"ENGAGEMENT"`, `"NOT_A_TYPE"`) raises `ReviewViolation`.
   `LEGAL_TARGET_TYPES` equals the eight types named in §2(a).
D. **Rejected verdict always valid** — `validate_verdict(ReviewVerdict(approved=False, target_type="x",
   status="anything"))` returns None (a rejection commits nothing, so its fields are not constrained).
E. **Mock reviewer determinism** — `MockReviewer([v1,v2])` returns `v1` then `v2`; over-consumption raises
   `RuntimeError`. Zero network.
F. **In-scope approved commit** — with a manifest that puts the target in scope, `run_once(engagement,
   driver, reviewer)` where the driver proposes one intent and the reviewer approves it at `hypothesis`
   creates a FINDING `finding:agent-proposal:<kind>:<target_id>` with `status=="hypothesis"` and
   `confidence==0` (unvalidated; `upsert_node` sets `confidence=0` at create), plus the correct edge
   (`vulnerable_to` asset→FINDING for an asset target, `derived_from` FINDING→SECRET for a SECRET target);
   the returned `DispatcherResult.committed` contains the finding id.
G. **Out-of-scope → writes nothing** — with a manifest that excludes the target, the same run commits
   nothing: the engagement's node and edge counts are identical before and after, and
   `DispatcherResult.committed == ()`.
H. **Rejected → writes nothing** — a reviewer returning `approved=False` commits nothing (counts
   unchanged, `committed == ()`).
I. **Hostile verdict → writes nothing** — a reviewer returning an approved verdict with a non-`hypothesis`
   status or an illegal target_type causes `run_once` to raise `ReviewViolation` and the graph is unchanged
   (node+edge counts identical; nothing partially written).
J. **No forbidden columns** — the commit never passes `confidence`/`in_scope`/`merged_into`/`id` to
   `upsert_node`, and sets `status` only at create (structural/source assertion on `dispatcher.py`).
K. **Backward-compatible zero-side-effect path** — `run_once(engagement, driver)` and `run(engagement,
   driver, max_steps=N)` **with no reviewer** still perform zero side effects (node+edge counts identical
   before/after) and return `committed == ()` — Increment 1's invariant is preserved.
L. **Mock-driven end-to-end** — `run(engagement, driver, max_steps=K, reviewer=MockReviewer([...]))` with a
   driver that proposes intents then returns `{"complete": True}` commits each in-scope approved intent,
   stops at the first `complete` result, and performs zero LLM calls and zero network.
M. **No live network** — monkeypatch both `socket.socket` and `socket.create_connection` to raise; the full
   commit run still completes (local graph writes only) and asserts no socket was used. Assert no traffic
   outside the CyberGym range.
N. **Scope audit (whole window)** — `git diff --name-only f4559a2..HEAD` ⊆ the §3 set (audit the whole
   window, not just expected files). This test defines `BRIEF_BASE = "f4559a2"` and uses
   `f"{BRIEF_BASE}..HEAD"`.
O. **Brief-16 seal** — `tests/test_agent_dispatcher.py` contains `BRIEF_MERGE = "f4559a2"` and its diff-range
   call uses `f"{BRIEF_BASE}..{BRIEF_MERGE}"` (the §2a seal landed, seal-only). Note: the bare literal
   `f"{BRIEF_BASE}..HEAD"` legitimately still appears inside the unrelated brief-15 seal-assertion string
   (`test_agent_dispatcher.py:118`, which §2a forbids touching), so assert on the **range call** —
   `f"{BRIEF_BASE}..HEAD"]` (the diff invocation with its closing bracket) is **absent** — not on the bare
   string.
P. **No-writer rail survives (§2c)** — `tests/test_agent_contracts.py::test_N_no_writer_calls` is
   parametrized over exactly `["contracts.py", "planner.py"]` (no `"dispatcher.py"`), and still asserts
   each contains no `upsert_node(`/`upsert_edge(`/`advance_secret_status(`/`advance_finding_status(`/
   `charge(`. `src/kronos/agent/contracts.py` and `src/kronos/agent/planner.py` remain writer-free.

## §9 — Done when
A–P pass under the project suite with 0 failed (totals refreshed as the final edit, after the last suite
run, per CLAUDE.md §4), the whole-window scope audit holds, the change is additive (one new `reviewer.py`,
two small edits to Increment-1 agent files, two new test files, the brief-16 seal, and the §2c one-line
test_N parametrize edit), a committed
proposal is a FINDING at `hypothesis` only (no promotion, no live execution, no network), out-of-scope /
rejected / upgraded proposals write nothing, and no non-agent source module is edited. CyberGym-only,
hermetic, no live targets, no live network.
