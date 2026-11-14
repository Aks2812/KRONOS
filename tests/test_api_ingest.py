"""SPEC_BRIEF R8 §5: standalone API-inventory ingestion source."""

from __future__ import annotations

import json

import pytest

from kronos.graph import EngagementGraph
from kronos.ingest import NodeUpsert
from kronos.ingest.api.parser import ingest_api_inventory, ingest_api_inventory_plan
from kronos.ingest.contract import IngestionSource, IngestPlan, apply_plan
from kronos.schema import NODE_PROPS_ALWAYS

U1 = "https://api.example.com/v1/users"
U2 = "https://api.example.com/v1/orders"


@pytest.fixture
def g(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    manifest = manifest_factory(scope={"in_scope": ["https://*"], "excluded": []})
    return EngagementGraph.init_engagement(tmp_path / "e.kz", manifest, pub)


def _inv(*endpoints):
    return json.dumps({"endpoints": list(endpoints)})


def test_well_formed_inventory(g):
    ups = ingest_api_inventory(_inv({"url": U1, "method": "GET"}, {"url": U2, "method": "POST"}), g)
    assert all(isinstance(u, NodeUpsert) for u in ups)
    assert {(u.type, u.id, u.props["method"]) for u in ups} == {
        ("API_ENDPOINT", U1, "GET"),
        ("API_ENDPOINT", U2, "POST"),
    }
    for n in ups:
        assert set(n.props) == NODE_PROPS_ALWAYS["API_ENDPOINT"]
        assert "in_scope" not in n.props
        assert n.props["url"] == n.id
        assert n.props["source"] == "api-inventory"
        assert n.scope_key == n.id


def test_unparseable_json_declines(g):
    plan = ingest_api_inventory_plan("{not json", g)
    assert plan.upserts == ()
    assert [d.reason for d in plan.report.declined] == ["unparseable_api_inventory"]
    assert ingest_api_inventory("{not json", g) == []


@pytest.mark.parametrize("doc", ["[1, 2]", '"x"', "3", json.dumps({"endpoints": {"a": 1}}), json.dumps({"endpoints": "x"})])
def test_non_object_or_non_list_endpoints_declines(g, doc):
    plan = ingest_api_inventory_plan(doc, g)
    assert plan.upserts == ()
    assert [d.reason for d in plan.report.declined] == ["unparseable_api_inventory"]


def test_absent_endpoints_default_empty(g):
    plan = ingest_api_inventory_plan("{}", g)
    assert plan.upserts == ()
    assert plan.report.declined == ()


def test_invalid_siblings_declined_valid_still_emit(g):
    inv = _inv(
        {"url": U1, "method": "GET"},
        {"method": "GET"},
        {"url": "https://api.example.com/v1/a"},
        {"url": "https://api.example.com/v1/b", "method": "TRACE"},
        {"url": "", "method": "GET"},
    )
    plan = ingest_api_inventory_plan(inv, g)
    assert {u.id for u in plan.upserts} == {U1}
    assert sorted(d.reason for d in plan.report.declined) == [
        "missing_endpoint_url",
        "missing_endpoint_url",
        "missing_or_invalid_method",
        "missing_or_invalid_method",
    ]


def test_lowercase_method_normalised(g):
    ups = ingest_api_inventory(_inv({"url": U1, "method": "get"}, {"url": U2, "method": "Patch"}), g)
    assert {u.id: u.props["method"] for u in ups} == {U1: "GET", U2: "PATCH"}


def test_plan_face_conforms_and_counts_match(g):
    assert isinstance(ingest_api_inventory_plan, IngestionSource)
    inv = _inv({"url": U1, "method": "GET"}, {"url": U2})
    plan = ingest_api_inventory_plan(inv, g)
    assert isinstance(plan, IngestPlan)
    assert plan.report.source.name == "api-inventory"
    assert plan.report.source.version == "1"
    assert plan.report.node_counts == {"API_ENDPOINT": 1}
    assert plan.report.edge_counts == {}
    assert len(plan.report.declined) == 1
    assert tuple(ingest_api_inventory(inv, g)) == plan.upserts


def test_plan_applies_to_graph(g):
    apply_plan(g, ingest_api_inventory_plan(_inv({"url": U1, "method": "GET"}), g))
    res = g.execute("MATCH (a:API_ENDPOINT {id: $i}) RETURN a.method", {"i": U1})
    assert res.get_next()[0] == "GET"


def test_declined_items_never_contain_raw_input(g):
    secret = "SECRET-TOKEN-abc123"
    docs = [
        "{" + secret,
        json.dumps({"endpoints": secret}),
        _inv({"url": secret}, {"method": secret}, {"url": secret, "method": secret}),
    ]
    for d in docs:
        plan = ingest_api_inventory_plan(d, g)
        assert plan.report.declined
        for item in plan.report.declined:
            assert secret not in item.reason
            assert secret not in item.detail
