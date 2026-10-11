import kuzu

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
    g.upsert_node("API_ENDPOINT", "api.acme.example.com", {})
    g.upsert_node("API_ENDPOINT", "api.evil.com", {})
    assert g.get_node("API_ENDPOINT", "api.acme.example.com")["in_scope"] is True
    assert g.get_node("API_ENDPOINT", "api.evil.com")["in_scope"] is False


def test_upsert_edge_merges_not_duplicates(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_factory(), pub)
    g.upsert_node("MOBILE_APP", "com.acme.app", {})
    g.upsert_node("SECRET", "secret:abc", {}, scope_key="com.acme.app")
    g.upsert_edge("leaks", "com.acme.app", "MOBILE_APP", "secret:abc", "SECRET")
    g.upsert_edge("leaks", "com.acme.app", "MOBILE_APP", "secret:abc", "SECRET")
    r = g.execute("MATCH ()-[e:leaks]->() RETURN count(e)")
    assert r.get_next()[0] == 1
