"""Kùzu DDL for the findings graph (SPEC.md "NODE TYPES" / "EDGE TYPES").

One DB file per engagement, fully isolated (SPEC.md decision — no server,
no shared DB). `init_db` is idempotent: every statement uses
`IF NOT EXISTS`, confirmed supported by Kùzu 0.11.3, so re-opening an
existing engagement DB never fails.

Edge-pair choices (which FROM/TO node-type pairs each edge label spans)
are this module's own design calls, not dictated by SPEC.md beyond the
edge label list itself — see DECISIONS.md for the full rationale per
label.
"""

from __future__ import annotations

from pathlib import Path

import kuzu

# Every scope-target node table gets: id, in_scope, created_at, source.
# ENGAGEMENT and EVIDENCE are not scope targets (see DECISIONS.md) and
# carry their own fixed property sets instead.
_NODE_TABLES = """
CREATE NODE TABLE IF NOT EXISTS ENGAGEMENT(
    id STRING, client STRING, authorized_by STRING,
    window_start STRING, window_end STRING, destructive_allowed BOOLEAN,
    in_scope BOOLEAN, created_at STRING,
    PRIMARY KEY(id)
);
CREATE NODE TABLE IF NOT EXISTS HOST(
    id STRING, in_scope BOOLEAN, created_at STRING, source STRING,
    PRIMARY KEY(id)
);
CREATE NODE TABLE IF NOT EXISTS SERVICE(
    id STRING, in_scope BOOLEAN, created_at STRING, source STRING,
    port INT64, protocol STRING,
    PRIMARY KEY(id)
);
CREATE NODE TABLE IF NOT EXISTS WEB_ENDPOINT(
    id STRING, in_scope BOOLEAN, created_at STRING, source STRING,
    url STRING, method STRING,
    PRIMARY KEY(id)
);
CREATE NODE TABLE IF NOT EXISTS PARAMETER(
    id STRING, in_scope BOOLEAN, created_at STRING, source STRING,
    name STRING, param_type STRING,
    PRIMARY KEY(id)
);
CREATE NODE TABLE IF NOT EXISTS API_ENDPOINT(
    id STRING, in_scope BOOLEAN, created_at STRING, source STRING,
    url STRING, method STRING,
    PRIMARY KEY(id)
);
CREATE NODE TABLE IF NOT EXISTS MOBILE_APP(
    id STRING, in_scope BOOLEAN, created_at STRING, source STRING,
    bundle_id STRING, platform STRING,
    PRIMARY KEY(id)
);
CREATE NODE TABLE IF NOT EXISTS MOBILE_COMPONENT(
    id STRING, in_scope BOOLEAN, created_at STRING, source STRING,
    component_type STRING, name STRING,
    PRIMARY KEY(id)
);
CREATE NODE TABLE IF NOT EXISTS SECRET(
    id STRING, in_scope BOOLEAN, created_at STRING, source STRING,
    value_ref STRING, kind STRING, status STRING, confidence INT64,
    scope_note STRING,
    PRIMARY KEY(id)
);
CREATE NODE TABLE IF NOT EXISTS IDENTITY(
    id STRING, in_scope BOOLEAN, created_at STRING, source STRING,
    name STRING, provider STRING,
    PRIMARY KEY(id)
);
CREATE NODE TABLE IF NOT EXISTS CLOUD_RESOURCE(
    id STRING, in_scope BOOLEAN, created_at STRING, source STRING,
    resource_type STRING, provider STRING,
    PRIMARY KEY(id)
);
CREATE NODE TABLE IF NOT EXISTS TECHNOLOGY(
    id STRING, in_scope BOOLEAN, created_at STRING, source STRING,
    name STRING, version STRING,
    PRIMARY KEY(id)
);
CREATE NODE TABLE IF NOT EXISTS FINDING(
    id STRING, in_scope BOOLEAN, created_at STRING, source STRING,
    title STRING, severity STRING, status STRING, confidence INT64,
    PRIMARY KEY(id)
);
CREATE NODE TABLE IF NOT EXISTS EVIDENCE(
    id STRING, created_at STRING, sha256 STRING, blob_path STRING, kind STRING,
    PRIMARY KEY(id)
);
"""

# Edge label -> (FROM, TO) pairs, exactly mirroring SCHEMA_DDL below.
# Kept as data so other modules (and tests) can introspect the model
# without re-parsing DDL text.
EDGE_PAIRS: dict[str, list[tuple[str, str]]] = {
    "hosts": [("HOST", "SERVICE"), ("CLOUD_RESOURCE", "HOST"), ("CLOUD_RESOURCE", "SERVICE")],
    "exposes": [
        ("HOST", "WEB_ENDPOINT"), ("HOST", "API_ENDPOINT"),
        ("SERVICE", "WEB_ENDPOINT"), ("SERVICE", "API_ENDPOINT"),
    ],
    "has_param": [("WEB_ENDPOINT", "PARAMETER"), ("API_ENDPOINT", "PARAMETER")],
    "contains": [("MOBILE_APP", "MOBILE_COMPONENT")],
    "leaks": [
        ("MOBILE_APP", "SECRET"), ("MOBILE_COMPONENT", "SECRET"),
        ("API_ENDPOINT", "SECRET"), ("WEB_ENDPOINT", "SECRET"),
    ],
    "references": [
        ("MOBILE_APP", "API_ENDPOINT"), ("MOBILE_COMPONENT", "API_ENDPOINT"),
        ("WEB_ENDPOINT", "API_ENDPOINT"), ("FINDING", "SECRET"), ("FINDING", "EVIDENCE"),
    ],
    "authenticates_to": [
        ("SECRET", "API_ENDPOINT"), ("SECRET", "CLOUD_RESOURCE"), ("SECRET", "HOST"),
        ("IDENTITY", "API_ENDPOINT"), ("IDENTITY", "CLOUD_RESOURCE"),
    ],
    "grants": [("IDENTITY", "CLOUD_RESOURCE")],
    "shares_cred_with": [("SECRET", "SECRET")],
    "depends_on": [("SERVICE", "SERVICE"), ("API_ENDPOINT", "SERVICE"), ("CLOUD_RESOURCE", "CLOUD_RESOURCE")],
    "vulnerable_to": [
        ("HOST", "FINDING"), ("SERVICE", "FINDING"), ("WEB_ENDPOINT", "FINDING"),
        ("API_ENDPOINT", "FINDING"), ("CLOUD_RESOURCE", "FINDING"),
        ("MOBILE_APP", "FINDING"), ("MOBILE_COMPONENT", "FINDING"),
    ],
    "resolves_to": [("HOST", "HOST"), ("API_ENDPOINT", "HOST"), ("WEB_ENDPOINT", "HOST")],
    "chains_to": [
        ("API_ENDPOINT", "HOST"), ("API_ENDPOINT", "CLOUD_RESOURCE"),
        ("HOST", "CLOUD_RESOURCE"), ("SERVICE", "CLOUD_RESOURCE"), ("FINDING", "FINDING"),
    ],
    "evidences": [("EVIDENCE", "FINDING"), ("EVIDENCE", "SECRET")],
}


def _rel_table_group_ddl() -> str:
    statements = []
    for label, pairs in EDGE_PAIRS.items():
        # Kuzu's "FROM x TO y" clauses, comma-separated within one GROUP.
        pair_sql = ", ".join(f"FROM {frm} TO {to_}" for frm, to_ in pairs)
        statements.append(f"CREATE REL TABLE GROUP IF NOT EXISTS {label}({pair_sql});")
    return "\n".join(statements)


SCHEMA_DDL = _NODE_TABLES + "\n" + _rel_table_group_ddl() + "\n"

ALL_NODE_TABLES = [
    "ENGAGEMENT", "HOST", "SERVICE", "WEB_ENDPOINT", "PARAMETER", "API_ENDPOINT",
    "MOBILE_APP", "MOBILE_COMPONENT", "SECRET", "IDENTITY", "CLOUD_RESOURCE",
    "TECHNOLOGY", "FINDING", "EVIDENCE",
]

# Columns `EngagementGraph.upsert_node` may write from caller-supplied
# `props` on EVERY call (create and re-merge alike). Deliberately
# excludes `id` (the MERGE key, never a SET target), `in_scope`
# (scope_guard's alone — see graph.py's _ALWAYS_IN_SCOPE_TYPES /
# _NO_IN_SCOPE_COLUMN_TYPES), `created_at` (create-only, see below), and
# `status`/`confidence`/`scope_note` (lifecycle.py's alone after
# creation — see NODE_PROPS_CREATE_ONLY and DECISIONS.md's "upsert_node
# prop allowlist" entry for why this exists at all).
NODE_PROPS_ALWAYS: dict[str, set[str]] = {
    "ENGAGEMENT": {"client", "authorized_by", "window_start", "window_end", "destructive_allowed"},
    "HOST": {"source"},
    "SERVICE": {"source", "port", "protocol"},
    "WEB_ENDPOINT": {"source", "url", "method"},
    "PARAMETER": {"source", "name", "param_type"},
    "API_ENDPOINT": {"source", "url", "method"},
    "MOBILE_APP": {"source", "bundle_id", "platform"},
    "MOBILE_COMPONENT": {"source", "component_type", "name"},
    "SECRET": {"source", "value_ref", "kind"},
    "IDENTITY": {"source", "name", "provider"},
    "CLOUD_RESOURCE": {"source", "resource_type", "provider"},
    "TECHNOLOGY": {"source", "name", "version"},
    "FINDING": {"source", "title", "severity"},
    "EVIDENCE": {"sha256", "blob_path", "kind"},
}

# Columns settable via `props` ONLY on the node's first creation. A
# caller may resupply them on a later upsert_node call (e.g. a parser
# re-running over the same raw input) without error, but the resupplied
# value is silently ignored rather than overwriting what's already
# there — `created_at` is immutable once stamped, and `status`'s initial
# value is an ingester's business, but every change after creation must
# go through lifecycle.py's advance_secret_status/advance_finding_status,
# never through a second upsert_node call.
NODE_PROPS_CREATE_ONLY: dict[str, set[str]] = {
    "SECRET": {"status"},
    "FINDING": {"status"},
}
# created_at is create-only for every node type that has the column
# (every type except EVIDENCE's own handling is identical — EVIDENCE
# also has created_at and follows the same rule).
for _table in ALL_NODE_TABLES:
    NODE_PROPS_CREATE_ONLY.setdefault(_table, set()).add("created_at")
del _table

# Columns `upsert_node` computes itself and will never accept from
# `props` under any circumstance — passing one of these raises
# ValueError rather than silently dropping it, so a caller finds out
# immediately rather than wondering later why its value didn't take.
NODE_PROPS_FORBIDDEN: set[str] = {"id", "in_scope", "confidence", "scope_note"}

# The full set of real, queryable columns per node type (mirrors the DDL
# in `_NODE_TABLES` exactly, same pattern as `EDGE_PAIRS`). Used by
# `query.py` to validate `node_type`/filter keys before they reach any
# Cypher text — unlike the write-side registries above, this one is
# unrestricted: a read filter on `status`/`confidence`/`in_scope` is
# completely legitimate (e.g. `list_findings(status=...)`), it's only
# *writing* those columns through `upsert_node` that's restricted.
NODE_COLUMNS: dict[str, set[str]] = {
    "ENGAGEMENT": {"id", "client", "authorized_by", "window_start", "window_end", "destructive_allowed", "in_scope", "created_at"},
    "HOST": {"id", "in_scope", "created_at", "source"},
    "SERVICE": {"id", "in_scope", "created_at", "source", "port", "protocol"},
    "WEB_ENDPOINT": {"id", "in_scope", "created_at", "source", "url", "method"},
    "PARAMETER": {"id", "in_scope", "created_at", "source", "name", "param_type"},
    "API_ENDPOINT": {"id", "in_scope", "created_at", "source", "url", "method"},
    "MOBILE_APP": {"id", "in_scope", "created_at", "source", "bundle_id", "platform"},
    "MOBILE_COMPONENT": {"id", "in_scope", "created_at", "source", "component_type", "name"},
    "SECRET": {"id", "in_scope", "created_at", "source", "value_ref", "kind", "status", "confidence", "scope_note"},
    "IDENTITY": {"id", "in_scope", "created_at", "source", "name", "provider"},
    "CLOUD_RESOURCE": {"id", "in_scope", "created_at", "source", "resource_type", "provider"},
    "TECHNOLOGY": {"id", "in_scope", "created_at", "source", "name", "version"},
    "FINDING": {"id", "in_scope", "created_at", "source", "title", "severity", "status", "confidence"},
    "EVIDENCE": {"id", "created_at", "sha256", "blob_path", "kind"},
}


def init_db(db_path: str | Path) -> kuzu.Database:
    """Open (creating if absent) the one-file-per-engagement Kùzu DB and
    ensure the full schema exists. Idempotent: safe to call on an
    already-initialized DB.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = kuzu.Database(str(path))
    conn = kuzu.Connection(db)
    conn.execute(SCHEMA_DDL)
    return db
