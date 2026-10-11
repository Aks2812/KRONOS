# Schema + Graph (`schema.py`, `graph.py`)

## What this is

One Kùzu DB file per engagement. `schema.py` holds the DDL for every node
and edge table; `graph.py`'s `EngagementGraph` is the only write path any
other module in this package uses to touch that DB.

## Node tables

14 node types, all defined in `schema.py`. Every scope-target type gets
`id` (primary key), `in_scope`, `created_at`, `source` plus its own
props. Two types are **not** scope targets and skip `in_scope`/`source`:

- `ENGAGEMENT` — represents the engagement itself. It keeps an `in_scope`
  *column* (for schema uniformity) but `upsert_node` always hardcodes it
  `True` rather than asking `ScopeGuard`.
- `EVIDENCE` — an artifact attached to a finding/secret, never an action
  target in its own right. It has **no** `in_scope` column at all;
  `upsert_node` skips that `SET` clause entirely for this type.

Why not ask `ScopeGuard` for either: neither corresponds to a network/app
target a glob or CIDR pattern could ever match meaningfully, and giving
them a real scope check would just be theater — see `DECISIONS.md`.

## Edge tables

Each edge label in SPEC.md's "EDGE TYPES" list is one `CREATE REL TABLE
GROUP`, spanning the `(FROM, TO)` node-type pairs listed in
`schema.EDGE_PAIRS`. Kùzu rel-table-groups need every pair declared up
front; there's no "any node type" wildcard. The exact pair choices (e.g.
why `leaks` includes `API_ENDPOINT -> SECRET` as well as `MOBILE_APP ->
SECRET`) are design calls this module made — not fixed by the spec beyond
the label name — and are listed with rationale in `DECISIONS.md`.

`EDGE_PAIRS` is kept as plain data (not just DDL text) so other modules
and tests can introspect "which pairs does `label` support" without
re-parsing SQL.

## Why MERGE-by-id is the dedup strategy

SPEC.md's INGESTION CONTRACT requires "same host:port updates, never
duplicates." Every node/edge write goes through `MERGE ... ON CREATE SET
... ON MATCH SET ...` keyed on `id` (nodes) or the pair of endpoint `id`s
(edges). Running the exact same upsert twice is a no-op on the second
call — see `test_upsert_node_merges_not_duplicates` /
`test_upsert_edge_merges_not_duplicates`. Callers are responsible for
picking a stable `id` (e.g. `host:10.0.0.1`, a content hash, or a bundle
id) — the graph layer does not invent one.

## Why `in_scope` is never caller-settable

`EngagementGraph.upsert_node` computes `in_scope` itself, from
`ScopeGuard.is_in_scope(scope_key or id)`, and writes it unconditionally —
any `in_scope` key present in a caller's `props` dict is simply never
read for that purpose (callers can't pass it at all; it's not a `props`
key, it's a separate computed value). This is deliberate: SPEC.md's
`scope_guard(target, manifest)` must be "the only scope mechanism," so
the one function that writes nodes into the graph is the one function
that calls it. There is no second, lower-level write path that skips this
check.

`scope_key` lets a node's scope be judged by something other than its own
`id` — e.g. a `SECRET` extracted from a mobile app is in-scope if the
*app's* bundle id is in-scope, not because the secret's own opaque id
string happens to match a glob.

## `upsert_edge`'s signature

`upsert_edge(label, from_id, from_type, to_id, to_type, props=None)` —
both endpoint **types** are required, not inferred. Kùzu's rel-table-group
MERGE needs to know which of a label's declared `(FROM, TO)` pairs to use;
scanning every node table to guess a bare id's type would be slow and
still ambiguous if two tables happened to share an id scheme. Callers
(notably `ingest.py`) already know each upsert's node type, so this costs
them nothing.

## `get_node`

Returns a plain `dict` of the node's own properties (no graph traversal),
or `None` if no row matches. Used by tests and by `lifecycle.py` to read
current `status` before validating a transition.
