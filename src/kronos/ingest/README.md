# Ingestion (`kronos.ingest`)

Turns raw tool output into a declarative plan of graph writes, then
applies that plan idempotently. An ingestion source never writes the
graph itself and never decides scope — those are `apply_plan`'s and
`EngagementGraph.upsert_node`'s jobs respectively, so every present and
future source gets scope-gating and prop-allowlisting for free.

## Modules

- **`__init__.py`** — `NodeUpsert`/`EdgeUpsert` (Brief #1's original
  ingestion contract), `ingest(raw_tool_output, tool_name, engagement)`
  (dispatch by `tool_name`), and `apply_upserts(graph, upserts)` — the
  underlying write path: the only code in this package that calls
  `engagement.upsert_node`/`upsert_edge` directly. Kept exactly as it
  was (SPEC_BRIEF9 doesn't touch its behavior) because
  `cybergym/kronos_validation_run.py` (out of this brief's allowlist)
  depends on `ingest()`'s bare-`list[NodeUpsert | EdgeUpsert]` return
  shape.
- **`contract.py`** (SPEC_BRIEF9 §3) — the formal, named version of the
  same shape: `SourceDescriptor`, `DeclinedItem`, `IngestReport`,
  `IngestPlan` (the plan plus its report), the `IngestionSource`
  structural `Protocol`, and `apply_plan(graph, plan)` — a thin wrapper
  that delegates to `apply_upserts`. `apply_plan` and `apply_upserts`
  are jointly the sole graph-writing chokepoint under this package (see
  `tests/test_ingest_contract.py`'s non-vacuous guard, which names both
  and nothing else).
- **`mobile/parser.py`** — the one real source, `ingest_mobile_static`
  (SPEC_BRIEF2). As of SPEC_BRIEF9, its extraction logic is unchanged
  and shared by two public faces over one internal core
  (`_ingest_mobile_static_core`): `ingest_mobile_static` (legacy
  bare-list return, used by `ingest()`/cybergym) and
  `ingest_mobile_static_plan` (the new `IngestionSource`-conforming
  entry point, returning an `IngestPlan`). Both emit the same
  `ingest_started`/`ingest_declined`/`ingest_finished` events.

## Why two entry points, not one

SPEC_BRIEF9 §3 asks for a source that "returns an `IngestPlan`." Making
`ingest_mobile_static` itself return that (instead of a bare list) would
be a breaking change for `cybergym/kronos_validation_run.py`, which is
explicitly out of this brief's allowlist (`cybergym/` "Must NOT
change"). Adapting the ingester therefore means two thin faces on one
extraction core, not a changed external contract for the one caller
this brief isn't allowed to touch — see SPEC_BRIEF9's own build report
for the full reasoning and `DECISIONS.md`'s Brief #9 entry.

## Declining is a recorded outcome, not silence

A source that can't safely process its input (e.g. an unparseable
`AndroidManifest.xml`) returns an empty plan **plus** a `DeclinedItem`
in its `IngestReport.declined` and an `ingest_declined` event — never a
silent empty return with no trace of why.
