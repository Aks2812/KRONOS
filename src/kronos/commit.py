"""GraphMutationAuthority: the sole holder of write-Cypher execution (SPEC_BRIEF31).

The writable kuzu Connection is a private attribute; no public method accepts
a raw Cypher string. Every mutation is a typed op carrying a `MutationSource`
identity. Column names are whitelisted literals inside each method; no
caller-supplied name ever reaches Cypher.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

import kuzu

from kronos.schema import (
    ALL_NODE_TABLES,
    EDGE_PAIRS,
    NODE_PROPS_ALWAYS,
    NODE_PROPS_CREATE_ONLY,
    NODE_PROPS_FORBIDDEN,
)
from kronos.scope_guard import ScopeGuard

# ENGAGEMENT is not a scope target: it is the engagement itself, so its
# in_scope column is always hardcoded True and scope_guard never decides it.
_ALWAYS_IN_SCOPE_TYPES = {"ENGAGEMENT"}

# EVIDENCE has no in_scope column at all (schema.py).
_NO_IN_SCOPE_COLUMN_TYPES = {"EVIDENCE"}

# Node types whose schema includes a `confidence` column.
_CONFIDENCE_BEARING_TYPES = {"SECRET", "FINDING"}

# Types whose tombstone also flips `status` to 'merged'.
_STATUS_BEARING_TYPES = {"SECRET", "FINDING"}


class MutationSource(str, Enum):
    DISPATCHER = "dispatcher"
    INGESTION = "ingestion"
    VALIDATION = "validation"
    RECONCILIATION = "reconciliation"
    LIFECYCLE = "lifecycle"


def _literal(value: Any) -> str:
    """Render a Python value as a Cypher literal (VALUES only, never names)."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


class GraphMutationAuthority:
    """Privileged, typed graph-mutation API. Not a raw-Cypher executor."""

    def __init__(self, conn: kuzu.Connection, scope: ScopeGuard) -> None:
        self._conn = conn
        self._scope = scope
        self._checkpoint_pending = False

    def _run(self, query: str, params: dict[str, Any]) -> None:
        self._conn.execute(query, params)

    def _commit_batch(self) -> None:
        # Checkpoint after each mutation batch so a fresh read-only handle
        # (SPEC_BRIEF31 §4.4 option c) observes the committed state.
        self._conn.execute("CHECKPOINT")

    @staticmethod
    def _check_source(source: MutationSource) -> None:
        if not isinstance(source, MutationSource):
            raise ValueError(f"source must be a MutationSource, got {source!r}")

    def create_or_update_node(
        self,
        type: str,
        id: str,
        props: dict[str, Any],
        scope_key: str | None,
        source: MutationSource,
    ) -> None:
        self._check_source(source)
        if type not in ALL_NODE_TABLES:
            raise ValueError(f"unknown node type {type!r}")

        forbidden = props.keys() & NODE_PROPS_FORBIDDEN
        if forbidden:
            raise ValueError(
                f"props contains {sorted(forbidden)}, which are computed by "
                f"scope_guard/lifecycle, never caller-settable"
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
                # SPEC_BRIEF10.4 §1.5: `scope_key or id` precedence unchanged.
                if scope_key:
                    in_scope = self._scope.is_in_scope(scope_key, node_type=type, target_kind="scope_key")
                else:
                    in_scope = self._scope.is_in_scope(id, node_type=type, target_kind="id")
            in_scope_clause = f"n.in_scope = {_literal(in_scope)}"
            create_clauses.append(in_scope_clause)
            match_clauses.append(in_scope_clause)

        if type in _CONFIDENCE_BEARING_TYPES:
            create_clauses.append("n.confidence = 0")

        if "created_at" in create_only:
            created_at = props.get("created_at", datetime.now(timezone.utc).isoformat())
            create_clauses.append(f"n.created_at = {_literal(created_at)}")
        for key in props:
            if key in create_only and key != "created_at":
                create_clauses.append(f"n.{key} = {_literal(props[key])}")

        create_sql = ", ".join(create_clauses)
        query = f"MERGE (n:{type} {{id: $id}}) ON CREATE SET {create_sql}"
        if match_clauses:
            query += f" ON MATCH SET {', '.join(match_clauses)}"
        self._run(query, {"id": id})
        self._commit_batch()

    def upsert_edge(
        self,
        label: str,
        from_id: str,
        from_type: str,
        to_id: str,
        to_type: str,
        props: dict[str, Any] | None,
        source: MutationSource,
    ) -> None:
        self._check_source(source)
        if label not in EDGE_PAIRS:
            raise ValueError(f"unknown edge label {label!r}")
        if from_type not in ALL_NODE_TABLES or to_type not in ALL_NODE_TABLES:
            raise ValueError(f"unknown node type in edge {from_type!r}/{to_type!r}")
        if props:
            # No REL TABLE in schema.py declares any property column.
            raise ValueError(f"edge props contain non-whitelisted column(s) {sorted(props)}")
        self._run(
            f"MATCH (a:{from_type} {{id: $from_id}}), (b:{to_type} {{id: $to_id}}) "
            f"MERGE (a)-[r:{label}]->(b)",
            {"from_id": from_id, "to_id": to_id},
        )
        self._commit_batch()

    def set_secret_lifecycle(
        self, id: str, *, status: str, confidence: int, scope_note: str | None, source: MutationSource
    ) -> None:
        self._check_source(source)
        self._run(
            "MATCH (s:SECRET {id: $id}) SET s.status = $status, s.confidence = $confidence, s.scope_note = $scope_note",
            {"id": id, "status": status, "confidence": confidence, "scope_note": scope_note},
        )
        self._commit_batch()

    def set_finding_lifecycle(self, id: str, *, status: str, confidence: int, source: MutationSource) -> None:
        self._check_source(source)
        self._run(
            "MATCH (f:FINDING {id: $id}) SET f.status = $status, f.confidence = $confidence",
            {"id": id, "status": status, "confidence": confidence},
        )
        self._commit_batch()

    def tombstone(self, node_type: str, id: str, survivor: str, source: MutationSource) -> None:
        self._check_source(source)
        if node_type not in ALL_NODE_TABLES:
            raise ValueError(f"unknown node type {node_type!r}")
        if node_type in _STATUS_BEARING_TYPES:
            query = f"MATCH (n:{node_type} {{id: $id}}) SET n.status = 'merged', n.merged_into = $survivor"
        else:
            query = f"MATCH (n:{node_type} {{id: $id}}) SET n.merged_into = $survivor"
        self._run(query, {"id": id, "survivor": survivor})
        self._commit_batch()

    def delete_loser_edges(self, node_type: str, loser_id: str, source: MutationSource) -> None:
        self._check_source(source)
        if node_type not in ALL_NODE_TABLES:
            raise ValueError(f"unknown node type {node_type!r}")
        for label, pairs in EDGE_PAIRS.items():
            for frm, to in pairs:
                if frm == node_type:
                    self._run(
                        f"MATCH (a:{frm} {{id: $id}})-[r:{label}]->(b:{to}) DELETE r", {"id": loser_id}
                    )
                if to == node_type:
                    self._run(
                        f"MATCH (a:{frm})-[r:{label}]->(b:{to} {{id: $id}}) DELETE r", {"id": loser_id}
                    )
        self._commit_batch()
