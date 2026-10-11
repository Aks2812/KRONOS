# Ingestion Contract (`ingest.py`)

SPEC.md's `ingest(raw_tool_output, tool_name, engagement) -> list of
node/edge upserts` contract, plus one hardcoded parser proving it works:
a mobile app leaking a secret.

## The upsert contract

`ingest()` never writes to the graph directly. It returns a plain list of
`NodeUpsert`/`EdgeUpsert` dataclasses — a description of what should
exist, not a side effect. `apply_upserts(engagement, upserts)` is the
only thing that actually calls `EngagementGraph.upsert_node`/
`upsert_edge`. This separation matters for a future brief's real parsers:
they can be tested as pure functions (raw tool output in, upsert list
out) with no DB involved at all.

`EdgeUpsert` carries only `label, from_id, to_id, props` — no endpoint
*types*. `apply_upserts` resolves each endpoint's type itself, by probing
`get_node` across every table in `schema.ALL_NODE_TABLES` until it finds
one that already holds that id (`_resolve_node_type`). This is why a
reference ingester's node upserts must be ordered before the edge
upserts that reference them — `apply_upserts` processes the list in
order, so by the time it reaches an `EdgeUpsert` both endpoints already
exist.

## MERGE/dedup guarantee

Every upsert goes through `EngagementGraph.upsert_node`/`upsert_edge`,
which `MERGE` on `id` (nodes) or the endpoint-id pair (edges) — see
`README_graph.md`. So `apply_upserts(g, ingest(raw, tool, g))` is safe to
call twice on the *same* raw input: the second call is a no-op, never a
duplicate. This is SPEC.md's "same host:port updates, never duplicates"
requirement, proven directly by
`test_apply_upserts_is_idempotent_no_duplicates`.

## The reference ingester

`ingest_reference_mobile_secret(bundle_id="com.kronos.demo")` hardcodes
exactly the worked example SPEC.md asks for: a `MOBILE_APP` node, a
`SECRET` node (its id derived from the bundle id's hash, its `scope_key`
set to the bundle id so its scope is judged by the app it came from, not
by its own opaque secret id), and a `leaks` edge between them. `ingest()`
dispatches to it only when `tool_name == "reference"`; every other tool
name raises `NotImplementedError` — real parsers are a later brief, and
this contract doesn't pretend otherwise.

## Plugging in a real parser later

A future parser is just another function with the shape `(raw_tool_output)
-> list[NodeUpsert | EdgeUpsert]`, registered in `ingest()`'s dispatch.
It should pick stable, deterministic node ids (so re-running the same
scan twice produces the same ids and therefore merges rather than
duplicates) and set each node's `scope_key` to whatever the scope guard
should actually judge — not always the node's own id (see the SECRET
example above).
