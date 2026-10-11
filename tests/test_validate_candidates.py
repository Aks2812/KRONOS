"""SPEC_BRIEF3 "candidate_target comes from the graph's existing
references/authenticates_to-candidate edges — it does NOT invent
targets." API_ENDPOINT candidates: joined via the app/component that
both `leaks` the secret and `references` the endpoint (exactly the
edges Brief #2 already writes). CLOUD_RESOURCE candidates: every
CLOUD_RESOURCE node in the engagement — a credential's privilege is
what's being tested, not assumed in advance (this is what makes a
chain-3-style over-privilege provable at all).
"""

from __future__ import annotations

from kronos.graph import EngagementGraph
from kronos.validate.candidates import find_candidate_targets_for_secret


def _graph(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    manifest_text = manifest_factory(
        scope={"in_scope": ["com.kronos.*", "http://localhost:8091*"], "excluded": []}
    )
    return EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_text, pub)


def test_api_endpoint_candidates_come_from_shared_app_leaks_and_references(
    tmp_path, manifest_factory, signing_keypair
) -> None:
    graph = _graph(tmp_path, manifest_factory, signing_keypair)
    graph.upsert_node("MOBILE_APP", "com.kronos.lab", {"bundle_id": "com.kronos.lab", "platform": "android", "source": "static"})
    graph.upsert_node(
        "SECRET",
        "secret-1",
        {"value_ref": "sha256:abc", "kind": "api_key", "status": "extracted", "source": "static"},
        scope_key="com.kronos.lab",
    )
    graph.upsert_edge("leaks", "com.kronos.lab", "MOBILE_APP", "secret-1", "SECRET")
    graph.upsert_node("API_ENDPOINT", "http://localhost:8091", {"source": "static"})
    graph.upsert_edge("references", "com.kronos.lab", "MOBILE_APP", "http://localhost:8091", "API_ENDPOINT")
    # An endpoint referenced by a DIFFERENT app must not show up as a candidate.
    graph.upsert_node("MOBILE_APP", "com.other.app", {"bundle_id": "com.other.app", "platform": "android", "source": "static"})
    graph.upsert_node("API_ENDPOINT", "http://unrelated.example.com", {"source": "static"})
    graph.upsert_edge("references", "com.other.app", "MOBILE_APP", "http://unrelated.example.com", "API_ENDPOINT")

    candidates = find_candidate_targets_for_secret(graph, "secret-1")

    assert len(candidates) == 1
    assert candidates[0].type == "API_ENDPOINT"
    assert candidates[0].id == "http://localhost:8091"
    assert candidates[0].in_scope is True


def test_cloud_resource_candidates_are_every_cloud_resource_in_the_engagement(
    tmp_path, manifest_factory, signing_keypair
) -> None:
    graph = _graph(tmp_path, manifest_factory, signing_keypair)
    graph.upsert_node("MOBILE_APP", "com.kronos.lab", {"bundle_id": "com.kronos.lab", "platform": "android", "source": "static"})
    graph.upsert_node(
        "SECRET",
        "secret-2",
        {"value_ref": "sha256:def", "kind": "api_key", "status": "extracted", "source": "static"},
        scope_key="com.kronos.lab",
    )
    graph.upsert_edge("leaks", "com.kronos.lab", "MOBILE_APP", "secret-2", "SECRET")
    graph.upsert_node(
        "CLOUD_RESOURCE", "bucket-a", {"resource_type": "s3_bucket", "provider": "aws", "source": "enrichment"},
        scope_key="arn:aws:s3:::does-not-match-anything",
    )
    graph.upsert_node(
        "CLOUD_RESOURCE", "bucket-b", {"resource_type": "s3_bucket", "provider": "aws", "source": "enrichment"},
        scope_key="arn:aws:s3:::does-not-match-anything-else",
    )

    candidates = find_candidate_targets_for_secret(graph, "secret-2")

    cloud_candidates = [c for c in candidates if c.type == "CLOUD_RESOURCE"]
    assert {c.id for c in cloud_candidates} == {"bucket-a", "bucket-b"}
    assert all(c.in_scope is False for c in cloud_candidates)  # neither ARN matches in_scope globs


def test_secret_with_no_leaking_app_has_no_candidates(tmp_path, manifest_factory, signing_keypair) -> None:
    graph = _graph(tmp_path, manifest_factory, signing_keypair)
    graph.upsert_node(
        "SECRET",
        "secret-3",
        {"value_ref": "sha256:ghi", "kind": "api_key", "status": "extracted", "source": "static"},
        scope_key="nowhere",
    )

    candidates = find_candidate_targets_for_secret(graph, "secret-3")

    assert candidates == []
