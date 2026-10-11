import pytest

from kronos.ingest import (
    EdgeUpsert,
    NodeUpsert,
    apply_upserts,
    ingest,
    ingest_reference_mobile_secret,
)


def test_ingest_reference_mobile_secret_shape():
    ups = ingest_reference_mobile_secret()
    assert any(isinstance(u, NodeUpsert) and u.type == "MOBILE_APP" for u in ups)
    assert any(isinstance(u, NodeUpsert) and u.type == "SECRET" for u in ups)
    assert any(isinstance(u, EdgeUpsert) and u.label == "leaks" for u in ups)


def test_ingest_dispatches_reference_tool(engagement_graph):
    ups = ingest(raw_tool_output=None, tool_name="reference", engagement=engagement_graph)
    assert len(ups) >= 3


def test_ingest_unknown_tool_raises(engagement_graph):
    with pytest.raises(NotImplementedError):
        ingest(raw_tool_output={}, tool_name="nmap", engagement=engagement_graph)


def test_apply_upserts_writes_nodes_and_edges(engagement_graph):
    g = engagement_graph
    ups = ingest_reference_mobile_secret()
    apply_upserts(g, ups)
    r = g.execute("MATCH (a:MOBILE_APP)-[:leaks]->(s:SECRET) RETURN a.id, s.id")
    assert r.has_next()


def test_apply_upserts_is_idempotent_no_duplicates(engagement_graph):
    g = engagement_graph
    ups = ingest_reference_mobile_secret()
    apply_upserts(g, ups)
    apply_upserts(g, ups)  # re-run identical raw input
    r = g.execute("MATCH (a:MOBILE_APP)-[:leaks]->(s:SECRET) RETURN count(*)")
    assert r.get_next()[0] == 1
    r = g.execute("MATCH (a:MOBILE_APP) RETURN count(a)")
    assert r.get_next()[0] == 1
    r = g.execute("MATCH (s:SECRET) RETURN count(s)")
    assert r.get_next()[0] == 1


def test_edge_upsert_raises_on_ambiguous_shared_id(engagement_graph):
    """Final review Important #4: the same id can legitimately exist in
    two different node tables (e.g. a HOST and an API_ENDPOINT sharing a
    hostname) — _resolve_node_type must not silently pick whichever
    table happens first in ALL_NODE_TABLES order, since that can wire an
    edge to the wrong endpoint type entirely."""
    g = engagement_graph
    g.upsert_node("HOST", "shared.acme.example.com", {})
    g.upsert_node("API_ENDPOINT", "shared.acme.example.com", {})
    with pytest.raises(ValueError):
        apply_upserts(g, [EdgeUpsert("resolves_to", "shared.acme.example.com", "shared.acme.example.com")])
