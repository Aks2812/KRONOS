# SPEC_BRIEF48 — reference eligibility predicate uses `paths` (AUTO-BRIEF, seq 280 NONE)

Origin: contract §13.1 standing AUTO-BRIEF envelope. Top checkpoint seq 280 pending_action NONE.
Selected backlog item (2): the reference `_eligible` predicate in `tests/test_rnd_contract.py`
ignores each item's `paths`; governance / `.claude` classification rides only on the hand-set
`touches_governance` / `touches_claude` flags, so `paths` (set by `_mk`) is dead. A backlog item
whose `paths` are governance but whose flag was left unset would be wrongly judged ELIGIBLE —
a fail-open gap against §13.1, which keys ineligibility off the files an item touches.

Priority rationale: item (1) (wire tests to live loop code) touches live executor / §6–§8 live-run
(PAUSED) and is materially ambiguous → mandatory pause, INELIGIBLE. Items (3–4) edit the contract →
governance, human-gated, INELIGIBLE. Item (2) is recorded, unblocked, reversible, branch-local,
precisely scoped, non-live, non-destructive, touches only a test file → the single highest-priority
ELIGIBLE action.

## §1 Permitted files (hard scope)
- `tests/test_rnd_contract.py` (ONLY)
- `docs/loop/SPEC_BRIEF48.md` (this brief, on the feature branch)

No other path. No governance file, no `.claude/**`, no `src/**`, no manifest/schema.

## §3 Scope-audit seal
- Prior AUTO-BRIEF (PR #47, contract v1.2.0) sealed @ `2fc2381e7a94cf217b175b0a32577e741506c90e` (main).
- This brief's scope-audit window = `2fc2381..HEAD`; every changed path MUST be in §1.

## §8 Acceptance criteria
- AC1 (scope): diff over `2fc2381..HEAD` touches only §1 paths.
- AC2 (paths now used): `_eligible` derives governance/`.claude` ineligibility from `item["paths"]`,
  OR'd with the existing hand-set flags; neither flag alone is the only signal.
- AC3 (fail-open closed): a backlog item with a `docs/governance/**` (or contract/manifest/schema)
  path and `touches_governance=False` is INELIGIBLE; same for a `.claude/**` path with
  `touches_claude=False`. New negative-case test(s) assert this and FAIL on the pre-change predicate.
- AC4 (no regression): existing SEQ272 selection tests unchanged in outcome — low1 selected,
  low1/low2 eligible, low3/low4 ineligible, empty/all-governance → idle.
- AC5 (suite): `pytest tests/test_rnd_contract.py` 0 failed; full suite 0 failed (re-measured from
  runner summary, never `$?`).

## Suite
Focused: `tests/test_rnd_contract.py`. Full: entire `tests/` suite (via `rtk test`).
