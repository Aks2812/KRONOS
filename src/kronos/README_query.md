# Query Interface (`query.py`)

The only read surface anything outside `kronos` — notably a future
agent — ever touches. Five functions:

- `query_graph(graph, node_type=None, filters=None)` — raw node lookup.
  `node_type=None` unions every table in the schema (O(num_tables), fine
  at single-engagement scale; no index to maintain).
- `list_findings(graph, status=None)` / `list_secrets(graph, status=None)`
  — thin `query_graph` wrappers filtered by `status`.
- `get_evidence(engagement_dir, sha256)` — re-exported from `evidence.py`
  verbatim, so callers only need to import `kronos.query` for the whole
  read API SPEC.md names.
- `find_paths(graph, from_type, to_type, max_hops=5, only_in_scope=True)`
  — the differentiator query.

## Why `find_paths` is the differentiator

This is the one query that actually proves KRONOS's cross-domain claim:
given a `MOBILE_APP` and a `CLOUD_RESOURCE`, does a chain of edges —
`leaks`, `authenticates_to`, `chains_to`, whatever the graph actually
contains — connect them in `max_hops` or fewer steps? No single-domain
tool asks this question because no single-domain tool has both ends of
the chain in the same graph.

It's built on Kùzu's variable-length path syntax, confirmed against the
installed `kuzu==0.11.3` rather than assumed:
`-[* 1..{max_hops} (r,n | WHERE n.in_scope = true)]->` restricts the
*traversal itself* to in-scope nodes at every step when `only_in_scope`
is True. One syntax pitfall worth flagging for future maintainers: Kùzu's
binder rejects `[x IN nodes(p) | x.id]`-style list comprehensions in a
`RETURN` clause ("Variable x is not in scope"), even though `nodes(p)`
and `rels(p)` work fine on their own. The fix used here is to `RETURN
nodes(p), rels(p)` as raw structs and pull `id`/`_label` out in Python —
each node/rel struct already carries those fields.

## Endpoints are always scope-checked

`WHERE a.in_scope = true AND b.in_scope = true` is applied unconditionally,
regardless of `only_in_scope`. `only_in_scope` only controls whether
*intermediate* hops may leave scope (useful for an operator's own
diagnostic "show me the whole graph, scope be damned" view) — the two
endpoints of a returned chain are never allowed to be an out-of-scope
asset. This mirrors SPEC.md's scope-guard intent for findings/secrets:
an out-of-scope node can exist in the graph, but it can never be the
reason a chain gets reported as real.
