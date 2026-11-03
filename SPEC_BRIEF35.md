# SPEC_BRIEF35 — G3: lock the evidence-gate invariant (regression test) + abstain-confidence assertion

**Goal (G3):** fewer false positives. BRIEF32–34 made every forward advance of a FINDING to
`reachable` evidence-gated (dispatcher, web, infra, secret/invalidation). That uniformity is
currently true only by inspection. This brief locks it with a **structural regression test**, so a
future producer that advances a FINDING to `reachable`/`exploited` without first attaching evidence
fails the suite. It also closes a prose/test gap from BRIEF34 (§5): assert the abstained FINDING's
confidence is not the unbacked-`reachable` value 7 (it keeps the create default 0, never
lifecycle-scored). **Tests-only — no `src` change.**

**Policy reference (R8).** Global gates, rails, and hard boundaries are `CLAUDE.md` §4 + the v7
contract. This brief restates only brief-specific content.

## 1. Base / window
- Brief base: `a0395c5` (main, merge of BRIEF34).
- Branch: `claude/g3-evidence-gate-regression-brief35`.
- Prior window **sealed**: `7f5f46c..a0395c5` (BRIEF34) — allowed only to its merge SHA (seal-tax,
  §8 AC4).

## 2. Current state (cited, on `a0395c5`)
- Forward advances of a FINDING to `"reachable"` in `src/kronos/**`, each preceded by an
  `attach_evidence(..., target_type="finding")` in the **same function**:
  - `src/kronos/agent/dispatcher.py:173` (gated by `if outcome.succeeded and outcome.evidence is
    not None:` with `attach_evidence` at dispatcher.py:164-172).
  - `src/kronos/validate/web_validator.py:75` (inside `if ... outcome.live and outcome.evidence:`,
    attach at web_validator.py:64-72).
  - `src/kronos/validate/infra_validator.py:74` (same shape).
  - `src/kronos/validate/invalidation.py:48` (inside `if evidence is not None:`, attach at
    invalidation.py:36-44).
- Legitimate exception (NOT a reachable advance): `src/kronos/validate/invalidation.py:63` advances
  to `"requires_revalidation"` — a backward/revalidation state that `lifecycle.py` permits without
  evidence (lifecycle.py:21). It is excluded from the rule.
- No advance to `"exploited"` exists in `src/kronos/**`.
- `src/kronos/lifecycle.py:85-86` — confidence: `reachable` → 9 if evidence else 7; `hypothesis`
  derives its own (non-7) value.

## 3. Permitted files (the ONLY files that may change)
1. `tests/test_finding_evidence_gate.py` — **new**. The structural evidence-gate test (§8 AC1/AC2).
2. `tests/test_invalidation.py` — add the §8 AC3 abstain-confidence assertion.
3. `tests/test_commit_authority.py` — seal-tax (§8 AC4): seal `7f5f46c..a0395c5` to
   `B34_SECTION_10`; add `B35_BASE = "a0395c5"` live audit `a0395c5..HEAD <= B35_SECTION_10`, with
   `B35_SECTION_10 = B34_SECTION_10 | {"SPEC_BRIEF35.md", "tests/test_finding_evidence_gate.py"}`.
   Keep the B30, B32, B33 seals.
4. `SPEC_BRIEF35.md` — this file.

No `src/` change. `src/kronos/manifest.py`, `.github/`, `cybergym/`, `.claude/` are hard-boundary
(`CLAUDE.md` §4) and MUST NOT change.

## 4. Behaviour of the structural test (prose-derived invariant)
Using the `ast` module, parse every `.py` file under `src/kronos/`. The invariant:

> For every function that contains a call `advance_finding_status(..., "reachable")` **or**
> `advance_finding_status(..., "exploited")`, that **same function** must also contain a call to
> `attach_evidence(...)` with a keyword/positional `target_type="finding"`.

- The test derives the expectation from this invariant, not from observed line numbers.
- It additionally pins the set of qualifying call sites (producer functions) to the four known ones
  (dispatcher, web, infra, invalidation) each with a one-line prose citation, so a **new** producer
  must be consciously added to the set — mirroring the repo's `NODE_TYPE_SHAPE_EVIDENCE` pattern.
- `"requires_revalidation"` and any non-`reachable`/`exploited` status are **not** subject to the
  rule.

## 5. Negative cases
- `requires_revalidation` advance (invalidation.py:63) must NOT be flagged (legitimately
  evidenceless).
- The test must be RED-first discriminating: a synthetic source snippet containing a
  `reachable` advance with no `attach_evidence` in the function must be flagged by the same checker
  (proving it is a conformance test, not a no-op).

## 8. Acceptance criteria
- **AC1 (invariant holds on current src):** the `ast`-based checker, run over `src/kronos/**`,
  reports **zero** violations; the set of reachable/exploited-advancing producer functions equals
  the pinned expected set of four, each with its evidence-gate citation. Expected from §2/§4 prose.
- **AC2 (checker discriminates — RED-first):** the same checker, applied to an in-test synthetic
  module source that advances a FINDING to `"reachable"` with no `attach_evidence`, returns a
  violation for that synthetic function. (Pure string input; touches no real file.)
- **AC3 (abstain confidence):** after `record_secret_finding` with `evidence=None`, the FINDING
  stays at `hypothesis` and its stored `confidence` is **not**
  `lifecycle.derive_confidence("finding", "reachable", has_evidence=False)` (=7) — i.e. it is never
  scored as an unbacked `reachable`. (A `hypothesis` FINDING never passes through lifecycle
  scoring, so it keeps the create-time default (`0`); BRIEF34 §5's implication that the value
  equals the `hypothesis` derive_confidence result (3) was imprecise — this AC asserts what ships,
  deriving the forbidden `reachable` value from `lifecycle` rather than hardcoding it.)
- **AC4 (seal-tax scope audit):** `set(diff --name-only a0395c5..HEAD) <= B35_SECTION_10`, and the
  BRIEF34 window sealed: `set(diff --name-only 7f5f46c..a0395c5) <= B34_SECTION_10` (not `..HEAD`).
  B30/B32/B33 seals remain. `B35_SECTION_10 = B34_SECTION_10 | {"SPEC_BRIEF35.md",
  "tests/test_finding_evidence_gate.py"}`.
- **AC5 (no live network):** every test added is `nonet` (or uses the module's socket-blocking
  fixture); no traffic outside the CyberGym range. §6 live-run stays PAUSED.
- **AC6 (suite):** full suite `0 failed` (decide from the `SUMMARY:` line, never `$?`). Record the
  measured total as the final edit.

## 9. Exit conditions
- All §8 AC pass; suite `0 failed`; scope audit `a0395c5..HEAD ⊆ B35_SECTION_10`; independent Haiku
  reviewer PASS. No `src/` or out-of-§3 file changed. No live/§6 execution.

Build note (builder): AC1-AC4 implemented, tests-only; full suite SUMMARY: 3959 passed, 1 skipped, 0 failed. Matcher tightened (attach target_type kw or positional index 4); re-run: 3959 passed, 1 skipped, 0 failed.
