"""Infra ingestion source: nmap XML -> HOST, SERVICE (SPEC_BRIEF11).

Mirrors `ingest/mobile/parser.py`: two thin faces on one core. The core
returns plans only; this module never calls the graph write methods —
`apply_plan`/`apply_upserts` do, so scope-gating and prop-allowlisting
happen in one place. nmap XML is untrusted: stdlib ElementTree only (no
external entity resolution, no network), and declined items carry
reasons, never raw input.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from kronos.events import emit
from kronos.ingest import EdgeUpsert, NodeUpsert
from kronos.ingest.contract import DeclinedItem, IngestPlan, SourceDescriptor, build_report

if TYPE_CHECKING:  # pragma: no cover
    from kronos.graph import EngagementGraph

INFRA_NMAP_SOURCE = SourceDescriptor(name="nmap", version="1")


def _ingest_infra_nmap_core(
    nmap_xml: str, engagement: "EngagementGraph"
) -> tuple[list[NodeUpsert | EdgeUpsert], list[DeclinedItem]]:
    engagement_dir = engagement.db_path.parent
    upserts: list[NodeUpsert | EdgeUpsert] = []
    declined: list[DeclinedItem] = []

    def decline(reason: str, detail: str) -> None:
        declined.append(DeclinedItem(reason=reason, detail=detail))
        emit(engagement_dir, "ingest_declined", reason=reason, detail=detail)

    emit(engagement_dir, "ingest_started", source_name=INFRA_NMAP_SOURCE.name, source_version=INFRA_NMAP_SOURCE.version)

    try:
        root = ET.fromstring(nmap_xml)
    except (ET.ParseError, ValueError, TypeError):
        decline("unparseable_nmap_xml", "nmap XML failed to parse")
        root = None

    for host_el in root.iter("host") if root is not None else ():
        host_id = None
        for addr_el in host_el.findall("address"):
            addr = (addr_el.get("addr") or "").strip()
            if addr and addr_el.get("addrtype") != "mac":
                host_id = addr
                break
        if host_id is None:
            decline("missing_address", "host element has no usable address")
            continue

        upserts.append(NodeUpsert("HOST", host_id, {"source": "nmap"}, scope_key=host_id))

        for port_el in host_el.findall("./ports/port"):
            portid = port_el.get("portid") or ""
            protocol = port_el.get("protocol") or ""
            state_el = port_el.find("state")
            if state_el is None or state_el.get("state") != "open":
                decline("port_not_open", "port is not in state open; no SERVICE emitted")
                continue
            if not portid.isdigit() or not protocol:
                decline("malformed_port", "port element missing numeric portid or protocol")
                continue
            service_id = f"{host_id}:{portid}/{protocol}"
            upserts.append(
                NodeUpsert(
                    "SERVICE",
                    service_id,
                    {"port": int(portid), "protocol": protocol, "source": "nmap"},
                    scope_key=f"{host_id}:{portid}",
                )
            )
            upserts.append(EdgeUpsert("hosts", host_id, service_id))

    emit(
        engagement_dir,
        "ingest_finished",
        source_name=INFRA_NMAP_SOURCE.name,
        node_count=sum(1 for u in upserts if isinstance(u, NodeUpsert)),
        edge_count=sum(1 for u in upserts if isinstance(u, EdgeUpsert)),
        declined_count=len(declined),
    )
    return upserts, declined


def ingest_infra_nmap(nmap_xml: str, engagement: "EngagementGraph") -> list[NodeUpsert | EdgeUpsert]:
    """Bare-list face, wired into the `ingest()` dispatcher."""
    upserts, _declined = _ingest_infra_nmap_core(nmap_xml, engagement)
    return upserts


def ingest_infra_nmap_plan(nmap_xml: str, engagement: "EngagementGraph") -> IngestPlan:
    """`IngestionSource`-conforming face: same core, wrapped in an `IngestPlan`."""
    upserts, declined = _ingest_infra_nmap_core(nmap_xml, engagement)
    return IngestPlan(upserts=tuple(upserts), report=build_report(INFRA_NMAP_SOURCE, upserts, declined))
