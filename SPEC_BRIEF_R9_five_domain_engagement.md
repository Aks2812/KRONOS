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
that the resulting FINDING(s) carry the three required properties — now read
back from the persisted graph (path A, §4c), not from the validator return. No
live targets, no network. This is a hermetic
milestone per roadmap `:14-15` ("COMPLETE (hermetic) = tested without any
live/manifest-bounded run"); contrast R10 (BE-G3-5) and R12 (BE-G2-6), which
require an authorized manifest-bounded run and are NOT in this brief.

`dns` is a sixth ingest module and is deliberately **not** one of the five
domains (the five are fixed by `KRONOS_RESEARCH_RECORD.md:1327-1328`).

## §2 Permitted files (hard scope) — GATE-1 amendment (path A, 2026-11-15)

The maintainer chose **path A**: persist the verdict tier and control
disposition onto the FINDING via a minimal `src/kronos/` change, so §4
assertions 3–4 rest on real persisted state, not the patched validator's
return. The builder may create/edit ONLY:

- `src/kronos/schema.py` (add two FINDING columns + make them settable — §4c)
- `src/kronos/validate/invalidation.py` (`record_secret_finding`: optional
  persistence kwargs — §4c)
- `src/kronos/validate/runner.py` (pass the outcome's values at the one call
  site — §4c)
- `tests/test_five_domain_engagement.py`
- `tests/test_schema_graph.py` (only if the two new columns require it)
- `tests/test_commit_authority.py` (seal-tax only — see §4b)

MUST NOT be touched: any OTHER `src/kronos/**` file, any OTHER test file,
`docs/`, `.claude/`, `.github/`, `cybergym/`. If the schema change breaks any
test outside this permitted set, STOP per the §7 tripwire — do not edit it.

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
3. **Verdict tier (persisted):** the anchored FINDING node has
   `verdict_tier == "live_discriminated"`, read back from the graph (NOT from the
   `ValidationOutcome` object), proving the runner persisted the discriminated
   verdict onto the finding.
4. **Control disposition (persisted):** the anchored FINDING node has a non-empty
   `control_disposition`, read back from the graph, proving the control arm's
   disposition was persisted onto the finding.

Assertions 3–4 MUST query the FINDING node via the graph read API, never the
patched validator's return value — the point of path A is that these rest on
persisted state.

## §4c Persistence design (minimal, path A)

1. `src/kronos/schema.py`:
   - Add two columns to the `FINDING` node table DDL: `verdict_tier STRING` and
     `control_disposition STRING`.
   - Add both to `NODE_COLUMNS["FINDING"]`.
   - Add both to `NODE_PROPS_ALWAYS["FINDING"]` so they are settable (and
     optional — `create_or_update_node` permits `always ∪ create_only` and
     requires none of them; existing FINDING creators that omit them are
     unaffected). Do NOT add them to `NODE_PROPS_FORBIDDEN`.
2. `src/kronos/validate/invalidation.py` — `record_secret_finding`: add two
   keyword-only params `verdict_tier: str = ""` and `control_disposition: str =
   ""`, and include each in the FINDING `props` dict ONLY when non-empty (so the
   existing `test_invalidation.py` callers that pass neither are unchanged).
3. `src/kronos/validate/runner.py` — at the single `record_secret_finding(...)`
   call site (~line 234): pass `verdict_tier=outcome.classification` and
   `control_disposition=outcome.control_outcome`.

No other `src/kronos/` behavior changes. `test_schema_graph.py` may be edited
only if the two new columns make an existing assertion there fail; no other test
file may change.

## §4b Seal-tax (`tests/test_commit_authority.py`)

`test_B31_Q_scope_audit` currently opens the R8 window with
`assert set(names(f"{R8_BASE}..HEAD")) <= R8_SECTION_10`. Surgical edit only,
weakening no other assertion:

1. Seal the R8 window at the R8/PR#61 merge SHA: change that assertion's range
   from `{R8_BASE}..HEAD` to `{R8_BASE}..{R8_MERGE}` where
   `R8_MERGE = "89c4df7"` (that window already ⊆ `R8_SECTION_10`).
2. Open a fresh R9 window: add `R9_BASE = "89c4df7"` and
   `R9_SECTION_10 = {"SPEC_BRIEF_R9_five_domain_engagement.md",
   "tests/test_five_domain_engagement.py", "tests/test_commit_authority.py",
   "src/kronos/schema.py", "src/kronos/validate/invalidation.py",
   "src/kronos/validate/runner.py", "tests/test_schema_graph.py"}` (every file in
   the R9 window, including the seal file itself; include
   `tests/test_schema_graph.py` only if it is actually changed), and a new
   assertion `set(names(f"{R9_BASE}..HEAD")) <= R9_SECTION_10`.

No other logic in that file may change.

## §5 Acceptance (reviewer, §8)

- Only the §2 permitted files changed (plus this brief); scope audit on the PR
  diff range.
- `tests/test_five_domain_engagement.py` passes and genuinely asserts §4 items
  1–4, with 3–4 read back from the persisted FINDING node (not a
  vacuous/trivially-passing test, not asserting the patched return).
- The test is hermetic: no real network/SDK call; validators patched.
- The §4b seal is present and weakens no existing assertion.
- Full canonical suite 0 failed via
  `TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" rtk test .venv/bin/python -m pytest -q`,
  decided from the runner SUMMARY line, never `$?`.

## §6 Non-goals

Live runs, CyberGym/lab runs, committed evaluation evidence (R10/BE-G3-5), the
live driver/executor (R12/BE-G2-6), dispatcher wiring, and any `src/kronos/`
change beyond the three files named in §2/§4c are out of scope. The persistence
change is deliberately confined to the secret-validation finding path; making
every other finding producer carry the two columns is a later follow-up.

## §7 Tripwire (mandatory STOP, not scope creep)

The §2 permitted set (path A) is exhaustive. If implementing §4c or the §4
assertions requires editing ANY file outside that set — any other `src/kronos/`
file, any other test, or governance — the builder MUST STOP and report exactly
which file and why; it must NOT edit it. In particular, if the two new FINDING
columns break a test other than `tests/test_schema_graph.py`, STOP and report
rather than widening scope. The loop then returns to GATE-1 for a further
amendment. Silent scope expansion is a hard-boundary violation.
