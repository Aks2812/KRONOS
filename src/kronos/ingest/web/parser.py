"""Web ingestion source: OpenAPI 3 JSON -> WEB_ENDPOINT, PARAMETER (SPEC_BRIEF13).

Mirrors `ingest/infra/parser.py`: two thin faces on one core. The core
returns plans only; this module never calls the graph write methods.
Reading the graph (`engagement.get_node`) for the S3 seed check is
read-only. Input is untrusted: stdlib `json` only, no network, and
declined items carry reasons, never raw input.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from kronos.events import emit
from kronos.ingest import EdgeUpsert, NodeUpsert
from kronos.ingest.contract import DeclinedItem, IngestPlan, SourceDescriptor, build_report

if TYPE_CHECKING:  # pragma: no cover
    from kronos.graph import EngagementGraph

WEB_OPENAPI_SOURCE = SourceDescriptor(name="openapi", version="1")

_DEFAULT_SERVER_URL = "http://127.0.0.1"
_METHODS = ("get", "post", "put", "patch", "delete")


def _ingest_web_openapi_core(
    openapi_json: Any, engagement: "EngagementGraph"
) -> tuple[list[NodeUpsert | EdgeUpsert], list[DeclinedItem]]:
    engagement_dir = engagement.db_path.parent
    upserts: list[NodeUpsert | EdgeUpsert] = []
    declined: list[DeclinedItem] = []

    def decline(reason: str, detail: str) -> None:
        declined.append(DeclinedItem(reason=reason, detail=detail))
        emit(engagement_dir, "ingest_declined", reason=reason, detail=detail)

    emit(engagement_dir, "ingest_started", source_name=WEB_OPENAPI_SOURCE.name, source_version=WEB_OPENAPI_SOURCE.version)

    doc: Any = None
    if isinstance(openapi_json, (str, bytes)):
        try:
            doc = json.loads(openapi_json)
        except (ValueError, TypeError):
            doc = None
    elif openapi_json is not None:
        doc = openapi_json
    if not isinstance(doc, dict):
        decline("unparseable_openapi_json", "OpenAPI input is missing, unparseable, or not a JSON object")
        doc = None

    host = None
    port = None
    server_base = ""
    if doc is not None:
        servers = doc.get("servers")
        first = servers[0] if isinstance(servers, list) and servers else None
        server_url = first.get("url") if isinstance(first, dict) else None
        if not isinstance(server_url, str):
            server_url = _DEFAULT_SERVER_URL  # no servers[0].url: brief default
        try:
            parts = urlsplit(server_url)
            host = parts.hostname
            port = parts.port
            scheme = parts.scheme
        except ValueError:
            host = None
        if not host:
            decline("malformed_server_url", "servers[0].url is not a usable URL")
            host = None
        else:
            server_base = server_url.rstrip("/")
            if port is None:
                port = 443 if scheme == "https" else 80

    paths = doc.get("paths") if host else None
    if host and not isinstance(paths, dict):
        decline("missing_paths", "OpenAPI document has no paths object")
        paths = None

    for path, item in (paths or {}).items():
        if not isinstance(item, dict):
            decline("malformed_path_item", "path item is not an object")
            continue
        path_params = item.get("parameters")
        path_params = path_params if isinstance(path_params, list) else []
        for method_key, op in item.items():
            if method_key.lower() not in _METHODS:
                continue
            if not isinstance(op, dict):
                decline("malformed_operation", "operation is not an object")
                continue
            method = method_key.upper()
            url = f"{server_base}{path}"
            endpoint_id = f"web:{method}:{url}"
            upserts.append(
                NodeUpsert("WEB_ENDPOINT", endpoint_id, {"source": "openapi", "url": url, "method": method}, scope_key=host)
            )
            expected_sid = f"{host}:{port}/tcp"
            if engagement.get_node("SERVICE", expected_sid) is not None:
                upserts.append(EdgeUpsert("exposes", expected_sid, endpoint_id))
            op_params = op.get("parameters")
            for param in path_params + (op_params if isinstance(op_params, list) else []):
                name = param.get("name") if isinstance(param, dict) else None
                param_in = param.get("in") if isinstance(param, dict) else None
                if not isinstance(name, str) or not name or not isinstance(param_in, str) or not param_in:
                    decline("malformed_parameter", "parameter missing name or in")
                    continue
                param_id = f"param:{endpoint_id}:{param_in}:{name}"
                upserts.append(
                    NodeUpsert(
                        "PARAMETER", param_id, {"source": "openapi", "name": name, "param_type": param_in}, scope_key=host
                    )
                )
                upserts.append(EdgeUpsert("has_param", endpoint_id, param_id))

    emit(
        engagement_dir,
        "ingest_finished",
        source_name=WEB_OPENAPI_SOURCE.name,
        node_count=sum(1 for u in upserts if isinstance(u, NodeUpsert)),
        edge_count=sum(1 for u in upserts if isinstance(u, EdgeUpsert)),
        declined_count=len(declined),
    )
    return upserts, declined


def ingest_web_openapi(openapi_json: Any, engagement: "EngagementGraph") -> list[NodeUpsert | EdgeUpsert]:
    """Bare-list face, wired into the `ingest()` dispatcher."""
    upserts, _declined = _ingest_web_openapi_core(openapi_json, engagement)
    return upserts


def ingest_web_openapi_plan(openapi_json: Any, engagement: "EngagementGraph") -> IngestPlan:
    """`IngestionSource`-conforming face: same core, wrapped in an `IngestPlan`."""
    upserts, declined = _ingest_web_openapi_core(openapi_json, engagement)
    return IngestPlan(upserts=tuple(upserts), report=build_report(WEB_OPENAPI_SOURCE, upserts, declined))
