# SPEC_BRIEF R7 — Cloud ingestion source (BE-G1-6)

Roadmap item R7 (`docs/roadmap/KRONOS_ROADMAP.md`: cloud ingestion →
`CLOUD_RESOURCE`, `IDENTITY`). GATE-1 approved by maintainer. Maps G1 (breadth)
and G3 (its validation travels in the same step). DoD predicate BE-G1-6
(`docs/governance/KRONOS_DONE.md:61`): source module `src/kronos/ingest/cloud/`
present AND test `tests/test_cloud_ingest.py` present.

## §1 Goal

Add a hermetic, provider-neutral cloud-inventory ingestion source that turns a
declarative inventory document into `CLOUD_RESOURCE` and `IDENTITY` nodes plus
`grants` edges. No provider credentials, no SDK (`boto3`) calls, no network, no
live cloud access — stdlib `json` only. This is the first usable cloud-domain
ingestion; it mirrors the existing `src/kronos/ingest/infra/parser.py` shape
exactly and introduces no new contract.

## §2 Permitted files (hard scope)

The builder may create/edit ONLY:

- `src/kronos/ingest/cloud/__init__.py`
- `src/kronos/ingest/cloud/parser.py`
- `tests/test_cloud_ingest.py`
- `tests/test_commit_authority.py` (GATE-1 amendment 2026-11-14: seal-tax only — see §4b)

Out of scope, MUST NOT be touched: `src/kronos/ingest/__init__.py` (dispatcher
wiring is a later follow-up), `src/kronos/schema.py` (the `IDENTITY` /
`CLOUD_RESOURCE` tables and the `grants` edge already exist — see
`schema.py:71-80` and `schema.py:121`), and anything under `docs/`,
`.claude/`, `.github/`, `cybergym/`, `src/kronos/validate/`.

## §3 Input (provider-neutral, hermetic)

A single JSON string. Shape:

```json
{
  "provider": "aws",
  "resources": [{"id": "arn:...:bucket/x", "resource_type": "s3_bucket"}],
  "identities": [{"id": "arn:...:user/alice", "name": "alice"}],
  "grants": [{"identity": "arn:...:user/alice", "resource": "arn:...:bucket/x"}]
}
```

- `provider` is a short string written to the `provider` prop of every emitted
  node. Missing/empty `provider` → decline the whole document
  (`missing_provider`), emit nothing.
- Unparseable JSON, or a top-level value that is not an object → decline
  (`unparseable_cloud_inventory`), emit nothing. Never put raw input in the
  reason/detail.
- `resources` / `identities` / `grants` each default to empty when absent.

## §4 Output (mirrors infra/parser.py)

Core returns `(upserts, declined)`; two faces wrap it:

- `ingest_cloud_inventory(inventory_json, engagement) -> list[NodeUpsert | EdgeUpsert]`
  (bare-list face).
- `ingest_cloud_inventory_plan(inventory_json, engagement) -> IngestPlan`
  (`IngestionSource`-conforming face; wraps the same core with `build_report`).

`SourceDescriptor(name="cloud-inventory", version="1")`.

Per resource item:
- `id` missing/empty → decline (`missing_resource_id`), skip.
- `resource_type` missing/empty → decline (`missing_resource_type`), skip.
- else `NodeUpsert("CLOUD_RESOURCE", id, {"resource_type": <str>, "provider": <str>, "source": "cloud-inventory"}, scope_key=id)`.

Per identity item:
- `id` missing/empty → decline (`missing_identity_id`), skip.
- `name` missing/empty → decline (`missing_identity_name`), skip.
- else `NodeUpsert("IDENTITY", id, {"name": <str>, "provider": <str>, "source": "cloud-inventory"}, scope_key=id)`.

Per grant item (emitted only after its two endpoints were emitted as nodes in
this same document; otherwise decline `grant_dangling_endpoint`, skip):
- `EdgeUpsert("grants", identity_id, resource_id)` — direction `IDENTITY ->
  CLOUD_RESOURCE`, matching `schema.py:121` `"grants": [("IDENTITY",
  "CLOUD_RESOURCE")]`.

Guardrail (SPEC_BRIEF9 §1, `ingest/contract.py`): no `NodeUpsert` may carry
`in_scope`; scope is decided downstream by `scope_guard` via `upsert_node`. The
source only sets `scope_key`. Emit `ingest_started` / `ingest_declined` /
`ingest_finished` events via `kronos.events.emit`, exactly as
`infra/parser.py` does.

## §4b Seal-tax (GATE-1 amendment, `tests/test_commit_authority.py`)

`test_B31_Q_scope_audit` asserts the open window `AB_BASE(3f6dbc3)..HEAD` is a
subset of `AB_SECTION_10`. R7's four new paths are not in that allowlist, so the
window must be sealed. Surgical edit only:

1. Seal the historical window at the B54/PR#59 merge SHA: change the last
   assertion from `{AB_BASE}..HEAD` to `{AB_BASE}..{AB_MERGE}` where
   `AB_MERGE = "6604e32"` (that window already ⊆ `AB_SECTION_10`).
2. Open a fresh R7 window: add `R7_BASE = "6604e32"` and
   `R7_SECTION_10 = {"SPEC_BRIEF_R7_cloud_ingestion.md",
   "src/kronos/ingest/cloud/__init__.py", "src/kronos/ingest/cloud/parser.py",
   "tests/test_cloud_ingest.py"}`, and a new assertion
   `set(names(f"{R7_BASE}..HEAD")) <= R7_SECTION_10`.

No other logic in that file may change. Do not weaken any existing assertion.

## §5 Tests (`tests/test_cloud_ingest.py`)

Cover, using an in-memory/temp `EngagementGraph` as the other ingest tests do:

1. A well-formed inventory yields the expected `CLOUD_RESOURCE` + `IDENTITY`
   nodes and `grants` edge; node props exactly match `NODE_PROPS_ALWAYS`
   (`schema.py:173-174`), no `in_scope` present.
2. Unparseable JSON declines with `unparseable_cloud_inventory` and emits
   nothing.
3. Missing `provider` declines whole document.
4. A resource missing `resource_type`, and an identity missing `name`, are each
   declined individually while valid siblings still emit.
5. A grant naming an endpoint not emitted in the document declines
   `grant_dangling_endpoint` and emits no edge.
6. The plan face conforms to `IngestionSource` and its `IngestReport` counts
   match the emitted upserts.
7. No declined item's reason/detail contains raw input.

## §6 Acceptance (reviewer, §8)

- Only the permitted files changed (the three product files + the §4b seal in
  `tests/test_commit_authority.py`); scope audit on the PR diff range.
- `tests/test_cloud_ingest.py` passes.
- Full canonical suite 0 failed via
  `TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" rtk test .venv/bin/python -m pytest -q`,
  decided from the runner SUMMARY line, never `$?`.
- No `boto3`/network/live import in the new module (hermetic).

## §7 Non-goals

Dispatcher wiring (`ingest()` in `ingest/__init__.py`), real provider SDK
ingestion, and live cloud access are explicitly out of scope and deferred.
