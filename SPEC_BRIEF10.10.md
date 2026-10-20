# SPEC_BRIEF10.10.md — Finding F-C: PD-5's host-identity-only scope must be tested, not asserted only in an untested comment

**Status:** APPROVED at GATE-1 by the orchestrator (Opus self-approval under the maintainer-authorized full-autonomy model — `CLAUDE.md` "Authority model"; `kronos/loop-state:docs/loop/PROGRESS.md` SEQ 55–56). Brief authored by the orchestrator this session.
**Stage:** FORK-2. **Derives from:** Finding **F-C** (LOW), recorded SEQ 42/43 as a deferred follow-up to `SPEC_BRIEF10.7` (Option A).
**Lands on:** `claude/finding-c-brief10-10`, base `d71ebf6` (current `main`; contains 10.7 + 10.8). Independent of the parked 10.9 — append-only; does not edit the F-B determinant comment or grid.

## 0. Goal justification
Primary **G2 (MORE EFFECTIVE):** closes a grounding gap. PD-5 (`10.5.pd5e`, the both-ends-glob exclusion) is **host-identity only**, but that scope is stated in code and in an **untested** rationale comment, while `_EXCL_DETERMINANT`/`_EXCLUSION_GRID` cite `10.5.pd5e` as the determinant for the `_P4_BOTH_ENDS_GLOB` row across all 14 `_TARGETS` (including non-host IPv6/bucket/ARN/bundle), and the existing row-uniform test checks only clause-string equality. This brief turns the host-identity-only scope into a **tested conformance assertion**. **G1 untouched; G3 not relaxed.** Test-only; no product behaviour changed.

## 1. The defect
The both-ends-glob PD-5 branch lives in `_matches_hostname_pattern` (`src/kronos/scope_guard.py:511`), which is shape-gated at `:515` — `if shape not in ("url", "host", "host_port"): return False` — so it never reaches `ip`, `ip_port`, `bucket_name`, `arn`, `bundle_id`. Per `SPEC_BRIEF10.5` §1.3 (PD-5): the both-ends glob compares **HOST identity only**. No test asserts this host-vs-non-host restriction; the only statement of it is an untested rationale comment near `_EXCL_DETERMINANT` in `tests/test_scope_guard.py`. So nothing fails if a future change widened PD-5 to a non-host shape.

## 2. The correction (approach)
Add ONE conformance test (test-only) asserting the host-identity-only scope of the PD-5 both-ends-glob branch directly against `_matches_hostname_pattern`. **No product code changes. No edit to the `_EXCL_DETERMINANT` comment or `_EXCLUSION_GRID`** (that row-level citation is the Option-A-accepted known limit, SEQ 43 — out of scope here). Expected values derive from `SPEC_BRIEF10.5` §1.3 PD-5 **prose** ("host identity only"), never from observed behaviour.

**Pre-build probe (orchestrator, read-only):** `_matches_hostname_pattern` @ `:511`, gate @ `:515` to `("url","host","host_port")`; `_P4_BOTH_ENDS_GLOB = "*.acme.com*"` present in `tests/test_scope_guard.py`. The asserted behaviour already holds, so the test is a conformance/characterization test; its validity is proven by a transient mutation (below), not by a RED-then-fix cycle.

## 3. Permitted files (only these may change)
- `tests/test_scope_guard.py`

Not permitted: `src/kronos/scope_guard.py`, `src/kronos/schema.py`, any other product code, `.claude/`, `.github/`, `src/kronos/manifest.py`, or anything under `cybergym/`.

## 5. Tests (the deliverable)
1. New test `test_b1010_fc_pd5_both_ends_glob_is_host_identity_only`:
   - pattern = `_P4_BOTH_ENDS_GLOB` (`"*.acme.com*"`).
   - For each **host-ish** shape in `("url", "host", "host_port")`, with a target whose host component matches the glob (e.g. host `"x.acme.com"`, host_port `"x.acme.com:443"`, url `"https://x.acme.com/p"`), assert `_matches_hostname_pattern(pattern, target, shape, is_exclusion=True)` is **True**.
   - For each **non-host** shape in `("ip", "ip_port", "bucket_name", "arn", "bundle_id")`, with any target, assert the call returns **False** — PD-5 does not reach non-host identities (prose: `SPEC_BRIEF10.5` §1.3, host identity only). Cite the clause in a comment.
   - The test is discriminating by construction: at least one host shape returns True and every non-host shape returns False for the same pattern, so removing the `:515` gate would flip the non-host assertions red.
2. **Validity (RED) evidence:** capture a transient mutation — temporarily relax the `:515` shape gate (uncommitted, reverted immediately) and confirm the non-host assertions go red — to prove the test can fail. Do **not** commit the mutation.
3. Regression: the full `tests/test_scope_guard.py` suite stays green; no existing test weakened; `_EXCL_DETERMINANT`/`_EXCLUSION_GRID` and the row-uniform test are untouched.

## 6. Live-use gate
Not applicable. Test-only; no product behaviour changes; §6 (live-use) is not engaged.

## 8. Acceptance criteria
1. `rtk test` `SUMMARY:` line shows **0 failed** (decide PASS/FAIL from the SUMMARY line, never the exit code).
2. `test_b1010_fc_pd5_both_ends_glob_is_host_identity_only` is present, asserts False for all five non-host shapes and True for at least one host shape, and its expected values cite `SPEC_BRIEF10.5` §1.3 PD-5.
3. RED evidence captured: a transient shape-gate mutation flips the non-host assertions red (reverted, not committed).
4. `git diff --name-only d71ebf6..HEAD` is exactly `tests/test_scope_guard.py` (the brief doc `SPEC_BRIEF10.10.md` is committed separately by the orchestrator and is not part of the builder's §3 diff).
5. No live network; no traffic outside the CyberGym range (no `socket`/`urllib`/`requests`/`httpx` added).

This is §8 acceptance-grounding of existing behaviour. Not a §6 live-use change.
