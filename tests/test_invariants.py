"""The 5 spec-named invariant tests (Brief #1 Deliverables #4).

These are safety invariants, not coverage theater: each one pins down a
hard rule from SPEC.md's VALIDATION LIFECYCLE / SCOPE GUARD sections that
must be enforced in code, not just documented. They are added task by
task, as each task's work makes the behavior they pin down possible.
"""

from datetime import datetime, timedelta, timezone

import pytest

from kronos.lifecycle import LifecycleError, advance_finding_status, advance_secret_status, can_anchor_finding, derive_confidence
from kronos.manifest import ManifestError, load_and_verify


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
