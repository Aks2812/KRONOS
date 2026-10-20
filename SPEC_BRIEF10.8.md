# SPEC_BRIEF10.8.md — Finding F-A: a schema.py citation must name the row's own type, not merely exist

**Status:** APPROVED at GATE-1 by the maintainer (`"GATE-1 approve 10.8"`; brief authored by the orchestrator this session and recorded in `kronos/loop-state:docs/loop/PROGRESS.md` SEQ 47). Built @ `a753aa9`, independently reviewed PASS, orchestrator step-5 verified. Parked at GATE-2 (local only, not pushed, no PR).
**Stage:** FORK-2. **Derives from:** Finding **F-A** (MEDIUM), recorded SEQ 43 as a deferred follow-up to `SPEC_BRIEF10.7`.
**Lands on:** `claude/findings-1-2-brief10-7`, base `98586b3`.

## 0. Goal justification
Primary **G2 (MORE EFFECTIVE):** closes a grounding gap left open by 10.7's Option A — the schema.py citation check rejected a *wrong* type but accepted a line naming *no* type, so a rule-5 row could cite an existing-but-irrelevant schema.py line. **G3** not relaxed; **G1** untouched. Test-only; no product behaviour changed.

## 1. The defect
`_citation_line_error` (`tests/test_scope_guard.py` ~:1434-1453), for a `schema.py` citation, computed `window = lines[ln-1]` and `quoted = re.findall(r'"([A-Z_]{3,})"', window)`, then errored only when `quoted and node_type not in quoted`. Gap: a cited `schema.py` line that **exists but names no type** (`quoted` empty) returned `None` = ACCEPTED. §1.2 rule 4/5 require a rule-5 row's `schema.py` citation to POSITIVELY name the row's own type.

## 2. The correction (approach)
Tighten ONLY the `schema.py` branch of `_citation_line_error` so `node_type` must appear in the cited line — error when `node_type not in quoted` (covers both wrong-type AND names-no-type). The producer (non-schema, multi-line window) branch is unchanged: it still rejects only a different-named type.

**Pre-build probe (orchestrator, read-only):** all 5 rule-5 `NODE_TYPE_SHAPE_EVIDENCE` rows already positively name their own type on the cited schema.py line (`SERVICE`:224, `WEB_ENDPOINT`:225, `PARAMETER`:226, `IDENTITY`:231, `TECHNOLOGY`:233), so the tightening breaks no existing row and no evidence-table / schema.py edit is required.

## 3. Permitted files (only these may change)
- `tests/test_scope_guard.py`

Not permitted: `src/kronos/scope_guard.py`, `src/kronos/schema.py`, any other product code, or anything under `cybergym/`.

## 5. Tests (RED-first; tests are the deliverable)
1. Tighten the `schema.py` branch of `_citation_line_error` (above).
2. New negative self-check `test_b108_fa_schema_citation_must_name_own_type_not_merely_exist`: a `schema.py` citation to a line that EXISTS but names NO type (`schema.py:221`, the `NODE_COLUMNS: dict[...] = {` opener — asserted to carry no quoted uppercase token) is REJECTED; keep the `:223` wrong-type-rejected and `:225` correct-accepted cases.
3. Regression: `test_b105_8_2_every_row_records_a_citation_and_a_rule_number` stays green (all 5 rule-5 rows still pass); `test_b107_f2_wrong_line_schema_citation_is_rejected` not weakened.

## 8. Acceptance criteria
1. `rtk test` `SUMMARY:` line shows **0 failed** (decide PASS/FAIL from the SUMMARY line, never the exit code).
2. The names-no-type negative self-check is present and asserts rejection.
3. `git diff --name-only 98586b3..HEAD` is exactly `tests/test_scope_guard.py`.
4. No live network; no traffic outside the CyberGym range.

This is §8 acceptance-tightening of an existing test. Not §6 live-use.

## Build evidence (recorded)
- HEAD `a753aa9`; diff `98586b3..a753aa9` = `tests/test_scope_guard.py` only (+25/-1).
- `.venv` pytest `tests/test_scope_guard.py`: 2992 passed, 0 failed; reviewer full suite: 3459 passed, 1 skipped, 0 failed.
- no-live-network satisfied statically (no `socket`/`urllib`/`requests`/`httpx` import in the file).
