# SPEC_BRIEF R9 — Five-domain integrated engagement run (BE-G1-7)

Roadmap item R9 (`docs/roadmap/KRONOS_ROADMAP.md:27`: five-domain integrated
engagement run). GATE-1 approved by maintainer; helper-scope delegated to the
orchestrator and resolved **test-only** (no `src/kronos/` change). Maps G1
(first usable milestone) and G3 (validation in the same step). DoD predicate
BE-G1-7 (`docs/governance/KRONOS_DONE.md:62`): TEST
`tests/test_five_domain_engagement.py` present, asserting all five domains
ingest into one graph and every resulting FINDING carries a two-armed proof, a
verdict tier, and a control disposition.

## §1 Goal

A single **hermetic** integration test that wires the five ingestion domains —
infra, web, mobile, API, cloud — over fixtures into one `EngagementGraph`, runs
one validation pass with validators patched (no live/network/SDK), and asserts
that the resulting FINDING(s) carry the three required properties. No live
targets, no network, no `src/kronos/` source change. This is a hermetic
milestone per roadmap `:14-15` ("COMPLETE (hermetic) = tested without any
live/manifest-bounded run"); contrast R10 (BE-G3-5) and R12 (BE-G2-6), which
require an authorized manifest-bounded run and are NOT in this brief.

`dns` is a sixth ingest module and is deliberately **not** one of the five
domains (the five are fixed by `KRONOS_RESEARCH_RECORD.md:1327-1328`).

## §2 Permitted files (hard scope)

The builder may create/edit ONLY:

- `tests/test_five_domain_engagement.py`
- `tests/test_commit_authority.py` (seal-tax only — see §4b)

MUST NOT be touched: anything under `src/kronos/**` (this is test-only — see the
§7 tripwire), `docs/`, `.claude/`, `.github/`, `cybergym/`, and any other test
file.

## §3 Fixtures and wiring (all hermetic, in-test)

Build one `EngagementGraph` (follow the fixture pattern in
`tests/test_validate_runner.py` and `tests/test_finding_evidence_gate.py` —
`manifest_factory`, `signing_keypair`, `EngagementGraph.init_engagement`). Then
ingest each of the five domains and apply to that one graph:

- infra: `ingest_infra_nmap(nmap_xml, engagement)` — an nmap XML string fixture.
- web: `ingest_web_openapi(openapi_json, engagement)` — an OpenAPI 3 JSON fixture.
- mobile: `ingest_reference_mobile_secret(bundle_id)` — the reference
  secret-leak example (this is the source of the SECRET that drives validation).
- API: `ingest_api_inventory(inventory_json, engagement)` (R8) — an
  `{"endpoints":[...]}` fixture whose endpoint is the candidate target the leaked
  secret authenticates to.
- cloud: `ingest_cloud_inventory(inventory_json, engagement)` (R7) — a
  `{"provider":...,"resources":[...],"identities":[...],"grants":[...]}` fixture.

Apply via `apply_upserts` / `apply_plan` (`src/kronos/ingest/__init__.py:114`,
`contract.py:118`), exactly as the existing ingest tests do.

## §4 Validation and assertions

Run one `run_validation_pass(graph, engagement_dir)`
(`src/kronos/validate/runner.py:123`) with the relevant validator **patched** to
return a deterministic, discriminated `ValidationOutcome` — mirror
`tests/test_validate_runner.py:154-158`
(`patch("kronos.validate.http_validator.validate_api_token", ...)`). No real
network/boto3 call may occur; add a `nonet`-style guard if the existing tests
have one.

Assert, over the resulting FINDING(s):

1. **All five domains ingested into one graph:** each domain's expected node
   type(s) are present in the single graph (e.g. `HOST`/`SERVICE`,
   `WEB_ENDPOINT`, `MOBILE_APP`/`SECRET`, `API_ENDPOINT`, `CLOUD_RESOURCE`).
2. **Two-armed proof:** each anchored FINDING has linked `EVIDENCE` (the
   `evidences`/`FINDING->EVIDENCE` relation, `schema.py:115,134`) carrying the
   request/response proof bytes written by the validation pass.
3. **Verdict tier:** the driving `ValidationOutcome` is `discriminated=True` with
   `classification == "live_discriminated"` (the runner's structural invariant,
   `validate/types.py`), i.e. the finding rests on a discriminated verdict, not a
   single undiscriminated arm.
4. **Control disposition:** the outcome's `control_outcome` is recorded
   (non-empty), i.e. the control arm's disposition is captured.

Map the three DoD properties onto these existing structures; introduce no new
schema column or source function. Assert via the public read API / graph
queries as the other validate tests do.

## §4b Seal-tax (`tests/test_commit_authority.py`)

`test_B31_Q_scope_audit` currently opens the R8 window with
`assert set(names(f"{R8_BASE}..HEAD")) <= R8_SECTION_10`. Surgical edit only,
weakening no other assertion:

1. Seal the R8 window at the R8/PR#61 merge SHA: change that assertion's range
   from `{R8_BASE}..HEAD` to `{R8_BASE}..{R8_MERGE}` where
   `R8_MERGE = "89c4df7"` (that window already ⊆ `R8_SECTION_10`).
2. Open a fresh R9 window: add `R9_BASE = "89c4df7"` and
   `R9_SECTION_10 = {"SPEC_BRIEF_R9_five_domain_engagement.md",
   "tests/test_five_domain_engagement.py", "tests/test_commit_authority.py"}`
   (the seal edit is itself in the R9 window, so the file lists itself), and a
   new assertion `set(names(f"{R9_BASE}..HEAD")) <= R9_SECTION_10`.

No other logic in that file may change.

## §5 Acceptance (reviewer, §8)

- Only the two permitted files changed (plus this brief); scope audit on the PR
  diff range.
- `tests/test_five_domain_engagement.py` passes and genuinely asserts §4 items
  1–4 (not a vacuous/trivially-passing test).
- The test is hermetic: no real network/SDK call; validators patched.
- The §4b seal is present and weakens no existing assertion.
- Full canonical suite 0 failed via
  `TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" rtk test .venv/bin/python -m pytest -q`,
  decided from the runner SUMMARY line, never `$?`.

## §6 Non-goals

Live runs, CyberGym/lab runs, committed evaluation evidence (R10/BE-G3-5), the
live driver/executor (R12/BE-G2-6), dispatcher wiring, and any `src/kronos/`
change are out of scope.

## §7 Tripwire (mandatory STOP, not scope creep)

This brief is **test-only**. If, during implementation, any of the §4 FINDING
properties (two-armed proof / verdict tier / control disposition) cannot be
asserted hermetically **without** adding or changing code under `src/kronos/`,
the builder MUST STOP and report exactly which assertion is blocked and why —
it must NOT edit any `src/kronos/` file. The loop then returns to GATE-1 for a
scope amendment (as with the R7 seal amendment). Silent scope expansion into
`src/kronos/` is a hard-boundary violation.
