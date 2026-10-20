# SPEC_BRIEF10.10.md — Finding F-C: PD-5's host-identity-only scope must be tested, not asserted only in an untested comment

**Status:** APPROVED at GATE-1 by the orchestrator (Opus self-approval under the maintainer-authorized full-autonomy model — `CLAUDE.md` "Authority model"; `kronos/loop-state:docs/loop/PROGRESS.md` SEQ 55–56). Brief authored by the orchestrator this session.
**Stage:** FORK-2. **Derives from:** Finding **F-C** (LOW), recorded SEQ 42/43 as a deferred follow-up to `SPEC_BRIEF10.7` (Option A).
**Lands on:** `claude/finding-c-brief10-10`, base `d71ebf6` (current `main`; contains 10.7 + 10.8). Independent of the parked 10.9 — append-only; does not edit the F-B determinant comment or grid.

## 0. Goal justification
Primary **G2 (MORE EFFECTIVE):** closes a grounding gap. PD-5 (`10.5.pd5e`, the both-ends-glob exclusion) is **host-identity only**, but that scope is stated in code and in an **untested** rationale comment, while `_EXCL_DETERMINANT`/`_EXCLUSION_GRID` cite `10.5.pd5e` as the determinant for the `_P4_BOTH_ENDS_GLOB` row across all 14 `_TARGETS` (including non-host IPv6/bucket/ARN/bundle), and the existing row-uniform test checks only clause-string equality. This brief turns the host-identity-only scope into a **tested conformance assertion**. **G1 untouched; G3 not relaxed.** Test-only; no product behaviour changed.

## 1. The defect
The both-ends-glob PD-5 branch lives in `_matches_hostname_pattern` (`src/kronos/scope_guard.py:511`), which is shape-gated at `:515` — `if shape not in ("url", "host", "host_port"): return False` — so it never reaches `ip`, `ip_port`, `bucket_name`, `arn`, `bundle_id`. Per `SPEC_BRIEF10.5` §1.3 (PD-5): the both-ends glob compares **HOST identity only**. No test asserts this host-vs-non-host restriction; the only statement of it is an untested rationale comment near `_EXCL_DETERMINANT` in `tests/test_scope_guard.py`. So nothing fails if a future change widened PD-5 to a non-host shape.

## 2. The correction (approach)
Add ONE conformance test (test-only) asserting the **function-level `:515` gate contract** of `_matches_hostname_pattern`: for any shape outside `("url","host","host_port")`, the function returns `False` (the PD-5 both-ends-glob branch is never reached). This grounds the gate line, not a system-wide semantic claim. **No product code changes. No edit to the `_EXCL_DETERMINANT` comment or `_EXCLUSION_GRID`** (that row-level citation is the Option-A-accepted known limit, SEQ 43 — out of scope). Expected values derive from `SPEC_BRIEF10.5` §1.3 PD-5 **prose** ("host identity only") and the `:515` gate contract, never from observed behaviour.

**Scope of the claim (honest, per SEQ 57/58 ruling R2):** this is a function-level assertion about the `:515` gate only. Of the five non-host shapes, **only `bucket_name` is SOLELY gate-determined** — removing the gate flips its result (the RED case). For `ip`/`ip_port`/`arn`/`bundle_id` the result is `False` under the gate but *also* for a downstream reason (their host-extraction yields no glob-matching host), so they are not solely gate-determined; they are included as the full enumeration of the gate's excluded shapes, not as independent gate evidence. Separately, **H3** (`SPEC_BRIEF10.3`; `src/kronos/scope_guard.py:397-402` and `:669 _HOST_SHAPES_FOR_EXCLUSION`) treats `bucket_name` as host on the exclusion path at a **higher layer** — that routing is out of scope for this function-level assertion, and this test makes no claim about it.

**Pre-build probe (orchestrator, read-only):** `_matches_hostname_pattern` @ `:511`, gate @ `:515` to `("url","host","host_port")`; `_P4_BOTH_ENDS_GLOB = "*.acme.com*"` present in `tests/test_scope_guard.py`. The asserted behaviour already holds, so the test is a conformance/characterization test; its validity is proven by a transient mutation of the gate (below), which flips the `bucket_name` assertion.

## 3. Permitted files (only these may change)
- `tests/test_scope_guard.py`

Not permitted: `src/kronos/scope_guard.py`, `src/kronos/schema.py`, any other product code, `.claude/`, `.github/`, `src/kronos/manifest.py`, or anything under `cybergym/`.

## 5. Tests (the deliverable)
1. New test `test_b1010_fc_pd5_hostname_pattern_gate_is_host_shapes_only`:
   - pattern = `_P4_BOTH_ENDS_GLOB` (`"*.acme.com*"`).
   - For each **host** shape in `("url", "host", "host_port")`, with a target whose host component matches the glob (e.g. host `"x.acme.com"`, host_port `"x.acme.com:443"`, url `"https://x.acme.com/p"`), assert `_matches_hostname_pattern(pattern, target, shape, is_exclusion=True)` is **True**.
   - For each shape in `("ip", "ip_port", "bucket_name", "arn", "bundle_id")` (the full set outside the host-shape gate), assert the call returns **False** — the `:515` gate short-circuits non-host shapes (the PD-5 both-ends-glob branch is never reached). Comment must: (a) cite `SPEC_BRIEF10.5` §1.3 PD-5 "host identity only"; (b) state this asserts the function-level `:515` gate contract, not a system-wide identity claim; (c) note that **only `bucket_name` is solely gate-determined** here, and that **H3** (`SPEC_BRIEF10.3`) treats `bucket_name` as host on the exclusion path at a higher layer, out of scope for this test.
2. **Validity (RED) evidence:** capture a transient mutation — temporarily relax the `:515` gate (uncommitted, reverted immediately) and confirm the **`bucket_name`** assertion goes red — to prove the gate is what the test pins. Do **not** commit the mutation. (The `ip`/`ip_port`/`arn`/`bundle_id` assertions are not expected to flip, because their host-extraction yields no glob-matching host; that is stated, not hidden.)
3. Regression: the full `tests/test_scope_guard.py` suite stays green; no existing test weakened; `_EXCL_DETERMINANT`/`_EXCLUSION_GRID` and the row-uniform test are untouched.
4. Prefer a top-level import for `_matches_hostname_pattern` consistent with the file's existing imports; avoid a mid-file `# noqa: E402` import if a clean top-level one is available.

## 6. Live-use gate
Not applicable. Test-only; no product behaviour changes; §6 (live-use) is not engaged.

## 8. Acceptance criteria
1. `rtk test` `SUMMARY:` line shows **0 failed** (decide PASS/FAIL from the SUMMARY line, never the exit code).
2. `test_b1010_fc_pd5_hostname_pattern_gate_is_host_shapes_only` is present, asserts False for all five shapes outside the host-shape gate (`ip`,`ip_port`,`bucket_name`,`arn`,`bundle_id`) and True for at least one host shape, and its comment (a) cites `SPEC_BRIEF10.5` §1.3 PD-5, (b) frames the assertion as the function-level `:515` gate contract, and (c) notes only `bucket_name` is solely gate-determined and that H3 treats `bucket_name` as host at a higher layer (out of scope).
3. RED evidence captured: a transient `:515` gate mutation flips the **`bucket_name`** assertion red (reverted, not committed). The brief does not claim the other four non-host assertions flip.
4. The builder's committed code diff is exactly `tests/test_scope_guard.py`. `git diff --name-only d71ebf6..HEAD` additionally shows `SPEC_BRIEF10.10.md` (the orchestrator-authored brief, separate commits e870aaa + this amendment); that is expected and is not a §3 violation.
5. No live network; no traffic outside the CyberGym range (no `socket`/`urllib`/`requests`/`httpx` added).

This is §8 acceptance-grounding of existing behaviour. Not a §6 live-use change.
