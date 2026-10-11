"""`run_reconciliation_pass(graph, engagement_dir) -> MergeReport`
(SPEC_BRIEF4 §3/§2 "PIPELINE PLACEMENT"): group every mergeable node type
by its canonical key and fold each group's duplicates together.

Idempotent by construction: a node already tombstoned by an earlier pass
(`merged_into IS NOT NULL`) is excluded from grouping entirely, so a
second run sees only singleton groups (nothing left to merge) and returns
an empty `MergeReport` without touching the graph — SPEC_BRIEF4 §4 test 4.

Run this after any node-creating pass and before validation
(`ingest -> reconcile -> enrich -> reconcile -> validate`, SPEC_BRIEF4
§2). `engagement_dir` is only needed to decode SECRET evidence blobs for
the canonical-key material (mirrors `validate.runner._decode_secret_value`
exactly, for the same reason: `value_ref` never carries the raw secret
inline on the node).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kronos.evidence import get_evidence
from kronos.reconcile import canonical
from kronos.reconcile.merge import MergeReport, merge_group

if TYPE_CHECKING:  # pragma: no cover
    from kronos.graph import EngagementGraph

_DEFAULT_PASS_NAME = "reconcile"


def _active_ids(graph: "EngagementGraph", node_type: str) -> list[str]:
    """Every node of `node_type` not already tombstoned by a prior pass."""
    result = graph.execute(f"MATCH (n:{node_type}) WHERE n.merged_into IS NULL RETURN n.id")
    ids = []
    while result.has_next():
        ids.append(result.get_next()[0])
    return ids


def _decode_secret_material(engagement_dir: str, value_ref: str) -> str:
    """Mirrors `kronos.validate.runner._decode_secret_value`: a missing
    blob or undecodable bytes degrades to "" -> `canonical_key_for_secret`
    returns `None` for it -> never merged, never crashes."""
    _, _, sha256 = value_ref.partition(":")
    try:
        blob = get_evidence(engagement_dir, sha256)
    except FileNotFoundError:
        return ""
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _group_secrets(graph: "EngagementGraph", engagement_dir: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for secret_id in _active_ids(graph, "SECRET"):
        secret = graph.get_node("SECRET", secret_id)
        material = _decode_secret_material(engagement_dir, secret["value_ref"])
        key = canonical.canonical_key_for_secret(secret["kind"], material)
        if key is not None:
            groups.setdefault(key, []).append(secret_id)
    return groups


def _group_api_endpoints(graph: "EngagementGraph") -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for endpoint_id in _active_ids(graph, "API_ENDPOINT"):
        endpoint = graph.get_node("API_ENDPOINT", endpoint_id)
        key = canonical.canonical_key_for_api_endpoint(endpoint["method"], endpoint["url"])
        if key is not None:
            groups.setdefault(key, []).append(endpoint_id)
    return groups


def _group_hosts(graph: "EngagementGraph") -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for host_id in _active_ids(graph, "HOST"):
        key = canonical.canonical_key_for_host(host_id)
        if key is not None:
            groups.setdefault(key, []).append(host_id)
    return groups


def _group_mobile_apps(graph: "EngagementGraph") -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for app_id in _active_ids(graph, "MOBILE_APP"):
        key = canonical.canonical_key_for_mobile_app(app_id)
        if key is not None:
            groups.setdefault(key, []).append(app_id)
    return groups


def _single_vulnerable_asset(graph: "EngagementGraph", finding_id: str) -> str | None:
    """`vulnerable_to`'s source is the affected asset. Only unambiguous
    when exactly one asset points at this finding — more than one, or
    zero, and there is no single "affected asset" to key on, so no key
    (guardrail 6: conservative bias)."""
    result = graph.execute("MATCH (a)-[:vulnerable_to]->(f:FINDING {id: $id}) RETURN a.id", {"id": finding_id})
    asset_ids = []
    while result.has_next():
        asset_ids.append(result.get_next()[0])
    return asset_ids[0] if len(asset_ids) == 1 else None


def _group_findings(graph: "EngagementGraph") -> dict[str, list[str]]:
    """FINDING's schema has no `location_sig` column and no ingester in
    this codebase populates one yet (see `canonical.canonical_key_for_finding`'s
    docstring) — `location_sig` is always `None` here, so this grouping
    pass is currently always empty in practice. Kept wired in (rather than
    omitted) so a future ingester that adds real location data gets
    correct FINDING dedup without a second brief touching this module."""
    groups: dict[str, list[str]] = {}
    for finding_id in _active_ids(graph, "FINDING"):
        finding = graph.get_node("FINDING", finding_id)
        affected_asset_id = _single_vulnerable_asset(graph, finding_id)
        key = canonical.canonical_key_for_finding(finding.get("title"), affected_asset_id, None)
        if key is not None:
            groups.setdefault(key, []).append(finding_id)
    return groups


def run_reconciliation_pass(
    graph: "EngagementGraph", engagement_dir: str, *, pass_name: str = _DEFAULT_PASS_NAME
) -> MergeReport:
    records = []
    groupings = (
        ("SECRET", _group_secrets(graph, engagement_dir)),
        ("API_ENDPOINT", _group_api_endpoints(graph)),
        ("HOST", _group_hosts(graph)),
        ("MOBILE_APP", _group_mobile_apps(graph)),
        ("FINDING", _group_findings(graph)),
    )
    for node_type, groups in groupings:
        for canonical_key, member_ids in groups.items():
            record = merge_group(graph, node_type, member_ids, canonical_key, pass_name)
            if record is not None:
                records.append(record)
    return MergeReport(records)
