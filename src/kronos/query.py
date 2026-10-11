"""The only read surface onto an engagement's graph (SPEC.md "QUERY INTERFACE").

Agents (a later brief) never read raw tool output; they read through
these four-and-a-half functions. `find_paths` is the differentiator
query: it is what turns a mobile secret, an API endpoint, and a cloud
resource into a provable cross-domain chain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kronos.evidence import get_evidence  # noqa: F401 - re-exported per SPEC.md's named interface list
from kronos.schema import ALL_NODE_TABLES

if TYPE_CHECKING:  # pragma: no cover - avoids a runtime import cycle with graph.py
    from kronos.graph import EngagementGraph


def query_graph(
    graph: "EngagementGraph", node_type: str | None = None, filters: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Return matching nodes as plain dicts. `node_type=None` unions every
    node table (O(num_tables); fine at this scale, no index needed)."""
    types = [node_type] if node_type is not None else ALL_NODE_TABLES
    rows: list[dict[str, Any]] = []
    for t in types:
        where = ""
        params: dict[str, Any] = {}
        if filters:
            clauses = []
            for i, (key, value) in enumerate(filters.items()):
                param_name = f"f{i}"
                clauses.append(f"n.{key} = ${param_name}")
                params[param_name] = value
            where = " WHERE " + " AND ".join(clauses)
        result = graph.execute(f"MATCH (n:{t}){where} RETURN n.*", params)
        columns = result.get_column_names()
        while result.has_next():
            row = result.get_next()
            rows.append({_strip_alias(c): v for c, v in zip(columns, row)})
    return rows


def _strip_alias(column_name: str) -> str:
    return column_name.split(".", 1)[1] if "." in column_name else column_name


def list_findings(graph: "EngagementGraph", status: str | None = None) -> list[dict[str, Any]]:
    return query_graph(graph, "FINDING", {"status": status} if status else None)


def list_secrets(graph: "EngagementGraph", status: str | None = None) -> list[dict[str, Any]]:
    return query_graph(graph, "SECRET", {"status": status} if status else None)


def find_paths(
    graph: "EngagementGraph",
    from_type: str,
    to_type: str,
    max_hops: int = 5,
    only_in_scope: bool = True,
) -> list[dict[str, Any]]:
    """Cross-domain chains from `from_type` to `to_type`, up to `max_hops`.

    Path endpoints are ALWAYS scope-checked (`a.in_scope = true AND
    b.in_scope = true`), regardless of `only_in_scope` — an out-of-scope
    asset must never surface as a chain terminus from this query, the
    same spirit as SPEC.md's scope-guard rule for findings/secrets.
    `only_in_scope` additionally governs intermediate hops: when True, the
    recursive traversal itself is restricted to in-scope nodes at every
    step (Kuzu's inline `(r,n | WHERE n.in_scope = true)` predicate);
    when False, intermediate hops may leave scope for diagnostic use.
    """
    if only_in_scope:
        pattern = f"-[* 1..{max_hops} (r,n | WHERE n.in_scope = true)]->"
    else:
        pattern = f"-[* 1..{max_hops}]->"

    # Kuzu's binder rejects a `[x IN nodes(p) | x.id]`-style comprehension
    # here ("Variable x is not in scope") even though `nodes(p)`/`rels(p)`
    # work fine on their own — confirmed empirically, not assumed. Return
    # the raw node/rel structs and pull `id`/`_label` out in Python instead.
    query = (
        f"MATCH p=(a:{from_type}){pattern}(b:{to_type}) "
        "WHERE a.in_scope = true AND b.in_scope = true "
        "RETURN nodes(p) AS ns, rels(p) AS rs, length(p) AS len "
        "ORDER BY len"
    )
    result = graph.execute(query)
    paths = []
    while result.has_next():
        ns, rs, length = result.get_next()
        paths.append({
            "nodes": [n["id"] for n in ns],
            "labels": [r["_label"] for r in rs],
            "length": length,
        })
    return paths
