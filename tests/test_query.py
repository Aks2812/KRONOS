import socket
import subprocess

import pytest

from kronos.lifecycle import advance_finding_status
from kronos.query import find_paths, list_findings, list_secrets, query_graph, resolve_host


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
    # SPEC_BRIEF10.4 §1.4: corrected to API_ENDPOINT's evidenced id
    # shape, a full URL (§0.2) -- the test's subject (find_paths
    # traversal) is unchanged; only the node id's shape is.
    g.upsert_node("API_ENDPOINT", "https://api.acme.example.com", {})
    g.upsert_node("CLOUD_RESOURCE", "cr:acme-bucket", {}, scope_key="api.acme.example.com")
    g.upsert_edge("leaks", "com.acme.app", "MOBILE_APP", "s1", "SECRET")
    g.upsert_edge("authenticates_to", "s1", "SECRET", "https://api.acme.example.com", "API_ENDPOINT")
    g.upsert_edge("chains_to", "https://api.acme.example.com", "API_ENDPOINT", "cr:acme-bucket", "CLOUD_RESOURCE")

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


# ---- SPEC_BRIEF27 resolve_host (hermetic; expected values from brief prose) ----

B27_BASE = "31ca3b5"
B27_SECTION_3 = {
    "SPEC_BRIEF27.md",
    "src/kronos/query.py",
    "tests/test_query.py",
    "tests/test_dns_ingest.py",
}


@pytest.fixture
def rg(tmp_path, manifest_factory, signing_keypair):
    from kronos.graph import EngagementGraph

    _, pub = signing_keypair
    manifest = manifest_factory(
        scope={"in_scope": ["*.example.com", "1.2.3.4", "5.6.7.8"], "excluded": []}
    )
    return EngagementGraph.init_engagement(tmp_path / "r.kz", manifest, pub)


def _seed(g, *edges, hosts=()):
    for h in hosts:
        g.upsert_node("HOST", h, {})
    for a, b in edges:
        g.upsert_node("HOST", a, {})
        g.upsert_node("HOST", b, {})
        g.upsert_edge("resolves_to", a, "HOST", b, "HOST")


def test_B27_A_direct(rg):
    _seed(rg, ("host.example.com", "1.2.3.4"))
    assert resolve_host(rg, "host.example.com") == {
        "name": "host.example.com",
        "status": "resolved",
        "terminals": ["1.2.3.4"],
        "excluded_out_of_scope": False,
    }


def test_B27_B_normalization(rg):
    _seed(rg, ("host.example.com", "1.2.3.4"))
    r = resolve_host(rg, "Host.Example.com.")
    assert r["name"] == "host.example.com"
    assert r["status"] == "resolved" and r["terminals"] == ["1.2.3.4"]


def test_B27_C_cname_chain(rg):
    _seed(rg, ("a.example.com", "b.example.com"), ("b.example.com", "1.2.3.4"))
    r = resolve_host(rg, "a.example.com")
    assert r["status"] == "resolved" and r["terminals"] == ["1.2.3.4"]


def test_B27_D_many_ips_deterministic(rg):
    _seed(rg, ("host.example.com", "5.6.7.8"), ("host.example.com", "1.2.3.4"))
    r = resolve_host(rg, "host.example.com")
    assert r["status"] == "resolved" and r["terminals"] == ["1.2.3.4", "5.6.7.8"]
    assert resolve_host(rg, "host.example.com") == r


def test_B27_E_dedup(rg):
    _seed(
        rg,
        ("a.example.com", "b.example.com"),
        ("a.example.com", "c.example.com"),
        ("b.example.com", "1.2.3.4"),
        ("c.example.com", "1.2.3.4"),
    )
    assert resolve_host(rg, "a.example.com")["terminals"] == ["1.2.3.4"]


def test_B27_E_diamond_is_not_a_cycle(rg):
    _seed(
        rg,
        ("a.example.com", "b.example.com"),
        ("a.example.com", "c.example.com"),
        ("b.example.com", "d.example.com"),
        ("c.example.com", "d.example.com"),
        ("d.example.com", "1.2.3.4"),
    )
    r = resolve_host(rg, "a.example.com")
    assert r["status"] == "resolved" and r["terminals"] == ["1.2.3.4"]


def test_B27_F_unknown_host(rg):
    r = resolve_host(rg, "nope.example.com")
    assert r["status"] == "unknown_host" and r["terminals"] == []


def test_B27_G_unresolved(rg):
    _seed(rg, hosts=["lonely.example.com", "1.2.3.4"])
    r = resolve_host(rg, "lonely.example.com")
    assert r["status"] == "unresolved" and r["terminals"] == []
    r = resolve_host(rg, "1.2.3.4")
    assert r["status"] == "unresolved" and r["terminals"] == []


def test_B27_H_out_of_scope_terminal(rg):
    _seed(rg, ("host.example.com", "1.2.3.4"), ("host.example.com", "9.9.9.9"))
    r = resolve_host(rg, "host.example.com")
    assert r["terminals"] == ["1.2.3.4"] and r["excluded_out_of_scope"] is True
    r = resolve_host(rg, "host.example.com", only_in_scope=False)
    assert r["terminals"] == ["1.2.3.4", "9.9.9.9"] and r["excluded_out_of_scope"] is False


def test_B27_I_out_of_scope_start(rg):
    _seed(rg, ("host.other.org", "1.2.3.4"))
    r = resolve_host(rg, "host.other.org")
    assert r["status"] == "unresolved" and r["terminals"] == []
    assert r["excluded_out_of_scope"] is True


def test_B27_J2_cycle(rg):
    _seed(rg, ("a.example.com", "b.example.com"), ("b.example.com", "a.example.com"))
    r = resolve_host(rg, "a.example.com")
    assert r["status"] == "cycle_detected" and r["terminals"] == []
    _seed(rg, ("a.example.com", "1.2.3.4"))
    r = resolve_host(rg, "a.example.com")
    assert r["status"] == "cycle_detected" and r["terminals"] == ["1.2.3.4"]


def _counts(g):
    n = g.execute("MATCH (n) RETURN count(n)").get_next()[0]
    e = g.execute("MATCH ()-[r]->() RETURN count(r)").get_next()[0]
    return n, e, None


def test_B27_R_read_only(rg):
    _seed(rg, ("host.example.com", "1.2.3.4"), ("host.example.com", "9.9.9.9"))

    def snapshot():
        res = rg.execute("MATCH (h:HOST) RETURN h.id, h.in_scope")
        hosts = []
        while res.has_next():
            hosts.append(tuple(res.get_next()))
        n, e, _ = _counts(rg)
        return n, e, sorted(hosts)

    before = snapshot()
    resolve_host(rg, "host.example.com")
    resolve_host(rg, "host.example.com", only_in_scope=False)
    resolve_host(rg, "nope.example.com")
    assert snapshot() == before
    assert query_graph(rg, "FINDING") == [] and query_graph(rg, "SECRET") == []


def test_B27_N_no_network(rg, monkeypatch):
    _seed(rg, ("host.example.com", "1.2.3.4"))

    def boom(*a, **k):
        raise AssertionError("socket used")

    monkeypatch.setattr(socket, "socket", boom)
    assert resolve_host(rg, "host.example.com")["status"] == "resolved"


def test_B27_J_scope_audit():
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{B27_BASE}..HEAD"], capture_output=True, text=True, check=True
    ).stdout.split()
    assert set(out) <= B27_SECTION_3, set(out) - B27_SECTION_3


def test_B27_J3_multipath_cycle(rg):
    # brief §8 J3 / D4: cycle closes only on a later branch (a->b, a->c, c->b, b->c)
    _seed(
        rg,
        ("a.example.com", "b.example.com"),
        ("a.example.com", "c.example.com"),
        ("c.example.com", "b.example.com"),
        ("b.example.com", "c.example.com"),
    )
    assert resolve_host(rg, "a.example.com")["status"] == "cycle_detected"
