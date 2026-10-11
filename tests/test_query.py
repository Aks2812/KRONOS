from kronos.lifecycle import advance_finding_status
from kronos.query import find_paths, list_findings, list_secrets, query_graph


def test_query_graph_filters_by_type_and_prop(engagement_graph):
    g = engagement_graph
    g.upsert_node("HOST", "h1", {})
    g.upsert_node("API_ENDPOINT", "api.acme.example.com", {})
    rows = query_graph(g, node_type="HOST")
    assert {r["id"] for r in rows} == {"h1"}


def test_list_findings_by_status(engagement_graph):
    g = engagement_graph
    g.upsert_node("FINDING", "f1", {"title": "a", "severity": "low", "status": "hypothesis"})
    g.upsert_node("FINDING", "f2", {"title": "b", "severity": "high", "status": "hypothesis"})
    advance_finding_status(g, "f2", "reachable")
    assert {r["id"] for r in list_findings(g, status="hypothesis")} == {"f1"}
    assert {r["id"] for r in list_findings(g, status="reachable")} == {"f2"}


def test_list_secrets_by_status(engagement_graph):
    g = engagement_graph
    g.upsert_node("SECRET", "s1", {"value_ref": "x", "kind": "api_key", "status": "extracted"})
    assert {r["id"] for r in list_secrets(g, status="extracted")} == {"s1"}


def test_find_paths_returns_seeded_mobile_to_cloud_chain(manifest_factory, signing_keypair, tmp_path):
    from kronos.graph import EngagementGraph

    # Ruling (Task 6, see ledger): extend in_scope to cover the seeded
    # mobile bundle id, so every node in this chain is legitimately
    # in-scope under find_paths' endpoint-always-checked design.
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


def test_find_paths_only_in_scope_excludes_out_of_scope_hop(engagement_graph):
    g = engagement_graph
    g.upsert_node("MOBILE_APP", "com.acme.app", {})
    g.upsert_node("API_ENDPOINT", "api.evil.com", {})  # out of scope
    g.upsert_node("CLOUD_RESOURCE", "cr:x", {}, scope_key="api.evil.com")
    g.upsert_edge("references", "com.acme.app", "MOBILE_APP", "api.evil.com", "API_ENDPOINT")
    g.upsert_edge("chains_to", "api.evil.com", "API_ENDPOINT", "cr:x", "CLOUD_RESOURCE")
    assert find_paths(g, "MOBILE_APP", "CLOUD_RESOURCE", max_hops=5, only_in_scope=True) == []
