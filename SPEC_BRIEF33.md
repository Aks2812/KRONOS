# SPEC_BRIEF33 — G3 evidence persistence for web/infra validator findings

**Goal (G3):** fewer false positives — findings must be evidence-backed. The secret
validator path persists its differential proof as an `EVIDENCE` graph node before
advancing a FINDING; the **web** and **infra** validator paths do not. They compute
equivalent proof bytes (`outcome.evidence`) but never call `attach_evidence`, so their
FINDINGs reach `status="reachable"` with proof living only in the ephemeral
`ValidationOutcome`. This brief makes web/infra findings persist their evidence the same
way, closing the inconsistency.

**Policy reference (R8).** Global gates, rails, and hard boundaries are
`CLAUDE.md` §4 + the v7 contract (`docs/loop/KRONOS_LOOP_ARCHITECTURE_v7.md`). This brief
restates only brief-specific content.

## 1. Base / window
- Brief base: `cf9293b` (main, merge of BRIEF31+BRIEF32).
- Branch: `claude/g3-evidence-persistence-brief33`.
- Prior window **sealed**: `a229b0d..cf9293b` (BRIEF31+BRIEF32) — its files are allowed only
  up to its merge SHA, not `..HEAD` (seal-tax, see §8 AC6).

## 2. Current behaviour (cited)
- `src/kronos/validate/runner.py:223-231` — secret path calls `attach_evidence(graph,
  engagement_dir, outcome.evidence, kind="validation_proof", target_type="secret", ...)`
  before the edge + status advance.
- `src/kronos/validate/web_validator.py:45-63` `record_web_finding` and
  `src/kronos/validate/infra_validator.py:44-61` `record_infra_finding` — advance a FINDING to
  `"reachable"` but **never** call `attach_evidence`; `outcome.evidence` (web_validator.py:32-34,
  infra_validator.py:31-33) is discarded.
- `src/kronos/lifecycle.py` report gate requires `>=1` EVIDENCE node to report a FINDING.
- `src/kronos/evidence.py:58` `attach_evidence(graph, engagement_dir, blob, kind,
  target_type, target_id, *, source)` — `target_type` accepts `"finding"`.

## 3. Permitted files (the ONLY files that may change)
1. `src/kronos/validate/web_validator.py` — add keyword-only `engagement_dir: str | Path | None
   = None` to `record_web_finding` and to `run_web_validation_pass` (threaded to
   `record_web_finding`). When `engagement_dir is not None` **and** `outcome is not None` **and**
   `outcome.evidence` is truthy, call `attach_evidence(engagement, engagement_dir,
   outcome.evidence, kind="validation_proof", target_type="finding", target_id=finding_id,
   source=MutationSource.VALIDATION)` **before** the status advance. No other behaviour change.
2. `src/kronos/validate/infra_validator.py` — the identical change to `record_infra_finding` and
   `run_infra_validation_pass`.
3. `src/kronos/agent/live_executor.py` — pass `self._engagement_dir` as `engagement_dir=` to the
   `record_infra_finding` (line 67) and `record_web_finding` (line 86) calls. Wiring only; no live
   execution (§6 remains paused).
4. `tests/test_web_validator.py` — add the §8 AC1/AC3/AC4 assertions.
5. `tests/test_infra_validator.py` — add the §8 AC2/AC3/AC4 assertions.
6. `tests/test_commit_authority.py` — seal-tax (§8 AC6): seal `a229b0d..cf9293b` to
   `B32_SECTION_10`, and add a `B33_BASE = "cf9293b"` live audit `cf9293b..HEAD <= B33_SECTION_10`.
7. `SPEC_BRIEF33.md` — this file.

No file outside this list may change. `src/kronos/manifest.py`, `.github/`, `cybergym/`,
`.claude/` are hard-boundary (`CLAUDE.md` §4) and MUST NOT change.

## 4. Behaviour
- A **live** web/infra finding (`outcome.live`) recorded with an `engagement_dir` persists its
  proof: one `EVIDENCE` node (sha256 of `outcome.evidence`, `kind="validation_proof"`) linked to
  the FINDING via an `evidences` edge, written with `source=MutationSource.VALIDATION`, **before**
  the FINDING advances to `"reachable"`.
- **Abstention unchanged.** Non-live outcomes already never reach `record_*_finding` (the pass
  fns append to `abstained`); no evidence is attached.
- **Backward-compatible.** With `engagement_dir=None` or `outcome=None`, no evidence is attached
  and the write count is unchanged (preserves `test_commit_authority.py:363`
  `test_B32_validator_paths_live_emit_VALIDATION`, which expects exactly 2 mutations).

## 5. Negative cases
- `record_web_finding`/`record_infra_finding` called with `outcome=None` → no `attach_evidence`,
  no EVIDENCE node.
- `engagement_dir=None` → no `attach_evidence`.
- No new network: evidence is derived from already-captured `outcome.evidence` bytes; no probe
  re-run.

## 8. Acceptance criteria
- **AC1 (web persistence):** after `record_web_finding(g, endpoint_id, live_outcome,
  engagement_dir=d)`, an `EVIDENCE` node whose `sha256` == sha256 of `live_outcome.evidence`
  exists and is linked to the FINDING via `evidences`. Expected from §4 prose.
- **AC2 (infra persistence):** same for `record_infra_finding`.
- **AC3 (no evidence without inputs):** `record_web_finding`/`record_infra_finding` with
  `outcome=None` (and/or `engagement_dir=None`) create **no** EVIDENCE node; the existing
  source-identity spy still sees exactly 2 VALIDATION mutations.
- **AC4 (report gate satisfied):** a web/infra FINDING carrying the persisted EVIDENCE node
  satisfies the `lifecycle.py` `>=1 EVIDENCE node` report gate (assert `_evidence_count` for the
  finding `>= 1`).
- **AC5 (attribution):** the EVIDENCE node + `evidences` edge are written with
  `MutationSource.VALIDATION`.
- **AC6 (seal-tax scope audit):** in `tests/test_commit_authority.py`,
  `set(diff --name-only cf9293b..HEAD) <= B33_SECTION_10`, and the BRIEF31/BRIEF32 window is
  sealed: `set(diff --name-only a229b0d..cf9293b) <= B32_SECTION_10` (not `..HEAD`).
  `B33_SECTION_10 = B32_SECTION_10 | {brief §3 paths}`.
- **AC7 (no live network):** every test added is `nonet`; assert no traffic outside the CyberGym
  range. §6 live-run stays PAUSED.
- **AC8 (suite):** full suite `0 failed` (read `SUMMARY:` line, not `$?` — `CLAUDE.md` §3). Record
  the measured total as the final edit.

## 9. Exit conditions
- All §8 AC pass; suite `0 failed`; scope audit `cf9293b..HEAD ⊆ B33_SECTION_10`; independent
  Haiku reviewer PASS. No file outside §3 changed. No live/§6 execution.
