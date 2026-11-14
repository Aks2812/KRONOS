"""Cloud ingestion source: declarative inventory JSON -> CLOUD_RESOURCE, IDENTITY (SPEC_BRIEF R7).

Mirrors `ingest/infra/parser.py`: two thin faces on one core. The core
returns plans only; this module never calls the graph write methods —
`apply_plan`/`apply_upserts` do, so scope-gating and prop-allowlisting
happen in one place. Hermetic: stdlib `json` only, no provider SDK, no
network. Input is untrusted; declined items carry reasons, never raw input.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from kronos.events import emit
from kronos.ingest import EdgeUpsert, NodeUpsert
from kronos.ingest.contract import DeclinedItem, IngestPlan, SourceDescriptor, build_report

if TYPE_CHECKING:  # pragma: no cover
    from kronos.graph import EngagementGraph

CLOUD_INVENTORY_SOURCE = SourceDescriptor(name="cloud-inventory", version="1")


def _text(item: Any, key: str) -> str | None:
    """Non-empty string field of a dict item, else None."""
    if not isinstance(item, dict):
        return None
    value = item.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _ingest_cloud_inventory_core(
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
        source_name=CLOUD_INVENTORY_SOURCE.name,
        source_version=CLOUD_INVENTORY_SOURCE.version,
    )

    doc: Any = None
    try:
        doc = json.loads(inventory_json)
    except (ValueError, TypeError, RecursionError):
        pass

    sections: dict[str, list] = {}
    if isinstance(doc, dict):
        for key in ("resources", "identities", "grants"):
            value = doc.get(key, [])
            if not isinstance(value, list):
                doc = None
                break
            sections[key] = value

    if not isinstance(doc, dict):
        decline("unparseable_cloud_inventory", "cloud inventory failed to parse as a JSON object")
    else:
        provider = _text(doc, "provider")
        if provider is None:
            decline("missing_provider", "inventory has no provider")
        else:
            resource_ids: set[str] = set()
            identity_ids: set[str] = set()

            for item in sections["resources"]:
                rid = _text(item, "id")
                if rid is None:
                    decline("missing_resource_id", "resource item has no id")
                    continue
                rtype = _text(item, "resource_type")
                if rtype is None:
                    decline("missing_resource_type", "resource item has no resource_type")
                    continue
                upserts.append(
                    NodeUpsert(
                        "CLOUD_RESOURCE",
                        rid,
                        {"resource_type": rtype, "provider": provider, "source": CLOUD_INVENTORY_SOURCE.name},
                        scope_key=rid,
                    )
                )
                resource_ids.add(rid)

            for item in sections["identities"]:
                iid = _text(item, "id")
                if iid is None:
                    decline("missing_identity_id", "identity item has no id")
                    continue
                name = _text(item, "name")
                if name is None:
                    decline("missing_identity_name", "identity item has no name")
                    continue
                upserts.append(
                    NodeUpsert(
                        "IDENTITY",
                        iid,
                        {"name": name, "provider": provider, "source": CLOUD_INVENTORY_SOURCE.name},
                        scope_key=iid,
                    )
                )
                identity_ids.add(iid)

            for item in sections["grants"]:
                iid = _text(item, "identity")
                rid = _text(item, "resource")
                if iid not in identity_ids or rid not in resource_ids:
                    decline("grant_dangling_endpoint", "grant endpoint was not emitted in this inventory")
                    continue
                upserts.append(EdgeUpsert("grants", iid, rid))

    emit(
        engagement_dir,
        "ingest_finished",
        source_name=CLOUD_INVENTORY_SOURCE.name,
        node_count=sum(1 for u in upserts if isinstance(u, NodeUpsert)),
        edge_count=sum(1 for u in upserts if isinstance(u, EdgeUpsert)),
        declined_count=len(declined),
    )
    return upserts, declined


def ingest_cloud_inventory(inventory_json: str, engagement: "EngagementGraph") -> list[NodeUpsert | EdgeUpsert]:
    """Bare-list face (not yet wired into the `ingest()` dispatcher)."""
    upserts, _declined = _ingest_cloud_inventory_core(inventory_json, engagement)
    return upserts


def ingest_cloud_inventory_plan(inventory_json: str, engagement: "EngagementGraph") -> IngestPlan:
    """`IngestionSource`-conforming face: same core, wrapped in an `IngestPlan`."""
    upserts, declined = _ingest_cloud_inventory_core(inventory_json, engagement)
    return IngestPlan(upserts=tuple(upserts), report=build_report(CLOUD_INVENTORY_SOURCE, upserts, declined))
