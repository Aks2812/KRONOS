# SPEC_BRIEF32 — Required source identity on graph write facades (G2 audit)

> Compact convention (R8): binding global policy is `CLAUDE.md` §4 + the v7 contract
> + v6 §3.1 MERGE-GATE; only brief-specific content is stated here. Stacks on
> `claude/commit-authority-brief31` @ `7b036fd` (BRIEF31, unmerged). Baseline for the
> combined scope window: main @ `a229b0d`. GATE-1 recorded by Opus (operator
> direction `context.md` 2026-11-02 "option (2)"; BOOTSTRAP decision operator-fixed,
> AskUserQuestion 2026-11-02). Research: SEQ 220 reviewer F2 + Sonnet 5 caller map.

## §1 Objective

Close reviewer finding F2 (SEQ 220): the write facades `upsert_node`/`upsert_edge`
hardcode `MutationSource.INGESTION`, so agent and validation writes are mislabeled and
enum members `DISPATCHER`/`VALIDATION` are dead. Make `source` a **required keyword
argument with no default** on both facades and on the shared helper `attach_evidence`,
and thread each caller's explicit enum identity. Satisfies the operator requirement
"auditable source identity" for every write path. No merge until BRIEF31+BRIEF32 both
pass; then one atomic head-pinned PR.

## §2 Verified baseline (cited)

- Enum `MutationSource` — `src/kronos/commit.py:40-45`; members DISPATCHER, INGESTION,
  VALIDATION, RECONCILIATION, LIFECYCLE. DISPATCHER/VALIDATION dead.
- Facades hardcode INGESTION — `src/kronos/graph.py:68` (`upsert_node`), `:79`
  (`upsert_edge`); no `source` param today. `GraphMutationAuthority` already takes a
  required `source` and calls `_check_source` — `src/kronos/commit.py:76-79,81-92,140-163`.
- Correct direct-`_authority` paths (NOT facades, unchanged): `lifecycle.py:123,129`
  (LIFECYCLE), `reconcile/merge.py:125,129` (RECONCILIATION).
- Facade callers to re-attribute: `validate/invalidation.py:21,31,32`,
  `validate/web_validator.py:46,56`, `validate/infra_validator.py:45,55`,
  `validate/runner.py:230`, `agent/dispatcher.py:60,66,68`, `reconcile/merge.py:102,111`,
  `ingest/__init__.py:119,123`, `graph.py:49` (init_engagement), `evidence.py:69,80`.

## §3 Decisions (operator-fixed / Opus-fixed at GATE-1 — NOT open)

1. `source` becomes a **keyword-only, no-default** param on `graph.upsert_node`,
   `graph.upsert_edge`, and `evidence.attach_evidence`. Omission raises `TypeError`
   (Python) — acceptance also asserts a conformance test proving omission fails.
2. **Add** `BOOTSTRAP = "bootstrap"` to `MutationSource` (`commit.py:40-45`).
   `init_engagement` (`graph.py:49`) passes `MutationSource.BOOTSTRAP` (operator-fixed).
3. Per-caller identity: dispatcher→`DISPATCHER`; validate/*→`VALIDATION`;
   ingest→`INGESTION`; reconcile `_carry_over_edges` (merge.py:102,111)→`RECONCILIATION`;
   init_engagement→`BOOTSTRAP`.
4. `attach_evidence` gains a required `source` param threaded from its callers:
   `dispatcher.py:162`→DISPATCHER; `validate/runner.py:222,236` + `invalidation.py:34`→VALIDATION.
5. Folded F-items — **non-architectural, in-scope only**: F1 doc drift
   (`README_graph.md`, `README_lifecycle.md` claim `execute()` write-capable — correct to
   read-only); F3 remove orphan `_STATUS_BEARING_TYPES` (`reconcile/merge.py:46-52`);
   F6 import order (`lifecycle.py:35-36`). **Not folded** (architectural / judgment):
   F5 cross-module `_authority` access, F7 edge-props exception type.

## §4 Architecture

No new subsystem. Change is purely: (a) one new enum member; (b) three signatures lose
their hardcoded/absent source and require it keyword-only; (c) ~15 production call sites
and ~20 test files pass explicit identity. `GraphMutationAuthority` and the read/write
split from BRIEF31 are unchanged — source already flows through the authority once the
facade stops clamping it.

## §8 Acceptance criteria (this brief's prose)

- **AC1** `graph.upsert_node`/`upsert_edge` and `evidence.attach_evidence` require
  `source` keyword-only, no default; calling without it raises (conformance test).
- **AC2** `MutationSource.BOOTSTRAP` exists; `init_engagement` writes the ENGAGEMENT
  root node attributed BOOTSTRAP (test asserts the stored node's source).
- **AC3** Each write path attributes its correct enum: dispatcher→DISPATCHER,
  validate/*→VALIDATION, ingest→INGESTION, reconcile carry-over→RECONCILIATION,
  lifecycle→LIFECYCLE (unchanged), bootstrap→BOOTSTRAP. Test asserts per-path.
- **AC4** `DISPATCHER` and `VALIDATION` are no longer dead — each is passed by at least
  one production path and asserted live.
- **AC5** No facade and no caller hardcodes `INGESTION` except the genuine ingestion path
  (`ingest/__init__.py`). Test greps `graph.py` for a literal `MutationSource.INGESTION`
  and asserts it is absent from `upsert_node`/`upsert_edge` bodies.
- **AC6** F1 docs corrected: `README_graph.md`/`README_lifecycle.md` no longer claim
  `execute()` is write-capable (test asserts the false phrasing is gone).
- **AC7** Whole-window scope audit `git diff --name-only a229b0d..HEAD ⊆` the §10
  allowlist; BRIEF30 seal `93fb05e..a229b0d` still asserted (carried from BRIEF31 AC7).
- **AC8** `rtk test` SUMMARY: 0 failed. No live network; no traffic outside CyberGym.
  (Net asserted by existing `nonet` fixture.)
- **AC9** Suite total in the final suite row is refreshed as the last edit.

## §9 Exit

All of AC1–AC9 PASS; Haiku independently reviews the combined `a229b0d..HEAD` diff and
reruns the suite; Opus semantic verify; then request atomic head-pinned PR/merge.

## §10 Permitted files (§3 allowlist — binding)

Production:
`src/kronos/commit.py`, `src/kronos/graph.py`, `src/kronos/evidence.py`,
`src/kronos/agent/dispatcher.py`, `src/kronos/validate/invalidation.py`,
`src/kronos/validate/web_validator.py`, `src/kronos/validate/infra_validator.py`,
`src/kronos/validate/runner.py`, `src/kronos/reconcile/merge.py`,
`src/kronos/ingest/__init__.py`, `src/kronos/lifecycle.py`.

Docs: `src/kronos/README_graph.md`, `src/kronos/README_lifecycle.md`.

Brief: `SPEC_BRIEF32.md`.

Tests (add `source=` / new conformance; the scope-audit allowlist set in
`test_commit_authority.py` must be extended to the union of the BRIEF31 §10 set and
every path above, so `a229b0d..HEAD ⊆` it):
`tests/test_commit_authority.py`, `tests/test_agent_commit.py`, `tests/test_lifecycle.py`,
`tests/test_agent_live_executor.py`, `tests/test_validate_runner.py`,
`tests/test_agent_dispatcher.py`, `tests/test_schema_graph.py`,
`tests/test_invalidation.py`, `tests/test_ingest_contract.py`,
`tests/test_negative_controls.py`, `tests/test_budget.py`,
`tests/test_agent_executor.py`, `tests/test_ingest.py`, `tests/test_evidence.py`,
`tests/test_reconcile.py`, `tests/test_mobile_ingest.py`, `tests/test_invariants.py`,
`tests/test_web_ingest.py`, `tests/test_query.py`, `tests/test_validate_candidates.py`.

Plus any BRIEF31 §10 file already in the window (`tests/test_stop.py`,
`SPEC_BRIEF31.md`, `tests/test_scope_guard.py`) remains listed — **nothing outside this
list may change**; audit the whole `a229b0d..HEAD` window, not just expected files.

## §12 Tests (tests-as-rules — write before implementation)

In `tests/test_commit_authority.py` (all `nonet`): (a) `source` omitted on each of the
three signatures raises; (b) per-path attribution matrix (one assert per enum, values
from §3/§8 prose, each cell carrying its path); (c) DISPATCHER/VALIDATION asserted live;
(d) BOOTSTRAP root-node attribution; (e) `graph.py` facade bodies carry no literal
`MutationSource.INGESTION`; (f) extend the scope-audit allowlist set and keep the
`a229b0d..HEAD ⊆ set` + BRIEF30-seal asserts. Expected values derive from this brief's
prose, never from observed behaviour.
