# SPEC_BRIEF50 — F1: schema-backed stop-report validation (jsonschema)

contract_version: 1.4.0
origin: AUTO-BRIEF (§13.1), operator-authorized follow-up F1 from PR#53 review
base: main @ 8f42638
decision_class: REVIEW-REQUIRED (test + dependency change; draft PR, operator merge-gate)

## §0 Problem
PR#53 reviewer finding F1 (low): the stop-report validation tests in
`tests/test_rnd_contract.py` exercise stdlib *mirrors* (`_validate_report`,
`_validate_v140`, `_validate_discriminated`) that re-implement the schema logic in
Python. They never validate against the real `docs/governance/stop_report.schema.json`
via a JSON-Schema engine, because `jsonschema` is absent from `.venv`. The mirror can
silently drift from the schema; AC1 evidence is "correct by inspection" only.

## §1 Goal
Exercise the REAL schema with a JSON-Schema engine so positive reports validate and
negative reports are rejected by `stop_report.schema.json` itself, and assert the
stdlib mirror and the real schema agree (drift guard). Keep the stdlib mirrors.

## §2 Permitted files (hard scope)
- `requirements.txt`
- `pyproject.toml`
- `tests/test_rnd_contract.py`
- `tests/test_commit_authority.py` — SEAL-TAX ONLY (amended after PR#53-reviewer-pattern
  review): extend `AB_SECTION_10` to list this brief's two new paths
  (`pyproject.toml`, `requirements.txt`), matching the existing `B32`/`B36` precedent. No
  audit-logic change, no base re-seal.

NO other file. Explicitly forbidden: `docs/governance/stop_report.schema.json`
(byte-identical to base), `docs/governance/KRONOS_RND_CONTRACT.md`,
`docs/governance/contract_manifest.json`, `.claude/**`, `.github/**`, `cybergym/**`.

## §3 Seal-tax
Prior brief SPEC_BRIEF49 scope window is sealed to its squash-merge SHA `8f42638`
(PR#53 MERGED 2026-11-12T04:44:29Z). This brief's scope audit is `8f42638..HEAD`.

The cumulative `test_commit_authority.py::test_B31_Q_scope_audit` window `AB_BASE(3f6dbc3)..HEAD`
must list this brief's new paths in `AB_SECTION_10`; see §2 seal-tax amendment.

## §5 Approach
1. Pin `jsonschema` (exact version, top-level only — match repo's direct-pin style; let
   transitive deps resolve) in both `requirements.txt` and `pyproject.toml`
   `[project.optional-dependencies].dev`.
2. In `tests/test_rnd_contract.py` add a `jsonschema`-backed validator using
   `Draft202012Validator` loaded from `docs/governance/stop_report.schema.json`.
3. Run the existing positive/negative vectors through the REAL schema; assert the real
   schema and the stdlib mirror agree (no drift) on each.

## §8 Acceptance criteria
- AC1: `jsonschema` pinned exact in `requirements.txt` AND in `pyproject.toml` dev extra;
  version string identical in both.
- AC2: `.venv/bin/python -c "import jsonschema"` succeeds.
- AC3: new tests load `stop_report.schema.json` and validate via
  `jsonschema.Draft202012Validator`; every positive report object used by the existing
  mirror tests (base PAUSE legacy 1.3.0/1.3.1/1.3.2, exact 1.4.0, 1.4.0-with-ledger-entry)
  validates against the real schema.
- AC4: every negative vector already covered by the mirror tests
  (missing/non-string/unknown/malformed `contract_version`; missing `when.milestone`,
  `effort_justification`, `how.reference_ledger`; invalid `decision_class`) is REJECTED
  by the real schema via jsonschema.
- AC5: a drift-guard test asserts mirror verdict == real-schema verdict across the full
  positive+negative vector set.
- AC6: `docs/governance/stop_report.schema.json` byte-identical to base `8f42638`;
  contract, manifest, `.claude/**` untouched.
- AC7: full canonical suite 0 failed via
  `TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" rtk test .venv/bin/python -m pytest -q`,
  decided from the summary line.
- AC8 (scope): `git diff --name-only 8f42638..HEAD` ⊆ §2 permitted set.
- AC9 (seal-tax): `tests/test_commit_authority.py::test_B31_Q_scope_audit` passes; the only
  change to that file is `AB_SECTION_10` gaining `pyproject.toml` and `requirements.txt`.

## §12 Required tests (in `tests/test_rnd_contract.py`)
1. `test_real_schema_accepts_positive_reports` — all positive vectors validate via jsonschema.
2. `test_real_schema_rejects_negative_reports` — all negative vectors rejected via jsonschema.
3. `test_mirror_and_real_schema_agree` — drift guard over the combined vector set.
