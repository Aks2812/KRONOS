"""The only read surface onto an engagement's graph (SPEC.md "QUERY INTERFACE").

Agents (a later brief) never read raw tool output; they read through
these four-and-a-half functions. `find_paths` is the differentiator
query: it is what turns a mobile secret, an API endpoint, and a cloud
resource into a provable cross-domain chain.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING, Any

from kronos.evidence import get_evidence  # noqa: F401 - re-exported per SPEC.md's named interface list
from kronos.schema import ALL_NODE_TABLES, NODE_COLUMNS

if TYPE_CHECKING:  # pragma: no cover - avoids a runtime import cycle with graph.py
    from kronos.graph import EngagementGraph

# EVIDENCE has no in_scope column (schema.py) — find_paths' endpoint
# WHERE clause would crash with a raw Kuzu binder error. ENGAGEMENT
# never appears in any schema.EDGE_PAIRS entry, so it can never be a
# real chain participant; letting it through would just silently
# return [] forever rather than telling the caller why. Final review
# Important #9.
_FIND_PATHS_INVALID_ENDPOINT_TYPES = {"EVIDENCE", "ENGAGEMENT"}


def query_graph(
    graph: "EngagementGraph", node_type: str | None = None, filters: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Return matching nodes as plain dicts. `node_type=None` unions every
    node table (O(num_tables); fine at this scale, no index needed).

    `node_type` and every key in `filters` are validated against
    `schema.NODE_COLUMNS` before any Cypher is built — final review
    Important #6: these were previously pasted into query text
    unchecked. Nothing in this brief passes untrusted input here, but
    SPEC.md names this as the read surface a future agent will drive,
    so the same allowlist discipline as `upsert_node` applies.
    """
    if node_type is not None and node_type not in ALL_NODE_TABLES:
        raise ValueError(f"unknown node type {node_type!r}")

    if filters and node_type is not None:
        unknown = filters.keys() - NODE_COLUMNS.get(node_type, set())
        if unknown:
            raise ValueError(f"filters contains unknown column(s) {sorted(unknown)} for node type {node_type!r}")

    types = [node_type] if node_type is not None else ALL_NODE_TABLES
    rows: list[dict[str, Any]] = []
    for t in types:
        if filters and node_type is None and not (filters.keys() <= NODE_COLUMNS.get(t, set())):
            # Unioning every table: a table that doesn't even have one
            # of the filtered columns simply has no matching rows.
            continue
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
    for label, t in (("from_type", from_type), ("to_type", to_type)):
        if t not in ALL_NODE_TABLES:
            raise ValueError(f"unknown node type {t!r} for {label}")
        if t in _FIND_PATHS_INVALID_ENDPOINT_TYPES:
            raise ValueError(
                f"{t!r} cannot be a find_paths endpoint ({label}): it is never a "
                "cross-domain chain participant with a scope verdict to check"
            )

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


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def resolve_host(graph: "EngagementGraph", name: str, only_in_scope: bool = True) -> dict[str, Any]:
    """Read-only: IP terminals an FQDN HOST resolves to via `resolves_to`
    edges (CNAME chains followed, BFS, cycle-safe via a visited set).

    Evidence, not authorization: never writes, never sets `in_scope`, and
    never promotes an out-of-scope IP into an in-scope result. Abstains via
    `status` (unknown_host / unresolved / cycle_detected) when the stored
    edges are insufficient. Makes no freshness claim (edges carry no time).
    """
    norm = name.lower()
    if norm.endswith("."):
        norm = norm[:-1]

    def result(status: str, terminals: list[str], excluded: bool) -> dict[str, Any]:
        return {
            "name": norm,
            "status": status,
            "terminals": sorted(set(terminals)),
            "excluded_out_of_scope": excluded,
        }

    res = graph.execute("MATCH (h:HOST {id: $id}) RETURN h.in_scope AS in_scope", {"id": norm})
    if not res.has_next():
        return result("unknown_host", [], False)
    start_in_scope = bool(res.get_next()[0])
    if only_in_scope and not start_in_scope:
        return result("unresolved", [], True)
    if _is_ip(norm):
        return result("unresolved", [], False)

    visited: set[str] = set()
    terminals: set[str] = set()
    excluded = False
    cycle = False
    queue: list[tuple[str, frozenset[str]]] = [(norm, frozenset())]
    while queue:
        current, ancestors = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        path = ancestors | {current}
        rows = graph.execute(
            "MATCH (a:HOST {id:$id})-[:resolves_to]->(b:HOST) RETURN b.id AS id, b.in_scope AS in_scope",
            {"id": current},
        )
        while rows.has_next():
            bid, b_in_scope = rows.get_next()
            if only_in_scope and not b_in_scope:
                excluded = True
                continue
            if _is_ip(bid):
                terminals.add(bid)
            elif bid in path:
                cycle = True  # back-edge to an FQDN on the current path
            else:
                queue.append((bid, path))

    if cycle:
        return result("cycle_detected", list(terminals), excluded)
    if terminals:
        return result("resolved", list(terminals), excluded)
    return result("unresolved", [], excluded)
