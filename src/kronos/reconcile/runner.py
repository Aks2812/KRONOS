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
from kronos.events import emit
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


def _group_api_endpoints(graph: "EngagementGraph", engagement_dir: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for endpoint_id in _active_ids(graph, "API_ENDPOINT"):
        endpoint = graph.get_node("API_ENDPOINT", endpoint_id)
        key = canonical.canonical_key_for_api_endpoint(endpoint["method"], endpoint["url"])
        if key is not None:
            groups.setdefault(key, []).append(endpoint_id)
        else:
            _emit_skipped(engagement_dir, "API_ENDPOINT", endpoint_id)
    return groups


def _group_web_endpoints(graph: "EngagementGraph", engagement_dir: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for endpoint_id in _active_ids(graph, "WEB_ENDPOINT"):
        endpoint = graph.get_node("WEB_ENDPOINT", endpoint_id)
        key = canonical.canonical_key_for_web_endpoint(endpoint["method"], endpoint["url"])
        if key is not None:
            groups.setdefault(key, []).append(endpoint_id)
        else:
            _emit_skipped(engagement_dir, "WEB_ENDPOINT", endpoint_id)
    return groups


def _group_hosts(graph: "EngagementGraph", engagement_dir: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for host_id in _active_ids(graph, "HOST"):
        key = canonical.canonical_key_for_host(host_id)
        if key is not None:
            groups.setdefault(key, []).append(host_id)
        else:
            _emit_skipped(engagement_dir, "HOST", host_id)
    return groups


def _single_host_for_service(graph: "EngagementGraph", service_id: str) -> str | None:
    """The HOST currently linked to this SERVICE via `hosts` — queried
    fresh each call, so once an earlier HOST merge has re-pointed edges
    onto the survivor (`merge.py`'s edge carry-over), this naturally
    returns the survivor's id, never a tombstoned loser's (SPEC_BRIEF9
    §5's ordering rule, enforced by call order in
    `run_reconciliation_pass`, not by a comment)."""
    result = graph.execute("MATCH (h:HOST)-[:hosts]->(s:SERVICE {id: $id}) RETURN h.id", {"id": service_id})
    host_ids = []
    while result.has_next():
        host_ids.append(result.get_next()[0])
    return host_ids[0] if len(host_ids) == 1 else None


def _group_services(graph: "EngagementGraph", engagement_dir: str) -> dict[str, list[str]]:
    """Must run strictly after `_group_hosts`'s merges have been applied
    (see `run_reconciliation_pass`). `host_key` here is the HOST's own
    RAW id, exactly as the `hosts` edge currently names it — not a
    freshly-recomputed `canonical_key_for_host`. That distinction is
    what makes the ordering rule load-bearing and testable rather than
    vacuous: `canonical_key_for_host` is a pure function of a host id's
    OWN text, so two genuine HOST duplicates always produce the same
    canonical key regardless of merge order — using it here would make
    §5's ordering requirement untestable by construction. The raw id,
    by contrast, only converges to one shared value across two
    SERVICE-duplicate's host edges once the HOST merge has actually run
    and re-pointed those edges onto the survivor (`merge.py`'s edge
    carry-over) — see `tests/test_reconcile.py`'s ordering test, which
    fails under the reverse order for exactly this reason."""
    groups: dict[str, list[str]] = {}
    for service_id in _active_ids(graph, "SERVICE"):
        service = graph.get_node("SERVICE", service_id)
        host_id = _single_host_for_service(graph, service_id)
        key = canonical.canonical_key_for_service(host_id, service["port"], service["protocol"])
        if key is not None:
            groups.setdefault(key, []).append(service_id)
        else:
            _emit_skipped(engagement_dir, "SERVICE", service_id)
    return groups


def _single_parent_endpoint(graph: "EngagementGraph", parameter_id: str) -> tuple[str, str] | None:
    """The one endpoint (WEB_ENDPOINT or API_ENDPOINT — `has_param`
    spans both per schema.EDGE_PAIRS) currently linked to this PARAMETER
    via `has_param`. Two separate typed queries rather than one
    multi-pattern match (same style as `_single_vulnerable_asset`),
    since a PARAMETER's id is only unique within its own node table, not
    across both possible parent types."""
    matches: list[tuple[str, str]] = []
    for parent_type in ("WEB_ENDPOINT", "API_ENDPOINT"):
        result = graph.execute(
            f"MATCH (e:{parent_type})-[:has_param]->(p:PARAMETER {{id: $id}}) RETURN e.id",
            {"id": parameter_id},
        )
        while result.has_next():
            matches.append((parent_type, result.get_next()[0]))
    return matches[0] if len(matches) == 1 else None


def _group_parameters(graph: "EngagementGraph", engagement_dir: str) -> dict[str, list[str]]:
    """Must run strictly after `_group_web_endpoints` and
    `_group_api_endpoints`'s merges (see `run_reconciliation_pass`) —
    `parent_key` here is the parent endpoint's own RAW id (whichever
    `WEB_ENDPOINT`/`API_ENDPOINT` the `has_param` edge currently names),
    not a freshly-recomputed `canonical_key_for_web_endpoint`/
    `canonical_key_for_api_endpoint`. Same reasoning as
    `_group_services`: those functions are pure, order-independent
    functions of an endpoint's own (method, url) — two genuine endpoint
    duplicates always produce the same canonical key regardless of
    merge order, which would make §5's ordering rule untestable.
    The raw id only converges across two PARAMETER duplicates' parent
    edges once the endpoint merge has actually re-pointed them onto the
    survivor."""
    groups: dict[str, list[str]] = {}
    for parameter_id in _active_ids(graph, "PARAMETER"):
        parameter = graph.get_node("PARAMETER", parameter_id)
        parent = _single_parent_endpoint(graph, parameter_id)
        parent_key = parent[1] if parent is not None else None
        key = canonical.canonical_key_for_parameter(parameter["name"], parameter["param_type"], parent_key)
        if key is not None:
            groups.setdefault(key, []).append(parameter_id)
        else:
            _emit_skipped(engagement_dir, "PARAMETER", parameter_id)
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


def _emit_skipped(engagement_dir: str, node_type: str, node_id: str) -> None:
    emit(engagement_dir, "reconcile_skipped_uncertain_key", node_type=node_type, node_id=node_id)


def _merge_type(
    graph: "EngagementGraph",
    engagement_dir: str,
    node_type: str,
    groups: dict[str, list[str]],
    pass_name: str,
    records: list,
) -> None:
    for canonical_key, member_ids in groups.items():
        record = merge_group(graph, node_type, member_ids, canonical_key, pass_name)
        if record is not None:
            records.append(record)
            emit(
                engagement_dir,
                "reconcile_merged",
                node_type=record.node_type,
                survivor_id=record.survivor_id,
                loser_ids=list(record.merged_ids),
            )


def run_reconciliation_pass(
    graph: "EngagementGraph", engagement_dir: str, *, pass_name: str = _DEFAULT_PASS_NAME
) -> MergeReport:
    """SPEC_BRIEF9 §5's ordering rule, enforced by CALL ORDER (not a
    comment): each type's group-then-merge step runs to completion
    before the next grouping function is even called, so `HOST` is
    fully merged before `_group_services` queries the graph, and
    `WEB_ENDPOINT`/`API_ENDPOINT` are fully merged before
    `_group_parameters` does. Grouping a child type eagerly alongside
    its parent (the way a single eager tuple of pre-computed groupings
    would) would let a child's compound key resolve against a
    soon-to-be-tombstoned loser — exactly the class of defect Brief #4
    already caught once (`merged_into`-inertness)."""
    records: list = []

    _merge_type(graph, engagement_dir, "SECRET", _group_secrets(graph, engagement_dir), pass_name, records)
    _merge_type(graph, engagement_dir, "WEB_ENDPOINT", _group_web_endpoints(graph, engagement_dir), pass_name, records)
    _merge_type(graph, engagement_dir, "API_ENDPOINT", _group_api_endpoints(graph, engagement_dir), pass_name, records)
    _merge_type(graph, engagement_dir, "HOST", _group_hosts(graph, engagement_dir), pass_name, records)
    # SERVICE after HOST (§5): _group_services queries each SERVICE's
    # current `hosts` edge, which the HOST merge above has already
    # re-pointed onto the survivor.
    _merge_type(graph, engagement_dir, "SERVICE", _group_services(graph, engagement_dir), pass_name, records)
    _merge_type(graph, engagement_dir, "MOBILE_APP", _group_mobile_apps(graph), pass_name, records)
    # PARAMETER after WEB_ENDPOINT/API_ENDPOINT (§5): same reasoning,
    # one level down the dependency chain.
    _merge_type(graph, engagement_dir, "PARAMETER", _group_parameters(graph, engagement_dir), pass_name, records)
    _merge_type(graph, engagement_dir, "FINDING", _group_findings(graph), pass_name, records)

    return MergeReport(records)
