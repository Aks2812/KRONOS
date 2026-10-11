import pytest

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


def test_find_paths_only_in_scope_excludes_out_of_scope_hop(manifest_factory, signing_keypair, tmp_path):
    """Final review Important #2: the original version of this test had
    BOTH endpoints out of scope under the default manifest, so it
    passed because of the endpoint-always-checked rule, not because the
    out-of-scope INTERMEDIATE hop was filtered — it would still have
    passed with that filter deleted. Fixed: both endpoints (MOBILE_APP,
    CLOUD_RESOURCE) are legitimately in scope here; only the
    intermediate API_ENDPOINT is out of scope, so only_in_scope is what
    actually has to do the blocking."""
    from kronos.graph import EngagementGraph

    _, pub = signing_keypair
    manifest_yaml = manifest_factory(scope={"in_scope": ["*.acme.example.com", "com.acme.*"]})
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_yaml, pub)

    g.upsert_node("MOBILE_APP", "com.acme.app", {})
    g.upsert_node("API_ENDPOINT", "api.evil.com", {})  # out of scope (intermediate hop only)
    g.upsert_node("CLOUD_RESOURCE", "cr:acme-bucket", {}, scope_key="api.acme.example.com")
    g.upsert_edge("references", "com.acme.app", "MOBILE_APP", "api.evil.com", "API_ENDPOINT")
    g.upsert_edge("chains_to", "api.evil.com", "API_ENDPOINT", "cr:acme-bucket", "CLOUD_RESOURCE")

    assert find_paths(g, "MOBILE_APP", "CLOUD_RESOURCE", max_hops=5, only_in_scope=True) == []
    out_of_scope_ok = find_paths(g, "MOBILE_APP", "CLOUD_RESOURCE", max_hops=5, only_in_scope=False)
    assert len(out_of_scope_ok) >= 1


def test_find_paths_rejects_evidence_or_engagement_endpoint(engagement_graph):
    """Final review Important #9: EVIDENCE/ENGAGEMENT have no in_scope
    column, so find_paths' endpoint WHERE clause used to crash with a
    raw Kuzu binder RuntimeError ("Cannot find property in_scope")
    instead of a clear, catchable error."""
    g = engagement_graph
    with pytest.raises(ValueError):
        find_paths(g, "FINDING", "EVIDENCE")
    with pytest.raises(ValueError):
        find_paths(g, "ENGAGEMENT", "HOST")


def test_find_paths_rejects_unknown_type(engagement_graph):
    with pytest.raises(ValueError):
        find_paths(engagement_graph, "NOT_A_REAL_TYPE", "HOST")


def test_query_graph_rejects_unknown_node_type(engagement_graph):
    with pytest.raises(ValueError):
        query_graph(engagement_graph, node_type="NOT_A_REAL_TYPE")


def test_query_graph_rejects_unknown_filter_key(engagement_graph):
    """Final review Important #6: query.py pasted filter keys into Cypher
    text unchecked; harmless today since only internal constants reach
    it, but SPEC.md says this is exactly the surface a future agent will
    drive. Reject unknown keys the same way upsert_node does."""
    g = engagement_graph
    g.upsert_node("HOST", "h1", {})
    with pytest.raises(ValueError):
        query_graph(g, node_type="HOST", filters={"id = '' OR 1=1 //": "x"})
