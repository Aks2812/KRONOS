"""EngagementGraph: the only write path into an engagement's Kùzu DB.

`upsert_node` is the sole place `in_scope` is computed — always via
`ScopeGuard`, never accepted from caller-supplied `props` (enforced: a
`props` key naming a computed or lifecycle-owned column raises
`ValueError`, and a key that isn't a real, known column for that node
type raises too — see `schema.NODE_PROPS_ALWAYS` /
`NODE_PROPS_CREATE_ONLY` / `NODE_PROPS_FORBIDDEN`). `upsert_edge` MERGEs
so re-running the same ingestion twice never duplicates edges.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import kuzu

from kronos.manifest import ScopeManifest, load_and_verify
from kronos.schema import (
    ALL_NODE_TABLES,
    NODE_PROPS_ALWAYS,
    NODE_PROPS_CREATE_ONLY,
    NODE_PROPS_FORBIDDEN,
    init_db,
)
from kronos.scope_guard import ScopeGuard

# ENGAGEMENT is not a scope target: it represents the engagement itself,
# so its in_scope column (schema.py gives it one) is always hardcoded
# True rather than something scope_guard decides (see DECISIONS.md).
_ALWAYS_IN_SCOPE_TYPES = {"ENGAGEMENT"}

# EVIDENCE has no in_scope column at all (schema.py) — it's an artifact
# attached to a finding/secret, never an action target in its own right.
_NO_IN_SCOPE_COLUMN_TYPES = {"EVIDENCE"}

# Node types whose schema includes a `confidence` column (SECRET, FINDING)
# — see the sentinel-default note in upsert_node below.
_CONFIDENCE_BEARING_TYPES = {"SECRET", "FINDING"}


def _literal(value: Any) -> str:
    """Render a Python value as a Cypher literal for a SET clause.

    Kùzu's Python parameter binding covers MATCH/MERGE predicates
    cleanly, but building a dynamic SET clause from an arbitrary set of
    property names per call is simplest with inline literals here; every
    value handled is a plain str/bool/int/float/None. Property VALUES are
    escaped here; property NAMES are checked against `schema.py`'s
    allowlists in `upsert_node` before they ever reach an f-string — see
    that function's validation at the top, which is what actually keeps
    an arbitrary `props` key from becoming executable Cypher text.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


class EngagementGraph:
    """One engagement's isolated Kùzu DB, opened under its verified manifest."""

    def __init__(self, db_path: str | Path, manifest: ScopeManifest) -> None:
        self.db_path = Path(db_path)
        self.manifest = manifest
        self.db = init_db(self.db_path)
        self.conn = kuzu.Connection(self.db)
        self.scope = ScopeGuard(manifest)

    @classmethod
    def init_engagement(
        cls, db_path: str | Path, manifest_yaml_text: str, public_key
    ) -> "EngagementGraph":
        manifest = load_and_verify(manifest_yaml_text, public_key)
        graph = cls(db_path, manifest)
        graph.upsert_node(
            "ENGAGEMENT",
            manifest.engagement_id,
            {
                "client": manifest.client,
                "authorized_by": manifest.authorized_by,
                "window_start": manifest.window_start.isoformat(),
                "window_end": manifest.window_end.isoformat(),
                "destructive_allowed": manifest.destructive_allowed,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return graph

    def upsert_node(
        self, type: str, id: str, props: dict[str, Any], scope_key: str | None = None
    ) -> None:
        """The only way to create or update a node.

        Validates `props` against `schema.py`'s per-type allowlists
        before building any Cypher (final-review fix: previously every
        key in `props` was written unchecked, so a caller could set
        `in_scope`/`confidence`/`status` directly — closing both the
        scope/lifecycle bypass and the property-name injection vector
        that bypass opened).

        `status` is settable via `props` only at creation (an ingester's
        initial value); a later call on the same `id` silently leaves it
        alone rather than erroring, so a parser re-run never resets a
        lifecycle-advanced SECRET/FINDING back down. `confidence` is
        never caller-settable at all — a fresh node gets the sentinel
        `0` (below every status cap) and only `lifecycle.py`'s two
        functions ever change it afterward.
        """
        if type not in ALL_NODE_TABLES:
            raise ValueError(f"unknown node type {type!r}")

        forbidden = props.keys() & NODE_PROPS_FORBIDDEN
        if forbidden:
            raise ValueError(
                f"props may not set {sorted(forbidden)} on {type!r}; these are "
                "computed by scope_guard/lifecycle, never caller-settable"
            )

        always = NODE_PROPS_ALWAYS.get(type, set())
        create_only = NODE_PROPS_CREATE_ONLY.get(type, set())
        unknown = props.keys() - always - create_only
        if unknown:
            raise ValueError(f"props contains unknown column(s) {sorted(unknown)} for node type {type!r}")

        always_clauses = [f"n.{key} = {_literal(props[key])}" for key in props if key in always]
        create_clauses = list(always_clauses)
        match_clauses = list(always_clauses)

        if type not in _NO_IN_SCOPE_COLUMN_TYPES:
            if type in _ALWAYS_IN_SCOPE_TYPES:
                in_scope = True
            else:
                in_scope = self.scope.is_in_scope(scope_key or id)
            in_scope_clause = f"n.in_scope = {_literal(in_scope)}"
            create_clauses.append(in_scope_clause)
            match_clauses.append(in_scope_clause)

        if type in _CONFIDENCE_BEARING_TYPES:
            create_clauses.append("n.confidence = 0")

        # created_at is create-only for every node type that has the
        # column (schema.py adds it to every type's create_only set).
        if "created_at" in create_only:
            created_at = props.get("created_at", datetime.now(timezone.utc).isoformat())
            create_clauses.append(f"n.created_at = {_literal(created_at)}")
        for key in create_only - {"created_at"}:
            if key in props:
                create_clauses.append(f"n.{key} = {_literal(props[key])}")

        create_sql = ", ".join(create_clauses)
        query = f"MERGE (n:{type} {{id: $id}}) ON CREATE SET {create_sql}"
        if match_clauses:
            query += f" ON MATCH SET {', '.join(match_clauses)}"
        self.conn.execute(query, {"id": id})

    def upsert_edge(
        self,
        label: str,
        from_id: str,
        from_type: str,
        to_id: str,
        to_type: str,
        props: dict[str, Any] | None = None,
    ) -> None:
        query = (
            f"MATCH (a:{from_type} {{id: $from_id}}), (b:{to_type} {{id: $to_id}}) "
            f"MERGE (a)-[r:{label}]->(b)"
        )
        if props:
            set_sql = ", ".join(f"r.{key} = {_literal(value)}" for key, value in props.items())
            query += f" ON CREATE SET {set_sql} ON MATCH SET {set_sql}"
        self.conn.execute(query, {"from_id": from_id, "to_id": to_id})

    def get_node(self, type: str, id: str) -> dict[str, Any] | None:
        result = self.conn.execute(f"MATCH (n:{type} {{id: $id}}) RETURN n.*", {"id": id})
        if not result.has_next():
            return None
        columns = result.get_column_names()
        row = result.get_next()
        return {_strip_alias(col): val for col, val in zip(columns, row)}

    def execute(self, query: str, params: dict[str, Any] | None = None):
        return self.conn.execute(query, params or {})


def _strip_alias(column_name: str) -> str:
    """Kùzu returns `n.*` columns as `n.prop_name`; strip the `n.` prefix."""
    return column_name.split(".", 1)[1] if "." in column_name else column_name
