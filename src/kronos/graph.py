"""EngagementGraph: the only write path into an engagement's Kùzu DB.

`upsert_node` is the sole place `in_scope` is computed — always via
`ScopeGuard`, never accepted from caller-supplied `props`. `upsert_edge`
MERGEs so re-running the same ingestion twice never duplicates edges.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import kuzu

from kronos.manifest import ScopeManifest, load_and_verify
from kronos.schema import init_db
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
    value handled is a plain str/bool/int/float/None from caller-supplied
    props, never unsanitized external text used as a query fragment itself
    (property VALUES are escaped, property NAMES come only from our own
    fixed schema column lists, never from external input).
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
        if type in _CONFIDENCE_BEARING_TYPES and "confidence" not in props:
            # A lifecycle-agnostic sentinel: 0 is below every status cap
            # (see lifecycle.py / DECISIONS.md). Only advance_secret_status
            # / advance_finding_status ever write the real derived value;
            # this just keeps a freshly-created node's confidence column
            # from being NULL before its first lifecycle transition.
            props = {**props, "confidence": 0}

        set_clauses = []
        if type not in _NO_IN_SCOPE_COLUMN_TYPES:
            if type in _ALWAYS_IN_SCOPE_TYPES:
                in_scope = True
            else:
                in_scope = self.scope.is_in_scope(scope_key or id)
            set_clauses.append(f"n.in_scope = {_literal(in_scope)}")

        for key, value in props.items():
            set_clauses.append(f"n.{key} = {_literal(value)}")
        set_sql = ", ".join(set_clauses)

        query = (
            f"MERGE (n:{type} {{id: $id}}) "
            f"ON CREATE SET {set_sql} "
            f"ON MATCH SET {set_sql}"
        )
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
