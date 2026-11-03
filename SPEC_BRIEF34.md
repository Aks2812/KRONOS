# SPEC_BRIEF34 — G3: abstain instead of reaching a secret-access FINDING without evidence

**Goal (G3):** fewer false positives — a FINDING may only advance to `reachable` when it is
evidence-backed; otherwise abstain. `record_secret_finding`
(`src/kronos/validate/invalidation.py`) attaches evidence only `if evidence is not None`, but
then advances the FINDING to `"reachable"` **unconditionally**. With `evidence is None` this
produces a `reachable` FINDING (confidence 7) carrying **no EVIDENCE node** — a false positive.
Every other forward-advance producer already gates the advance on evidence (dispatcher.py:163-173,
web_validator.py:62-75, infra_validator.py:62-74, all post-BRIEF33). This brief makes the secret
path consistent: advance only when evidence was attached; otherwise leave the FINDING at
`hypothesis` (abstain).

**Policy reference (R8).** Global gates, rails, and hard boundaries are `CLAUDE.md` §4 + the v7
contract (`docs/loop/KRONOS_LOOP_ARCHITECTURE_v7.md`). This brief restates only brief-specific
content.

## 1. Base / window
- Brief base: `7f5f46c` (main, merge of BRIEF33).
- Branch: `claude/g3-invalidation-evidence-gate-brief34`.
- Prior window **sealed**: `cf9293b..7f5f46c` (BRIEF33) — allowed only up to its merge SHA, not
  `..HEAD` (seal-tax, §8 AC4).

## 2. Current behaviour (cited)
- `src/kronos/validate/invalidation.py:35-44` — `attach_evidence(...)` runs only `if evidence is
  not None`.
- `src/kronos/validate/invalidation.py:46-47` — the advance to `"reachable"` runs
  **unconditionally** (guarded only by the create-only `status == "hypothesis"` re-run check), so
  `evidence is None` yields `reachable` with no EVIDENCE node.
- Contrast (all gate the advance on evidence): `src/kronos/agent/dispatcher.py:163`
  (`if outcome.succeeded and outcome.evidence is not None:` then attach, then advance),
  `src/kronos/validate/web_validator.py:63` / `infra_validator.py:62`
  (`... and outcome.live and outcome.evidence` then attach then advance).

## 3. Permitted files (the ONLY files that may change)
1. `src/kronos/validate/invalidation.py` — in `record_secret_finding`, advance to `"reachable"`
   **only when evidence was attached** (i.e. only inside / gated by the existing `evidence is not
   None` condition). When `evidence is None`, do **not** advance; leave the FINDING at
   `"hypothesis"`. No other behaviour change; the create-only re-run guard is preserved.
2. `tests/test_invalidation.py` — add the §8 AC1/AC2 assertions.
3. `tests/test_commit_authority.py` — seal-tax (§8 AC4): seal `cf9293b..7f5f46c` to
   `B33_SECTION_10`, and add `B34_BASE = "7f5f46c"` live audit `7f5f46c..HEAD <= B34_SECTION_10`,
   with `B34_SECTION_10 = B33_SECTION_10 | {"SPEC_BRIEF34.md"}`. Keep the B30 and B32 seals.
4. `SPEC_BRIEF34.md` — this file.

No file outside this list may change. `src/kronos/manifest.py`, `.github/`, `cybergym/`,
`.claude/` are hard-boundary (`CLAUDE.md` §4) and MUST NOT change.

## 4. Behaviour
- `record_secret_finding(..., evidence=E, engagement_dir=D)` with **E not None**: unchanged —
  attach evidence (EVIDENCE node, `evidences` edge, `MutationSource.VALIDATION`), then advance to
  `"reachable"`.
- `record_secret_finding(..., evidence=None, ...)`: **abstain** — create the FINDING at
  `"hypothesis"` with its edges (`derived_from`, `vulnerable_to`) as today, attach no evidence, and
  **do not advance**; the FINDING stays at `"hypothesis"`.
- Idempotent re-run unchanged: a FINDING already advanced is not re-advanced.
- The real validator caller (`runner.py` live branch) always passes non-None `outcome.evidence`, so
  the discriminated/live path is unchanged.

## 5. Negative cases
- `evidence=None` → no EVIDENCE node, FINDING `status == "hypothesis"` (abstention), confidence
  reflects `hypothesis`, not the 7 of an unbacked `reachable`.
- No new network: the fix only reorders/guards an existing advance; no probe or traffic.

## 8. Acceptance criteria
- **AC1 (evidence → reachable + persisted):** after `record_secret_finding` with non-None
  `evidence` and a real `engagement_dir`, the FINDING `status == "reachable"` **and**
  `_evidence_count(graph, "finding", finding_id) >= 1`. Expected from §4 prose.
- **AC2 (no evidence → abstain):** after `record_secret_finding` with `evidence=None`, the FINDING
  `status == "hypothesis"` (not `"reachable"`) **and** `_evidence_count(...) == 0` (no EVIDENCE
  node). This is the RED-first discriminating case: it fails against the pre-fix unconditional
  advance.
- **AC3 (no live network):** every test added is `nonet`; assert no traffic outside the CyberGym
  range. §6 live-run stays PAUSED.
- **AC4 (seal-tax scope audit):** in `tests/test_commit_authority.py`,
  `set(diff --name-only 7f5f46c..HEAD) <= B34_SECTION_10`, and the BRIEF33 window is sealed:
  `set(diff --name-only cf9293b..7f5f46c) <= B33_SECTION_10` (not `..HEAD`). The B30 and B32 seals
  remain. `B34_SECTION_10 = B33_SECTION_10 | {"SPEC_BRIEF34.md"}`.
- **AC5 (suite):** full suite `0 failed` (decide from the `SUMMARY:` line, never `$?` —
  `CLAUDE.md` §3). Record the measured total as the final edit.

## 9. Exit conditions
- All §8 AC pass; suite `0 failed`; scope audit `7f5f46c..HEAD ⊆ B34_SECTION_10`; independent
  Haiku reviewer PASS. No file outside §3 changed. No live/§6 execution.

_Build note: full suite SUMMARY: 3955 passed, 1 skipped, 0 failed (builder run, pre-review)._
