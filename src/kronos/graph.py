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

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import kuzu

from kronos.manifest import ScopeManifest, load_and_verify
from kronos.commit import (  # noqa: F401  (re-exported: tests introspect these)
    _ALWAYS_IN_SCOPE_TYPES,
    _CONFIDENCE_BEARING_TYPES,
    _NO_IN_SCOPE_COLUMN_TYPES,
    GraphMutationAuthority,
    MutationSource,
)
from kronos.schema import init_db
from kronos.scope_guard import ScopeGuard

class EngagementGraph:
    """One engagement's isolated Kùzu DB, opened under its verified manifest."""

    def __init__(self, db_path: str | Path, manifest: ScopeManifest) -> None:
        self.db_path = Path(db_path)
        self.manifest = manifest
        # Writable handle is private to the authority; init_db creates schema.
        self._db = init_db(self.db_path)
        self.scope = ScopeGuard(manifest)
        self._authority = GraphMutationAuthority(kuzu.Connection(self._db), self.scope)

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
            source=MutationSource.BOOTSTRAP,
        )
        return graph

    def upsert_node(
        self,
        type: str,
        id: str,
        props: dict[str, Any],
        scope_key: str | None = None,
        *,
        source: MutationSource,
    ) -> None:
        """Facade: validation and Cypher live in `GraphMutationAuthority`
        (SPEC_BRIEF31). `source` is required, keyword-only (SPEC_BRIEF32)."""
        self._authority.create_or_update_node(type, id, props, scope_key, source)

    def upsert_edge(
        self,
        label: str,
        from_id: str,
        from_type: str,
        to_id: str,
        to_type: str,
        props: dict[str, Any] | None = None,
        *,
        source: MutationSource,
    ) -> None:
        self._authority.upsert_edge(label, from_id, from_type, to_id, to_type, props, source)

    def get_node(self, type: str, id: str) -> dict[str, Any] | None:
        result = self.execute(f"MATCH (n:{type} {{id: $id}}) RETURN n.*", {"id": id})
        if not result.has_next():
            return None
        columns = result.get_column_names()
        row = result.get_next()
        return {_strip_alias(col): val for col, val in zip(columns, row)}

    @contextmanager
    def _read_batch(self):
        """Fresh read-only handle per logical read batch, closed promptly on
        success and on exception; never cached (SPEC_BRIEF31 §4.4 option c)."""
        db = kuzu.Database(str(self.db_path), read_only=True)
        conn = None
        try:
            conn = kuzu.Connection(db)
            yield conn
        finally:
            if conn is not None:
                conn.close()
            db.close()

    def execute(self, query: str, params: dict[str, Any] | None = None) -> "_Rows":
        """Read-only query API. Writes fail at the kuzu driver (RuntimeError)."""
        with self._read_batch() as conn:
            result = conn.execute(query, params or {})
            return _Rows(result.get_column_names(), _drain(result))


def _drain(result) -> list:
    rows = []
    while result.has_next():
        rows.append(result.get_next())
    return rows


class _Rows:
    """Materialized result: valid after the read-only handle is closed."""

    def __init__(self, columns: list[str], rows: list) -> None:
        self._columns = columns
        self._rows = rows
        self._i = 0

    def has_next(self) -> bool:
        return self._i < len(self._rows)

    def get_next(self):
        row = self._rows[self._i]
        self._i += 1
        return row

    def get_column_names(self) -> list[str]:
        return self._columns


def _strip_alias(column_name: str) -> str:
    """Kùzu returns `n.*` columns as `n.prop_name`; strip the `n.` prefix."""
    return column_name.split(".", 1)[1] if "." in column_name else column_name
