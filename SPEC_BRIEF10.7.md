# SPEC_BRIEF10.7.md — Findings 1 & 2: determinant-true differential/grid citations + schema.py citation-line closure

**Status:** APPROVED at GATE-1 by the maintainer (recorded from the durable GATE-1 record in `kronos/loop-state:docs/loop/PROGRESS.md` SEQ 38; the brief was queued there rather than written to disk at approval time). Built @ `98586b3`, independently reviewed PASS on mechanics with three grounding findings (SEQ 42); maintainer chose **Option A** — accept the row-level exclusion mapping as a documented limit — at SEQ 43. Finding F-A deferred as its own follow-up (see `SPEC_BRIEF10.8.md`).
**Stage:** FORK-2. **Scope:** Findings 1 and 2 ONLY. **Author:** orchestrator (claude-opus).
**Lands on:** a branch cut from the fresh squash-merge `main` after PR #15 merged (`faac345`); implemented on `claude/findings-1-2-brief10-7`.

## 0. Goal justification
Primary **G2 (MORE EFFECTIVE):** the `scope_guard` conformance tests are the precondition for safe autonomy; a citation that names the wrong determinant clause, or a schema.py citation validated against a neighbouring line, is a change-detector masquerading as a conformance test. **G3** (safety/validation): not relaxed, not widened — this only tightens evidence grounding. **G1** untouched. Precedence respected: nothing narrowed or widened in product behaviour; test-only.

## 1. The defects
**Finding 2 — schema.py citation-line hole.** `test_b105_8_2` (`tests/test_scope_guard.py` ~:1479-1493) validated a `schema.py` citation against a ±3-line window (`lines[ln-1:ln+3]`), so a rule-5 row could cite a *neighbouring* type's line and still pass. The ±3 window is legitimate only for multi-line producer `NodeUpsert(` call sites (rule 1, non-schema `.py`), where the type string lands on a later line.

**Finding 1 — mis-attributed differential/grid cells.** ~35 differential/grid cells cited the wrong determinant clause: ~28 `_P5_BARE_IP`/`_P6_CIDR` exclusion cells and ~7 `_P4_BOTH_ENDS_GLOB` exclusion cells were attributed to a clause that does not determine them. The `:1935-1936` comment claimed §1.2 "exercises" cells that were already denied at `dcbdba9`.

## 2. The corrections (approach)
**Finding 2.** Harden `test_b105_8_2`: a `schema.py` citation must name the node type on the **cited line itself** (`lines[ln-1]`); keep the ±3-line window ONLY for multi-line producer `NodeUpsert(` call sites. Add a RED-first negative self-check: a constructed EV row citing `schema.py:223` (HOST's row) for `WEB_ENDPOINT` must be REJECTED (today's validator accepts it — the hole). All 12 shipped rows still pass.

**Finding 1.** Re-attribute the ~35 cells to their DETERMINANT clause (grids ~:1680-1685 and ~:1753-1755; clause registry ~:1631-1643; comment ~:1935-1936): ~28 `_P5_BARE_IP`/`_P6_CIDR` exclusion cells → **10.r7** (SPEC_BRIEF10 §1.1 r7 / `_matches_address_pattern`); ~7 `_P4_BOTH_ENDS_GLOB` exclusion cells → the **PD-5 exclusion-side clause** (NOT the allow-side FORK-U 10.1.U). Soften the `:1935-1936` comment claiming §1.2 "exercises" cells already denied at `dcbdba9`.

- **FORK-AE (ENFORCED, maintainer-strengthened):** the Finding-1 assertion must verify the INTENDED DETERMINANT ATTRIBUTION — each identified cell is asserted to cite its EXPECTED determinant clause (positive: bare-IP/CIDR → 10.r7; `_P4` → PD-5 exclusion-side clause), not merely that unchanged-from-`dcbdba9` cells avoid citing §1.2. The negative invariant is retained only as a secondary guard. The `dcbdba9` git-archive export already present in `test_b105_5_5` (~:1917-1969) supplies the base measurement.
- **FORK-AD:** post-merge — branch from the fresh squash-merge `main` commit (NOT `f80ad6a`, NOT `648621a`).

## 3. Permitted files (only these may change)
- `tests/test_scope_guard.py`

Reads `schema.py` and `scope_guard.py` read-only. Not permitted: any product code, `schema.py`, `scope_guard.py`, `graph.py`, `manifest.py`, or anything under `cybergym/`.

## 4. Other findings kept separate (NOT fixed by 10.7)
RFC-6874 percent-encoding; the `CLOUD_RESOURCE` rule-5 row; §5.5 enumeration mismatch; criterion-10 sub-clause — recorded, not addressed here.

## 8. Acceptance criteria
1. `schema.py` citation validated against the **cited line only**; `WEB_ENDPOINT` → `schema.py:223` fails; all 12 shipped rows pass.
2. Every identified differential/grid cell cites its **EXPECTED determinant clause** (positive attribution, enforced per FORK-AE); negative invariant retained as secondary guard.
3. The `:1935-1936` comment corrected.
4. `tests/`: 0 failed, 1 skipped; `cybergym/cloud/`: 17 passed — run under the project `.venv`; totals refreshed as the final edit.
5. Only `tests/test_scope_guard.py` changed; zero diff to `scope_guard.py` / `schema.py` / `graph.py` / `manifest.py` and `cybergym/`.
6. RED-first recorded for both guards.
7. Scope held to Findings 1 & 2.

## Exclusion-side determinant is row-uniform BY DESIGN (derived; SPEC_BRIEF10.9, Finding F-B)
TESTED claim: the DECLARED determinant map `_EXCL_DETERMINANT` is row-uniform over `_EXCLUSION_GRID` for the three named patterns, as asserted by `test_b109_fb_exclusion_determinant_is_row_uniform_by_design` (with a negative self-check proving the check can fail). RATIONALE (not tested, not an absolute): the authors declared the map row-level because rule 6 (deny-broad) compares HOST-IDENTITY ONLY (`src/kronos/scope_guard.py` rule 6; `SPEC_BRIEF10.5.md` §1.3 PD-5), so port, scheme and path -- the axes that distinguish target columns -- are discarded; this is the reason the map is declared row-uniform. The test does not verify that causal derivation. This is not a gap and no verdict changes. Follow-up **F-A** (schema.py wrong-/missing-type citation) is tracked separately in `SPEC_BRIEF10.8.md`.
