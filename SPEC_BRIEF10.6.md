# SPEC_BRIEF10.6.md — Erratum: §4.2 and guardrail-9 HOST-narrowing lines contradict the ratified HOST family (Finding 5)

**Status:** APPROVED at GATE-1 by the maintainer, with the two-line amendment (correct both false HOST-narrowing statements; for lines 186-187 remove "§1.1's HOST change narrows" and keep the check; no audit footnote; Findings 1 and 2 kept separate).
**Stage:** FORK-2 (issue #2). **Predecessor:** SPEC_BRIEF10.5 at PR #15 head `648621a`, independently reviewed PASS 15/15.
**Lands on:** PR #15's existing branch `claude/scope-key-dispatch-brief10-4`.

## 0. Goal justification
Primary **G2 (MORE EFFECTIVE):** `scope_guard`'s specification is the precondition for safe autonomy; a stray line that silently reverses a ratified shape family is a defect in that precondition. **G3** (safety/validation constraint) not advanced, not weakened — no gate relaxed, no scope widened. **G1** untouched. Precedence respected: this removes contradictions only; it narrows nothing and widens nothing.

## 1. The defect
`SPEC_BRIEF10.5.md` carried two surviving fragments of FORK-AB's **rejected** HOST-narrowing proposal:
- **Line 221** (§4 Design, item 2): stated that `HOST` narrows to `{host, ip}`.
- **Lines 186-187** (acceptance item 9 / guardrail 9): "§1.2 widens the deny side; §1.1's `HOST` change narrows." — §1.1 makes no narrowing change to HOST.

Both contradict three ratified places in the same brief: §1.1 (HOST keeps all four shapes under rule 1), §7 FORK-AB ("PROPOSED AND REJECTED"), and §8 acceptance criterion 3 (HOST is `{host, ip, host_port, ip_port}` under rule 1). Severity: LOW (documentation) but regression-capable — a reader following §4.2 would narrow HOST and break 21 tests (14 ratified lock/H2/grid cases from Briefs #10/#10.1/#10.3) plus guardrail §2.1's signed-manifest proof.

## 2. The corrections
(a) On `SPEC_BRIEF10.5.md:221`, the clause now reads: `HOST` keeps all four shapes `{host, ip, host_port, ip_port}` under rule 1 (not rule 5); rule 5 is never consulted for it (see §1.1, FORK-AB).
(b) On `SPEC_BRIEF10.5.md:186-187`, remove the false "§1.1's `HOST` change narrows" clause so item 9 reads: "The allow side is not widened anywhere. §1.2 widens the deny side. Prove the allow side is unchanged by differential measurement, not by assertion."
No audit footnote.

## 3. Permitted files (only these may change)
- `SPEC_BRIEF10.5.md` — lines 221 and 186-187 only.
- `SPEC_BRIEF10.6.md` — this erratum brief itself.

Not permitted: any code, test, `schema.py`, `graph.py`, `scope_guard.py`, `manifest.py`, `README_scope.md`, `DECISIONS.md`, or anything under `cybergym/`.

## 4. Verification (doc-only change; checks are scope/zero-diff assertions)
1. Scope: `git diff --name-only 648621a..HEAD` contains only the two §3 files.
2. Code zero-diff: no diff to any code/test/doc file outside §3; the test suite is therefore necessarily unchanged from the reviewed baseline (tests/: 3457 passed, 0 failed, 1 skipped; cybergym/cloud/: 17 passed). Run under the project `.venv`.
3. Consistency: no line of `SPEC_BRIEF10.5.md` asserts (as live design) that HOST narrows; §4 item 2, item 9, §1.1, §7 FORK-AB, §8.3 all agree on four shapes under rule 1. The only remaining mention of the narrowing is FORK-AB, which records it as rejected.

## 5. FORKs
- FORK-ER1: correct both lines in place, no footnote (maintainer chose default).
- FORK-ER2: Findings 1 and 2 kept as separate follow-up items (not bundled here).

## 6. Acceptance criteria
1. Lines 221 and 186-187 corrected as §2. 2. No surviving HOST-narrows claim (outside FORK-AB's rejected record). 3. Only §3 files changed. 4. Code/suite zero-diff vs 648621a. 5. Findings 1 and 2 untouched. 6. PR #15 left open, unmerged, not marked ready. 7. New head SHA recorded; the 648621a PASS marked invalidated pending fresh review at the new head.
