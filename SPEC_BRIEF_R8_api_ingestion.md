# SPEC_BRIEF R8 — Standalone API ingestion (BE-G1-5)

Roadmap item R8 (`docs/roadmap/KRONOS_ROADMAP.md:26`: standalone API ingestion,
not mobile-sourced). GATE-1 approved by maintainer. Maps G1 (breadth) and G3
(validation travels in the same step). DoD predicate BE-G1-5
(`docs/governance/KRONOS_DONE.md:60`): source module `src/kronos/ingest/api/`
present AND test `tests/test_api_ingest.py` present; mobile-sourced API evidence
is insufficient (roadmap D4 `:43`).

## §1 Goal

Add a hermetic, provider-neutral **standalone** API-inventory ingestion source
that turns a declarative list of observed API endpoints into `API_ENDPOINT`
nodes — sourced directly, not via a mobile app (which today is the only
producer: `src/kronos/ingest/mobile/parser.py:276`). No network, no live API
calls, no SDK — stdlib `json` only. Mirrors `src/kronos/ingest/infra/parser.py`
and `src/kronos/ingest/cloud/parser.py` (R7) exactly; introduces no new
contract and no schema change (`API_ENDPOINT` already exists,
`schema.py:50-53`).

## §2 Permitted files (hard scope)

The builder may create/edit ONLY:

- `src/kronos/ingest/api/__init__.py`
- `src/kronos/ingest/api/parser.py`
- `tests/test_api_ingest.py`
- `tests/test_commit_authority.py` (seal-tax only — see §4b)

Out of scope, MUST NOT be touched: `src/kronos/ingest/__init__.py` (dispatcher
wiring is a later follow-up), `src/kronos/schema.py` (the `API_ENDPOINT` table
already exists), `src/kronos/ingest/mobile/**`, `src/kronos/ingest/web/**`, and
anything under `docs/`, `.claude/`, `.github/`, `cybergym/`,
`src/kronos/validate/`.

## §3 Input (provider-neutral, hermetic, standalone)

A single JSON string. Shape:

```json
{
  "endpoints": [
    {"url": "https://api.example.com/v1/users", "method": "GET"},
    {"url": "https://api.example.com/v1/orders", "method": "POST"}
  ]
}
```

- Unparseable JSON, or a top-level value that is not an object → decline
  (`unparseable_api_inventory`), emit nothing. Never put raw input in the
  reason/detail.
- `endpoints` defaults to empty when absent. A non-list `endpoints` → decline
  (`unparseable_api_inventory`), emit nothing.

## §4 Output (mirrors infra/cloud parser)

Core returns `(upserts, declined)`; two faces wrap it:

- `ingest_api_inventory(inventory_json, engagement) -> list[NodeUpsert | EdgeUpsert]`
  (bare-list face).
- `ingest_api_inventory_plan(inventory_json, engagement) -> IngestPlan`
  (`IngestionSource`-conforming face; wraps the same core with `build_report`).

`SourceDescriptor(name="api-inventory", version="1")`.

Per endpoint item:
- `url` missing/empty (non-empty string required) → decline
  (`missing_endpoint_url`), skip.
- `method` missing, or not one of `GET POST PUT PATCH DELETE`
  (case-insensitive; normalise to upper-case) → decline
  (`missing_or_invalid_method`), skip.
- else `NodeUpsert("API_ENDPOINT", url, {"url": url, "method": <UPPER>,
  "source": "api-inventory"}, scope_key=url)`. `id` is the `url` (matching
  `mobile/parser.py:276`, which keys `API_ENDPOINT` by url).

Guardrail (SPEC_BRIEF9 §1, `ingest/contract.py`): no `NodeUpsert` may carry
`in_scope`; scope is decided downstream by `scope_guard` via `upsert_node`. The
source only sets `scope_key`. Emit `ingest_started` / `ingest_declined` /
`ingest_finished` events via `kronos.events.emit`, exactly as
`infra/parser.py` does. Props must match `NODE_PROPS_ALWAYS` for `API_ENDPOINT`
(`url`, `method`, `source`; `schema.py`).

## §4b Seal-tax (`tests/test_commit_authority.py`)

`test_B31_Q_scope_audit` currently opens the R7 window with
`assert set(names(f"{R7_BASE}..HEAD")) <= R7_SECTION_10`. R8's new paths are not
in `R7_SECTION_10`, so that window must be sealed and a new one opened. Surgical
edit only, weakening no other assertion:

1. Seal the R7 window at the R7/PR#60 merge SHA: change that assertion's range
   from `{R7_BASE}..HEAD` to `{R7_BASE}..{R7_MERGE}` where
   `R7_MERGE = "84434eb"` (that window already ⊆ `R7_SECTION_10`).
2. Open a fresh R8 window: add `R8_BASE = "84434eb"` and
   `R8_SECTION_10 = {"SPEC_BRIEF_R8_api_ingestion.md",
   "src/kronos/ingest/api/__init__.py", "src/kronos/ingest/api/parser.py",
   "tests/test_api_ingest.py", "tests/test_commit_authority.py"}` (the seal edit
   is itself in the R8 window, so the file lists itself), and a new assertion
   `set(names(f"{R8_BASE}..HEAD")) <= R8_SECTION_10`.

No other logic in that file may change. Do not weaken any existing assertion.

## §5 Tests (`tests/test_api_ingest.py`)

Cover, using a temp `EngagementGraph` as the other ingest tests do:

1. A well-formed inventory yields the expected `API_ENDPOINT` nodes; node props
   exactly match `NODE_PROPS_ALWAYS` (`url`, `method`, `source`), no `in_scope`
   present; method normalised to upper-case.
2. Unparseable JSON declines with `unparseable_api_inventory` and emits nothing.
3. A non-object top level, and a non-list `endpoints`, each decline
   `unparseable_api_inventory`.
4. An endpoint missing `url`, and one with an invalid/missing `method`, are each
   declined individually (`missing_endpoint_url`, `missing_or_invalid_method`)
   while valid siblings still emit.
5. A lowercase method (e.g. `get`) is accepted and stored as `GET`.
6. The plan face conforms to `IngestionSource` and its `IngestReport` counts
   match the emitted upserts.
7. No declined item's reason/detail contains raw input.

## §6 Acceptance (reviewer, §8)

- Only the permitted files changed (the four in §2); scope audit on the PR diff
  range.
- `tests/test_api_ingest.py` passes.
- The §4b seal is present and weakens no existing assertion.
- Full canonical suite 0 failed via
  `TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" rtk test .venv/bin/python -m pytest -q`,
  decided from the runner SUMMARY line, never `$?`.
- No network/live/SDK import in the new module (hermetic).

## §7 Non-goals

Dispatcher wiring (`ingest()` in `ingest/__init__.py`), real HTTP capture or
live API traffic ingestion, parameter extraction, and linking endpoints to
hosts/services are explicitly out of scope and deferred.
