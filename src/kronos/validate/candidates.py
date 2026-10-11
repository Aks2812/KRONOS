"""Candidate-target discovery (SPEC_BRIEF3 "The validator takes (secret,
candidate_target) where candidate_target comes from the graph's existing
references/authenticates_to-candidate edges — it does NOT invent
targets.").

API_ENDPOINT candidates: whatever node(s) `leaks` this secret also
`references` — exactly the edges Brief #2's mobile ingester already
writes (and any future ingester writing the same edge labels). Done as
two plain queries joined in Python rather than one multi-pattern Cypher
MATCH, to avoid depending on cross-pattern variable-binding behavior
this codebase hasn't otherwise exercised.

CLOUD_RESOURCE candidates: every CLOUD_RESOURCE node currently in the
engagement. Deliberately not edge-filtered — there is no schema-legal
edge type connecting a mobile app/secret to a cloud resource before it's
proven live (`authenticates_to` is the validator's OWN output, not an
input), and trying every known cloud resource is exactly what reveals a
credential's real (possibly over-broad) privilege, e.g. CyberGym's
chain-3 credential working on two buckets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kronos.validate.types import CandidateTarget

if TYPE_CHECKING:  # pragma: no cover
    from kronos.graph import EngagementGraph


def _leaking_app_ids(graph: "EngagementGraph", secret_id: str) -> list[str]:
    result = graph.execute("MATCH (app)-[:leaks]->(s:SECRET {id: $id}) RETURN app.id", {"id": secret_id})
    app_ids = []
    while result.has_next():
        app_ids.append(result.get_next()[0])
    return app_ids


def _referenced_endpoints(graph: "EngagementGraph", app_id: str) -> list[tuple[str, bool]]:
    result = graph.execute(
        "MATCH (app {id: $id})-[:references]->(ep:API_ENDPOINT) RETURN ep.id, ep.in_scope", {"id": app_id}
    )
    endpoints = []
    while result.has_next():
        endpoints.append(tuple(result.get_next()))
    return endpoints


def _all_cloud_resources(graph: "EngagementGraph") -> list[tuple[str, bool]]:
    result = graph.execute("MATCH (c:CLOUD_RESOURCE) RETURN c.id, c.in_scope")
    resources = []
    while result.has_next():
        resources.append(tuple(result.get_next()))
    return resources


def find_candidate_targets_for_secret(graph: "EngagementGraph", secret_id: str) -> list[CandidateTarget]:
    candidates: list[CandidateTarget] = []
    seen_endpoint_ids: set[str] = set()

    for app_id in _leaking_app_ids(graph, secret_id):
        for endpoint_id, in_scope in _referenced_endpoints(graph, app_id):
            if endpoint_id in seen_endpoint_ids:
                continue
            seen_endpoint_ids.add(endpoint_id)
            candidates.append(CandidateTarget(type="API_ENDPOINT", id=endpoint_id, in_scope=in_scope))

    for resource_id, in_scope in _all_cloud_resources(graph):
        candidates.append(CandidateTarget(type="CLOUD_RESOURCE", id=resource_id, in_scope=in_scope))

    return candidates
