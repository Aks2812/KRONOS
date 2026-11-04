# SPEC_BRIEF36 — G3: severity chokepoint — enum allowlist at the graph mutation authority

**Goal (G3):** fewer false positives. The `severity` column of a FINDING is a free-form `STRING`
(`schema.py:88`) with no allowlist anywhere. Any producer can write an arbitrary severity
(`"critical"`, `"urgent"`, a typo) and the graph mutation authority accepts it. This brief closes
that gap with a **fail-closed enum guard at the single commit chokepoint**
(`GraphMutationAuthority.create_or_update_node`), matching the module's existing unknown-column
guard. **Option A (enum-only):** the guard validates that a written `severity` is a legal level; it
does **not** add an evidence-tie (that is a separate, larger invariant, explicitly out of scope).

**Policy reference (R8).** Global gates, rails, and hard boundaries are `CLAUDE.md` §4 + the v7
contract. This brief restates only brief-specific content.

## 1. Base / window
- Brief base: `329194c` (main, merge of BRIEF35 / PR #42).
- Branch: `claude/severity-enum-chokepoint-brief36`.
- Prior window **sealed**: `a0395c5..329194c` (BRIEF35) — allowed only to its merge SHA
  (seal-tax, §8 AC4).

## 2. Current state (cited, on `329194c`)
- `src/kronos/schema.py:88` — `FINDING` schema: `... title STRING, severity STRING, status STRING,
  confidence INT64, ...`. `severity` is an unconstrained STRING.
- `src/kronos/schema.py:176` — `"FINDING": {"source", "title", "severity"}` (required props).
- Every severity value produced in `src/kronos/**` is `"info"`:
  - `src/kronos/agent/dispatcher.py:64`
  - `src/kronos/validate/web_validator.py:57`
  - `src/kronos/validate/infra_validator.py:56`
  - `src/kronos/validate/invalidation.py:28`
- Commit chokepoint: `src/kronos/commit.py:82` `GraphMutationAuthority.create_or_update_node`.
  It already fail-closes on unknown node type (`:92`) and non-whitelisted columns (`:105`,
  `raise ValueError`). The severity guard belongs in the same method, same style.
- `src/kronos/commit.py:12` already `from enum import Enum`.
- Severity values used in `tests/**`: `"info"`, `"low"`, `"high"` — all legal under §3's allowlist
  (verified; the guard breaks no existing test).

## 3. Permitted files (the ONLY files that may change)
1. `src/kronos/commit.py` — define `SEVERITY_LEVELS` and add the guard in `create_or_update_node`.
2. `tests/test_commit_severity.py` — **new**. §8 AC1/AC2/AC3 tests.
3. `tests/test_commit_authority.py` — seal-tax only (§8 AC4).
4. `SPEC_BRIEF36.md` — this file.

No other `src/` file changes. `src/kronos/manifest.py`, `src/kronos/schema.py`, `.github/`,
`cybergym/`, `.claude/` are hard-boundary (`CLAUDE.md` §4) and MUST NOT change. (The allowlist is a
commit-authority concern, so it lives in `commit.py`, not in the schema.)

## 4. Behaviour of the guard
- Define `SEVERITY_LEVELS = frozenset({"info", "low", "medium", "high", "critical"})` in
  `commit.py`.
- In `create_or_update_node`, after the existing unknown-column check, when `props` contains a
  `"severity"` key, reject a value not in `SEVERITY_LEVELS`:
  `raise ValueError(f"severity {value!r} not in {sorted(SEVERITY_LEVELS)}")`.
- The guard fires for any node type whose props carry `severity` (today: FINDING). It does not
  require severity to be present, and it does not touch any other column.
- **No evidence-tie, no confidence coupling, no ordering/ranking** — those are out of scope
  (Option A).

## 5. Negative / positive cases
- Positive: each of the five legal levels on a FINDING `create_or_update_node` is accepted (no
  raise).
- Negative: an illegal severity (e.g. `"urgent"`) on a FINDING `create_or_update_node` raises
  `ValueError`, and no node is written (fail-closed, before the batched `_run`).
- Regression: the existing producers' `"info"` path still commits.

## 8. Acceptance criteria
- **AC1 (rejects illegal):** `create_or_update_node("FINDING", ..., props={..., "severity":
  "urgent"}, source=<valid>)` raises `ValueError`; the graph gains no FINDING from the call.
- **AC2 (accepts every legal level):** for each `s` in `SEVERITY_LEVELS`, a FINDING
  `create_or_update_node` with `severity=s` succeeds and the node is present with that severity.
- **AC3 (no regression on producers):** a FINDING committed with `severity="info"` (the existing
  producer value) still succeeds; a `create_or_update_node` for a node type with **no** severity
  prop is unaffected.
- **AC4 (seal-tax scope audit):** in `tests/test_commit_authority.py`:
  add `B36_BASE = "329194c"`; change the BRIEF35 live audit to the **sealed** form
  `set(names(f"{B35_BASE}..{B36_BASE}")) <= B35_SECTION_10`; add the new live audit
  `set(names(f"{B36_BASE}..HEAD")) <= B36_SECTION_10` with
  `B36_SECTION_10 = B35_SECTION_10 | {"SPEC_BRIEF36.md", "src/kronos/commit.py",
  "tests/test_commit_severity.py"}`. Keep the B31/B32/B33/B34/B35 seals unchanged.
- **AC5 (no live network):** every test added is `nonet` (or uses the socket-blocking fixture); no
  traffic outside the CyberGym range. §6 live-run stays PAUSED (SEQ 140).
- **AC6 (suite):** full suite `0 failed` (decide from the `SUMMARY:` line, never `$?`). Record the
  measured total as the final edit.

## 9. Exit conditions
- All §8 AC pass; suite `0 failed`; scope audit `329194c..HEAD ⊆ B36_SECTION_10`; independent Haiku
  reviewer PASS. No out-of-§3 file changed; `schema.py` unchanged. No live/§6 execution.
