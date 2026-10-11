"""The 5 spec-named invariant tests (Brief #1 Deliverables #4).

These are safety invariants, not coverage theater: each one pins down a
hard rule from SPEC.md's VALIDATION LIFECYCLE / SCOPE GUARD sections that
must be enforced in code, not just documented. They are added task by
task, as each task's work makes the behavior they pin down possible.
"""

from datetime import datetime, timedelta, timezone

import pytest

from kronos.graph import EngagementGraph
from kronos.ingest import apply_upserts, ingest_reference_mobile_secret
from kronos.lifecycle import LifecycleError, advance_finding_status, advance_secret_status, can_anchor_finding, derive_confidence
from kronos.manifest import ManifestError, load_and_verify
from kronos.query import find_paths


def test_invariant_expired_or_unsigned_manifest_rejected(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    now = datetime.now(timezone.utc)
    expired = manifest_factory(engagement={
        "window_start": (now - timedelta(days=10)).isoformat(),
        "window_end": (now - timedelta(days=1)).isoformat(),
    })
    with pytest.raises(ManifestError):
        load_and_verify(expired, pub)

    tampered = manifest_factory().replace("Acme Corp", "Evil Corp")
    with pytest.raises(ManifestError):
        load_and_verify(tampered, pub)


def test_invariant_no_evidence_finding_cannot_be_reported(engagement_graph):
    g = engagement_graph
    g.upsert_node("FINDING", "f1", {"title": "t", "severity": "high", "status": "hypothesis"})
    advance_finding_status(g, "f1", "reachable")
    advance_finding_status(g, "f1", "exploited")
    with pytest.raises(LifecycleError):
        advance_finding_status(g, "f1", "reported")


def test_invariant_out_of_scope_secret_cannot_anchor_finding(engagement_graph):
    g = engagement_graph
    g.upsert_node("API_ENDPOINT", "api.evil.com", {})
    g.upsert_node("SECRET", "s1", {"value_ref": "x", "kind": "api_key", "status": "extracted"})
    advance_secret_status(g, "s1", "validated")
    g.upsert_edge("authenticates_to", "s1", "SECRET", "api.evil.com", "API_ENDPOINT")
    advance_secret_status(g, "s1", "reachable")
    assert can_anchor_finding(g, "s1") is False


def test_invariant_confidence_cannot_exceed_status_cap():
    assert derive_confidence("finding", "hypothesis", False) < 7
    assert derive_confidence("secret", "extracted", True) < 7  # evidence doesn't rescue an unvalidated secret
    assert derive_confidence("secret", "validated", False) in (7, 8)


def test_invariant_find_paths_returns_seeded_mobile_to_cloud_chain(manifest_factory, signing_keypair, tmp_path):
    # Same seeding as test_find_paths_returns_seeded_mobile_to_cloud_chain
    # (tests/test_query.py) — see Task 6's ledger ruling on why the
    # manifest here extends in_scope to cover the seeded bundle id.
    _, pub = signing_keypair
    manifest_yaml = manifest_factory(scope={"in_scope": ["*.acme.example.com", "com.acme.*"]})
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_yaml, pub)

    g.upsert_node("MOBILE_APP", "com.acme.app", {"bundle_id": "com.acme.app"})
    g.upsert_node("SECRET", "s1", {"value_ref": "x", "kind": "api_key", "status": "extracted"}, scope_key="com.acme.app")
    g.upsert_node("API_ENDPOINT", "api.acme.example.com", {})
    g.upsert_node("CLOUD_RESOURCE", "cr:acme-bucket", {}, scope_key="api.acme.example.com")
    g.upsert_edge("leaks", "com.acme.app", "MOBILE_APP", "s1", "SECRET")
    g.upsert_edge("authenticates_to", "s1", "SECRET", "api.acme.example.com", "API_ENDPOINT")
    g.upsert_edge("chains_to", "api.acme.example.com", "API_ENDPOINT", "cr:acme-bucket", "CLOUD_RESOURCE")

    paths = find_paths(g, "MOBILE_APP", "CLOUD_RESOURCE", max_hops=5)
    assert len(paths) >= 1
    assert paths[0]["nodes"][0] == "com.acme.app"
    assert paths[0]["nodes"][-1] == "cr:acme-bucket"


def test_invariant_ingested_reference_example_produces_mobile_to_secret_chain(
    manifest_factory, signing_keypair, tmp_path
):
    # Ruling (Task 7, see ledger): the shared engagement_graph fixture's
    # default in_scope doesn't cover ingest_reference_mobile_secret()'s
    # default bundle id, so this test builds its own graph with scope
    # extended to include it.
    _, pub = signing_keypair
    manifest_yaml = manifest_factory(scope={"in_scope": ["*.acme.example.com", "com.kronos.*"]})
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_yaml, pub)

    apply_upserts(g, ingest_reference_mobile_secret())
    paths = find_paths(g, "MOBILE_APP", "SECRET", max_hops=2)
    assert len(paths) >= 1
