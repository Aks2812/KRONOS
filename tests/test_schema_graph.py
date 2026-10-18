import kuzu
import pytest

from kronos.graph import EngagementGraph
from kronos.schema import init_db

ALL_NODE_TABLES = [
    "ENGAGEMENT", "HOST", "SERVICE", "WEB_ENDPOINT", "PARAMETER", "API_ENDPOINT",
    "MOBILE_APP", "MOBILE_COMPONENT", "SECRET", "IDENTITY", "CLOUD_RESOURCE",
    "TECHNOLOGY", "FINDING", "EVIDENCE",
]


def test_init_db_creates_all_node_tables(tmp_path):
    db = init_db(tmp_path / "e.kz")
    conn = kuzu.Connection(db)
    for t in ALL_NODE_TABLES:
        r = conn.execute(f"MATCH (n:{t}) RETURN count(n)")
        assert r.has_next()


def test_init_db_is_idempotent(tmp_path):
    p = tmp_path / "e.kz"
    init_db(p)
    init_db(p)  # must not raise


def test_upsert_node_merges_not_duplicates(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_factory(), pub)
    g.upsert_node("HOST", "host:10.0.0.1", {"created_at": "2026-01-01T00:00:00Z"})
    g.upsert_node("HOST", "host:10.0.0.1", {"created_at": "2026-01-01T00:00:00Z"})
    r = g.execute("MATCH (n:HOST) RETURN count(n)")
    assert r.get_next()[0] == 1


def test_upsert_node_stamps_in_scope_via_scope_guard(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_factory(), pub)  # in_scope=["*.acme.example.com"]
    # SPEC_BRIEF10.4 §1.4: corrected to API_ENDPOINT's evidenced id
    # shape, a full URL (§0.2) -- this test's subject (upsert_node's
    # in-scope stamping) is unchanged; only the node id's shape is.
    # `api.evil.com` stays a bare host, deliberately: it is the
    # out-of-scope control and was never broken by this correction (a
    # bare-host API_ENDPOINT id already failed the url-shape family
    # filter before and after this brief).
    g.upsert_node("API_ENDPOINT", "https://api.acme.example.com", {})
    g.upsert_node("API_ENDPOINT", "api.evil.com", {})
    assert g.get_node("API_ENDPOINT", "https://api.acme.example.com")["in_scope"] is True
    assert g.get_node("API_ENDPOINT", "api.evil.com")["in_scope"] is False


def test_mobile_component_exported_flag_round_trips(tmp_path, manifest_factory, signing_keypair):
    """Brief #2 schema extension: MOBILE_COMPONENT.exported is a plain
    descriptive attribute (like component_type/name), caller-settable via
    props, defaulting to false when omitted."""
    _, pub = signing_keypair
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_factory(), pub)
    g.upsert_node("MOBILE_APP", "com.acme.app", {})
    g.upsert_node(
        "MOBILE_COMPONENT", "com.acme.app/.MainActivity",
        {"component_type": "activity", "name": "MainActivity", "exported": True},
    )
    g.upsert_node(
        "MOBILE_COMPONENT", "com.acme.app/.InternalService",
        {"component_type": "service", "name": "InternalService", "exported": False},
    )
    g.upsert_node(
        "MOBILE_COMPONENT", "com.acme.app/.NoFlagGiven",
        {"component_type": "receiver", "name": "NoFlagGiven"},
    )
    assert g.get_node("MOBILE_COMPONENT", "com.acme.app/.MainActivity")["exported"] is True
    assert g.get_node("MOBILE_COMPONENT", "com.acme.app/.InternalService")["exported"] is False
    assert g.get_node("MOBILE_COMPONENT", "com.acme.app/.NoFlagGiven")["exported"] is False


def test_upsert_edge_merges_not_duplicates(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_factory(), pub)
    g.upsert_node("MOBILE_APP", "com.acme.app", {})
    g.upsert_node("SECRET", "secret:abc", {}, scope_key="com.acme.app")
    g.upsert_edge("leaks", "com.acme.app", "MOBILE_APP", "secret:abc", "SECRET")
    g.upsert_edge("leaks", "com.acme.app", "MOBILE_APP", "secret:abc", "SECRET")
    r = g.execute("MATCH ()-[e:leaks]->() RETURN count(e)")
    assert r.get_next()[0] == 1


# --- Final-review regression tests (both review passes confirmed these) ---


def test_upsert_node_cannot_override_in_scope_via_props(tmp_path, manifest_factory, signing_keypair):
    """Final review Critical #1: props={"in_scope": True} on an
    out-of-scope id must NOT make the node in-scope. scope_guard is
    SPEC.md's only scope mechanism; upsert_node must not let a caller's
    dict override its verdict."""
    _, pub = signing_keypair
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_factory(), pub)
    with pytest.raises(ValueError):
        g.upsert_node("API_ENDPOINT", "api.evil.com", {"in_scope": True})


def test_upsert_node_cannot_set_confidence_via_props(tmp_path, manifest_factory, signing_keypair):
    """Final review Critical #1: confidence must never be caller-settable,
    even at creation — only lifecycle.derive_confidence may produce it."""
    _, pub = signing_keypair
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_factory(), pub)
    with pytest.raises(ValueError):
        g.upsert_node("FINDING", "f1", {"title": "t", "severity": "high", "status": "hypothesis", "confidence": 10})


def test_upsert_node_rejects_unknown_prop_keys(tmp_path, manifest_factory, signing_keypair):
    """Final review Critical #2: an unrecognized props key must never
    reach the Cypher text at all (closes the injection vector in the key
    position, which _literal's value-escaping does not cover)."""
    _, pub = signing_keypair
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_factory(), pub)
    with pytest.raises(ValueError):
        g.upsert_node("HOST", "h1", {"confidence = 99, n.in_scope": True})


def test_upsert_node_cannot_change_status_after_creation(tmp_path, manifest_factory, signing_keypair):
    """Final review Important: re-ingesting a SECRET must not reset its
    lifecycle-advanced status/confidence back down. status is settable
    via props only at creation; a later upsert_node call on the same id
    must leave status/confidence untouched (only lifecycle.py may change
    them after creation)."""
    from kronos.lifecycle import advance_secret_status

    _, pub = signing_keypair
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_factory(), pub)
    g.upsert_node("SECRET", "s1", {"value_ref": "x", "kind": "api_key", "status": "extracted"})
    advance_secret_status(g, "s1", "validated")
    assert g.get_node("SECRET", "s1")["status"] == "validated"

    # Re-ingest the exact same raw upsert (simulating a re-run of ingest()).
    g.upsert_node("SECRET", "s1", {"value_ref": "x", "kind": "api_key", "status": "extracted"})
    node = g.get_node("SECRET", "s1")
    assert node["status"] == "validated"
    assert node["confidence"] == 7
