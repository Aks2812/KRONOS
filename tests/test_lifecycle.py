import pytest

from kronos.lifecycle import (
    LifecycleError,
    advance_finding_status,
    advance_secret_status,
    can_anchor_finding,
    derive_confidence,
)


def test_secret_transition_extracted_to_validated_ok(engagement_graph):
    g = engagement_graph
    g.upsert_node("SECRET", "s1", {"value_ref": "sha256:aaa", "kind": "api_key", "status": "extracted"})
    advance_secret_status(g, "s1", "validated")
    assert g.get_node("SECRET", "s1")["status"] == "validated"


def test_secret_cannot_skip_validated(engagement_graph):
    g = engagement_graph
    g.upsert_node("SECRET", "s1", {"value_ref": "x", "kind": "api_key", "status": "extracted"})
    with pytest.raises(LifecycleError):
        advance_secret_status(g, "s1", "reachable")


def test_secret_cannot_leave_dead(engagement_graph):
    g = engagement_graph
    g.upsert_node("SECRET", "s1", {"value_ref": "x", "kind": "api_key", "status": "extracted"})
    advance_secret_status(g, "s1", "dead")
    with pytest.raises(LifecycleError):
        advance_secret_status(g, "s1", "validated")


def test_finding_reported_requires_exploited_and_evidence(engagement_graph):
    g = engagement_graph
    g.upsert_node("FINDING", "f1", {"title": "t", "severity": "high", "status": "hypothesis"})
    with pytest.raises(LifecycleError):
        advance_finding_status(g, "f1", "reported")  # wrong status
    advance_finding_status(g, "f1", "reachable")
    advance_finding_status(g, "f1", "exploited")
    with pytest.raises(LifecycleError):
        advance_finding_status(g, "f1", "reported")  # exploited but NO evidence yet


def test_finding_reported_terminal(engagement_graph):
    g = engagement_graph
    g.upsert_node("FINDING", "f1", {"title": "t", "severity": "high", "status": "hypothesis"})
    advance_finding_status(g, "f1", "reachable")
    advance_finding_status(g, "f1", "exploited")
    # simulate evidence directly via the edge (Task 5 wires attach_evidence; here we poke the graph)
    g.upsert_node("EVIDENCE", "ev1", {"sha256": "abc", "blob_path": "x", "kind": "screenshot"})
    g.upsert_edge("evidences", "ev1", "EVIDENCE", "f1", "FINDING")
    advance_finding_status(g, "f1", "reported")
    with pytest.raises(LifecycleError):
        advance_finding_status(g, "f1", "hypothesis")


def test_out_of_scope_secret_cannot_anchor_finding(engagement_graph):
    g = engagement_graph  # in_scope=["*.acme.example.com"]
    g.upsert_node("API_ENDPOINT", "api.evil.com", {})
    g.upsert_node("SECRET", "s1", {"value_ref": "x", "kind": "api_key", "status": "extracted"})
    advance_secret_status(g, "s1", "validated")
    g.upsert_edge("authenticates_to", "s1", "SECRET", "api.evil.com", "API_ENDPOINT")
    advance_secret_status(g, "s1", "reachable")
    assert can_anchor_finding(g, "s1") is False
    assert g.get_node("SECRET", "s1")["scope_note"] is not None  # recorded as a note


def test_confidence_cannot_exceed_status_cap(engagement_graph):
    g = engagement_graph
    g.upsert_node("FINDING", "f1", {"title": "t", "severity": "high", "status": "hypothesis"})
    assert g.get_node("FINDING", "f1")["confidence"] < 7
    advance_finding_status(g, "f1", "reachable")
    assert g.get_node("FINDING", "f1")["confidence"] < 9
    advance_finding_status(g, "f1", "exploited")
    assert g.get_node("FINDING", "f1")["confidence"] >= 9


def test_derive_confidence_pure_function_table():
    assert derive_confidence("finding", "hypothesis", False) < 7
    assert derive_confidence("secret", "validated", False) in (7, 8)
    assert derive_confidence("finding", "reachable", True) >= 9
    assert derive_confidence("finding", "exploited", True) == 10
    assert derive_confidence("secret", "dead", False) == 0
