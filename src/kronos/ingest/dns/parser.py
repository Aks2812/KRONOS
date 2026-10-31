"""DNS-resolution ingestion source: tool-neutral JSON records -> HOST, resolves_to (SPEC_BRIEF26).

Input is a JSON list of {"name", "type": A|AAAA|CNAME, "value"} records.
Mirrors `ingest/infra/parser.py`: two thin faces on one core that never
writes the graph (`apply_plan`/`apply_upserts` do). Stdlib only, no
network, no lifecycle events; declined items carry reasons, never raw input.
"""

from __future__ import annotations

import ipaddress
import json
import re
from typing import TYPE_CHECKING

from kronos.ingest import EdgeUpsert, NodeUpsert
from kronos.ingest.contract import DeclinedItem, IngestPlan, SourceDescriptor, build_report

if TYPE_CHECKING:  # pragma: no cover
    from kronos.graph import EngagementGraph

DNS_SOURCE = SourceDescriptor(name="dns", version="1")

_FQDN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")


def _norm_fqdn(value: str) -> str | None:
    candidate = value.lower()
    if candidate.endswith("."):
        candidate = candidate[:-1]
    if not candidate or not _FQDN_RE.match(candidate):
        return None
    if len(candidate) > 253 or any(not 1 <= len(label) <= 63 for label in candidate.split(".")):
        return None
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return candidate
    return None  # an IP literal is not an FQDN


def _ingest_dns_records_core(
    raw: str, engagement: "EngagementGraph"
) -> tuple[list[NodeUpsert | EdgeUpsert], list[DeclinedItem]]:
    upserts: list[NodeUpsert | EdgeUpsert] = []
    declined: list[DeclinedItem] = []

    try:
        records = json.loads(raw)
    except (ValueError, TypeError):
        records = None
    if not isinstance(records, list):
        declined.append(
            DeclinedItem(
                reason="unparseable_dns_json",
                detail="DNS input is missing, unparseable, or not a JSON list",
            )
        )
        return upserts, declined

    def decline(reason: str, detail: str) -> None:
        declined.append(DeclinedItem(reason=reason, detail=detail))

    for rec in records:
        if not isinstance(rec, dict) or not all(
            isinstance(rec.get(k), str) for k in ("name", "type", "value")
        ):
            decline("missing_field", "record is not an object with string name, type, value")
            continue
        rtype = rec["type"]
        if rtype not in ("A", "AAAA", "CNAME"):
            decline("unsupported_record_type", "record type is not one of A, AAAA, CNAME")
            continue
        name = _norm_fqdn(rec["name"])
        if name is None:
            decline("malformed_fqdn", "record name is not a valid FQDN")
            continue
        value: str | None
        if rtype == "CNAME":
            value = _norm_fqdn(rec["value"])
            if value is None:
                decline("malformed_fqdn", "CNAME value is not a valid FQDN")
                continue
        else:
            cls = ipaddress.IPv4Address if rtype == "A" else ipaddress.IPv6Address
            try:
                cls(rec["value"])
            except ValueError:
                decline("malformed_address", f"{rtype} value is not a valid address of that family")
                continue
            value = rec["value"]

        src = {"source": DNS_SOURCE.name}
        upserts.append(NodeUpsert("HOST", name, dict(src), scope_key=name))
        upserts.append(NodeUpsert("HOST", value, dict(src), scope_key=value))
        upserts.append(EdgeUpsert("resolves_to", name, value))

    return upserts, declined


def ingest_dns_records(raw: str, engagement: "EngagementGraph") -> list[NodeUpsert | EdgeUpsert]:
    """Bare-list face, wired into the `ingest()` dispatcher."""
    upserts, _declined = _ingest_dns_records_core(raw, engagement)
    return upserts


def ingest_dns_records_plan(raw: str, engagement: "EngagementGraph") -> IngestPlan:
    """`IngestionSource`-conforming face: same core, wrapped in an `IngestPlan`."""
    upserts, declined = _ingest_dns_records_core(raw, engagement)
    return IngestPlan(upserts=tuple(upserts), report=build_report(DNS_SOURCE, upserts, declined))
