"""Ingestion contract (SPEC.md "INGESTION CONTRACT"): turn raw tool output
into a list of node/edge upserts, then apply them idempotently.

Only one parser is implemented this brief — `ingest_reference_mobile_secret`,
the hardcoded worked example proving the contract end to end (a mobile
app leaking a secret). Every other `tool_name` is a stub: real parsers are
a later brief.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from kronos.schema import ALL_NODE_TABLES

if TYPE_CHECKING:  # pragma: no cover - avoids a runtime import cycle with graph.py
    from kronos.graph import EngagementGraph


@dataclass(frozen=True)
class NodeUpsert:
    type: str
    id: str
    props: dict[str, Any]
    scope_key: str | None = None


@dataclass(frozen=True)
class EdgeUpsert:
    label: str
    from_id: str
    to_id: str
    props: dict[str, Any] | None = None


def ingest_reference_mobile_secret(bundle_id: str = "com.kronos.demo") -> list[NodeUpsert | EdgeUpsert]:
    """The one worked example: a mobile app leaking a hardcoded secret.

    Proves the ingestion contract (node/edge upserts, MERGE-dedup on
    re-ingestion) without a real parser.
    """
    secret_id = f"secret:{hashlib.sha256(bundle_id.encode()).hexdigest()[:16]}"
    return [
        NodeUpsert("MOBILE_APP", bundle_id, {"bundle_id": bundle_id, "platform": "android", "source": "static"}),
        NodeUpsert(
            "SECRET",
            secret_id,
            {
                "value_ref": "sha256:" + hashlib.sha256(b"demo-key").hexdigest(),
                "kind": "api_key",
                "status": "extracted",
                "source": "static",
            },
            scope_key=bundle_id,
        ),
        EdgeUpsert("leaks", bundle_id, secret_id),
    ]


def ingest(raw_tool_output: Any, tool_name: str, engagement: "EngagementGraph") -> list[NodeUpsert | EdgeUpsert]:
    """Dispatch by `tool_name`. Only "reference" is implemented."""
    if tool_name == "reference":
        return ingest_reference_mobile_secret()
    raise NotImplementedError(f"parser for tool_name={tool_name!r} not implemented; real parsers are a later brief")


def _resolve_node_type(engagement: "EngagementGraph", node_id: str) -> str:
    for table in ALL_NODE_TABLES:
        if engagement.get_node(table, node_id) is not None:
            return table
    raise ValueError(f"no existing node with id {node_id!r} in any table; apply its NodeUpsert first")


def apply_upserts(engagement: "EngagementGraph", upserts: list[NodeUpsert | EdgeUpsert]) -> None:
    """Write a list of upserts to the graph. MERGE-based, so re-applying
    the exact same list twice (e.g. re-running `ingest()` on identical raw
    input) never creates duplicate nodes or edges."""
    for item in upserts:
        if isinstance(item, NodeUpsert):
            engagement.upsert_node(item.type, item.id, item.props, scope_key=item.scope_key)
        elif isinstance(item, EdgeUpsert):
            from_type = _resolve_node_type(engagement, item.from_id)
            to_type = _resolve_node_type(engagement, item.to_id)
            engagement.upsert_edge(item.label, item.from_id, from_type, item.to_id, to_type, item.props)
        else:
            raise TypeError(f"unknown upsert type: {item!r}")
