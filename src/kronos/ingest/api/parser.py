"""API ingestion source: declarative endpoint-inventory JSON -> API_ENDPOINT (SPEC_BRIEF R8).

Mirrors `ingest/cloud/parser.py`: two thin faces on one core. The core
returns plans only; this module never calls the graph write methods —
`apply_plan`/`apply_upserts` do, so scope-gating and prop-allowlisting
happen in one place. Hermetic: stdlib `json` only, no network, no SDK.
Input is untrusted; declined items carry reasons, never raw input.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from kronos.events import emit
from kronos.ingest import EdgeUpsert, NodeUpsert
from kronos.ingest.contract import DeclinedItem, IngestPlan, SourceDescriptor, build_report

if TYPE_CHECKING:  # pragma: no cover
    from kronos.graph import EngagementGraph

API_INVENTORY_SOURCE = SourceDescriptor(name="api-inventory", version="1")

_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})


def _text(item: Any, key: str) -> str | None:
    """Non-empty string field of a dict item, else None."""
    if not isinstance(item, dict):
        return None
    value = item.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _ingest_api_inventory_core(
    inventory_json: str, engagement: "EngagementGraph"
) -> tuple[list[NodeUpsert | EdgeUpsert], list[DeclinedItem]]:
    engagement_dir = engagement.db_path.parent
    upserts: list[NodeUpsert | EdgeUpsert] = []
    declined: list[DeclinedItem] = []

    def decline(reason: str, detail: str) -> None:
        declined.append(DeclinedItem(reason=reason, detail=detail))
        emit(engagement_dir, "ingest_declined", reason=reason, detail=detail)

    emit(
        engagement_dir,
        "ingest_started",
        source_name=API_INVENTORY_SOURCE.name,
        source_version=API_INVENTORY_SOURCE.version,
    )

    doc: Any = None
    try:
        doc = json.loads(inventory_json)
    except (ValueError, TypeError, RecursionError):
        pass

    endpoints: list = []
    if isinstance(doc, dict):
        endpoints = doc.get("endpoints", [])
        if not isinstance(endpoints, list):
            doc = None

    if not isinstance(doc, dict):
        decline("unparseable_api_inventory", "api inventory failed to parse as a JSON object")
    else:
        for item in endpoints:
            url = _text(item, "url")
            if url is None:
                decline("missing_endpoint_url", "endpoint item has no url")
                continue
            method = _text(item, "method")
            method = method.strip().upper() if method is not None else None
            if method not in _METHODS:
                decline("missing_or_invalid_method", "endpoint item has no valid method")
                continue
            upserts.append(
                NodeUpsert(
                    "API_ENDPOINT",
                    url,
                    {"url": url, "method": method, "source": API_INVENTORY_SOURCE.name},
                    scope_key=url,
                )
            )

    emit(
        engagement_dir,
        "ingest_finished",
        source_name=API_INVENTORY_SOURCE.name,
        node_count=sum(1 for u in upserts if isinstance(u, NodeUpsert)),
        edge_count=sum(1 for u in upserts if isinstance(u, EdgeUpsert)),
        declined_count=len(declined),
    )
    return upserts, declined


def ingest_api_inventory(inventory_json: str, engagement: "EngagementGraph") -> list[NodeUpsert | EdgeUpsert]:
    """Bare-list face (not yet wired into the `ingest()` dispatcher)."""
    upserts, _declined = _ingest_api_inventory_core(inventory_json, engagement)
    return upserts


def ingest_api_inventory_plan(inventory_json: str, engagement: "EngagementGraph") -> IngestPlan:
    """`IngestionSource`-conforming face: same core, wrapped in an `IngestPlan`."""
    upserts, declined = _ingest_api_inventory_core(inventory_json, engagement)
    return IngestPlan(upserts=tuple(upserts), report=build_report(API_INVENTORY_SOURCE, upserts, declined))
