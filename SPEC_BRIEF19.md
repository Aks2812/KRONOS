# SPEC_BRIEF19 S8 LOW-backlog cleanup (test non-vacuity, contract truthiness, stale comment, extra-key policy)

**Stage:** S8 agent layer, post-Increment-3. This brief clears the three non-blocking LOW
backlog items recorded at PROGRESS.md SEQ 108 — it adds **no new behavior** and **no live
execution**. Authorized by maintainer next-direction choice **(C)** (resumes after the SEQ
108/109/110 checkpoints). CyberGym only; no live targets; no scope expansion; zero network in
tests.

## §1 — Problem

Three LOW items from SEQ 108 `non_blocking_backlog`:

1. **L-1 (real test defect).** `tests/test_agent_executor.py` `test_J_chokepoints_only`
   (~181-193) ends with a self-referential non-vacuity check: it builds a literal string `bad`
   by hand and asserts `'"status"' in bad`. That exercises nothing from
   `dispatcher.run_once` — if the forbidden-pattern checks above it were deleted, those last
   lines would still pass. The non-vacuity guard proves only that Python substring matching
   works on a string the test wrote.

2. **contracts.py truthiness (real defect).** `src/kronos/agent/contracts.py`
   `validate_reason_payload` line 38 is `complete = bool(payload.get("complete"))`. Since
   `bool("false") is True`, a payload `{"complete": "false"}` is silently read as complete.
   There is no type check on `complete`.

3. **extra-key policy (open question) + L-2 (cosmetic).** `validate_reason_payload` rejects
   only `FORBIDDEN_FIELDS`; unknown top-level/intent keys are silently ignored, and the policy
   was never recorded. Separately, the comment at `tests/test_agent_executor.py` ~121 cites
   "Brief §8 C says confidence 3", but `SPEC_BRIEF18.md` §8-C now states the create-time value
   is `0`. Only the comment is stale; the `< 7` assertion is correct.

## §2 — Approach

- **L-1:** hoist the forbidden-pattern tuple used by the `run_once`-source scan into a single
  local, use it for the scan loop, then assert the **same** tuple flags a known direct-write
  string. The guard then fails if the forbidden set is emptied — it is bound to the production
  matcher, not to a hand-written literal.
- **contracts.py:** reject a non-`bool` `complete` with `ContractViolation` before coercion;
  an absent `complete` still defaults to `False`. No other evaluation changes.
- **extra-key policy:** record the decision in a one-line comment in `contracts.py` —
  `validate_reason_payload` is intentionally lenient on unknown keys (only `FORBIDDEN_FIELDS`
  are rejected), matching the create-only contract model. **No behavior change**; strict
  unknown-key rejection is deliberately out of scope for this cleanup (it would change the
  Increment 1-3 contract surface and needs its own authorized brief).
- **L-2:** correct the stale comment to cite create value `0`; assertion unchanged.

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only 5b7001d..HEAD` ⊆ set)

1. `SPEC_BRIEF19.md`
2. `src/kronos/agent/contracts.py` (edit: type-check `complete`; one-line extra-key-policy comment)
3. `tests/test_agent_executor.py` (edit: L-1 non-vacuity rewrite; L-2 comment fix — two spots)
4. `tests/test_agent_contracts.py` (edit: add `complete`-must-be-bool test)

Base = `origin/main` @ `5b7001d`. Never `git add -A`; stage explicit paths only.
Do **NOT** edit `dispatcher.py`, `executor.py`, `planner.py`, `drivers.py`, `reviewer.py`,
`__init__.py`, `schema.py`, `scope_guard.py`, `manifest.py`, `.github/`, or anything under
`cybergym/`. Build fixtures with existing helpers READ-ONLY.

## §8 — Acceptance criteria (tests-as-rules; `tests/test_agent_executor.py`, `tests/test_agent_contracts.py`)

Decide PASS/FAIL from pytest's `SUMMARY:` line, never `$?` (CLAUDE.md §3). Expected values
derive from this brief's prose, not observed behaviour.

A. **L-1 non-vacuity bound to the matcher** — in `test_J_chokepoints_only`, the forbidden
   patterns are a single named tuple; the scan loop uses it against `dispatcher.run_once`
   source, and a final assertion applies that **same** tuple to the direct-write string
   `engagement.upsert_node("FINDING", fid, {"status": "reachable", "confidence": 9})` and
   requires it to be flagged (`any(f in bad for f in forbidden)` is `True`). Emptying the tuple
   must break both the scan and this guard. Zero network.

B. **contract rejects non-bool `complete`** — `validate_reason_payload({"complete": "false"})`
   raises `ContractViolation`; so does any non-`bool` `complete` (e.g. `1`, `"true"`, `[]` when
   present). `bool("false")`-style coercion no longer occurs.

C. **`complete` stays optional** — a payload with no `complete` key and a non-empty `intents`
   list is still valid (`complete` defaults to `False`); `{"complete": True}` is valid;
   `{"complete": False, "intents": [<one valid intent>]}` is valid; the existing coexistence
   rules (`complete and intents` → raise; neither → raise) are unchanged.

D. **extra-key policy recorded** — `contracts.py` carries a one-line comment stating unknown
   keys are intentionally ignored (only `FORBIDDEN_FIELDS` rejected). No test asserts rejection
   of unknown keys, and none is added; behavior is unchanged.

E. **L-2 comment accuracy** — the evidenceless-rail test's comment cites the brief's current
   create value `0` (not `3`); the assertion remains `node["confidence"] < 7`.

F. **Scope audit (whole window)** — `git diff --name-only 5b7001d..HEAD` ⊆ the §3 set.

G. **Suite green** — full `pytest` run reports `0 failed` on the final commit (totals refreshed
   as the last edit).

## §9 — Done when

All of §8 holds, the whole-window scope audit is clean, the change is additive-or-corrective
only (no new module, no live execution, no network), and the full suite is green on the head
commit.
