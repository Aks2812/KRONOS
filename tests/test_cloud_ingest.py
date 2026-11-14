"""SPEC_BRIEF R7 §5: cloud-inventory ingestion source."""

from __future__ import annotations

import json

import pytest

from kronos.graph import EngagementGraph
from kronos.ingest import EdgeUpsert, NodeUpsert
from kronos.ingest.cloud.parser import ingest_cloud_inventory, ingest_cloud_inventory_plan
from kronos.ingest.contract import IngestionSource, IngestPlan, apply_plan
from kronos.schema import NODE_PROPS_ALWAYS

RES = "arn:aws:s3:::bucket/x"
USER = "arn:aws:iam::1:user/alice"


@pytest.fixture
def g(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    manifest = manifest_factory(scope={"in_scope": ["arn:*"], "excluded": []})
    return EngagementGraph.init_engagement(tmp_path / "e.kz", manifest, pub)


def _inv(**over):
    doc = {
        "provider": "aws",
        "resources": [{"id": RES, "resource_type": "s3_bucket"}],
        "identities": [{"id": USER, "name": "alice"}],
        "grants": [{"identity": USER, "resource": RES}],
    }
    doc.update(over)
    return json.dumps({k: v for k, v in doc.items() if v is not None})


def test_well_formed_inventory(g):
    ups = ingest_cloud_inventory(_inv(), g)
    nodes = [u for u in ups if isinstance(u, NodeUpsert)]
    edges = [u for u in ups if isinstance(u, EdgeUpsert)]
    assert {(n.type, n.id) for n in nodes} == {("CLOUD_RESOURCE", RES), ("IDENTITY", USER)}
    assert len(edges) == 1
    assert (edges[0].label, edges[0].from_id, edges[0].to_id) == ("grants", USER, RES)
    for n in nodes:
        assert set(n.props) == NODE_PROPS_ALWAYS[n.type]
        assert "in_scope" not in n.props
        assert n.props["provider"] == "aws"
        assert n.props["source"] == "cloud-inventory"
        assert n.scope_key == n.id
    by_type = {n.type: n for n in nodes}
    assert by_type["CLOUD_RESOURCE"].props["resource_type"] == "s3_bucket"
    assert by_type["IDENTITY"].props["name"] == "alice"


def test_unparseable_json_declines(g):
    plan = ingest_cloud_inventory_plan("{not json", g)
    assert plan.upserts == ()
    assert [d.reason for d in plan.report.declined] == ["unparseable_cloud_inventory"]
    assert ingest_cloud_inventory("{not json", g) == []


def test_non_object_top_level_declines(g):
    plan = ingest_cloud_inventory_plan("[1, 2]", g)
    assert plan.upserts == ()
    assert [d.reason for d in plan.report.declined] == ["unparseable_cloud_inventory"]


@pytest.mark.parametrize("provider", [None, "", "   "])
def test_missing_provider_declines_whole_document(g, provider):
    doc = json.loads(_inv())
    if provider is None:
        del doc["provider"]
    else:
        doc["provider"] = provider
    plan = ingest_cloud_inventory_plan(json.dumps(doc), g)
    assert plan.upserts == ()
    assert [d.reason for d in plan.report.declined] == ["missing_provider"]


def test_absent_sections_default_empty(g):
    plan = ingest_cloud_inventory_plan(json.dumps({"provider": "aws"}), g)
    assert plan.upserts == ()
    assert plan.report.declined == ()


def test_invalid_siblings_declined_valid_still_emit(g):
    inv = _inv(
        resources=[
            {"id": RES, "resource_type": "s3_bucket"},
            {"id": "arn:aws:s3:::bucket/y"},
            {"resource_type": "s3_bucket"},
        ],
        identities=[
            {"id": USER, "name": "alice"},
            {"id": "arn:aws:iam::1:user/bob"},
            {"name": "carol"},
        ],
        grants=[],
    )
    plan = ingest_cloud_inventory_plan(inv, g)
    assert {u.id for u in plan.upserts} == {RES, USER}
    assert sorted(d.reason for d in plan.report.declined) == [
        "missing_identity_id",
        "missing_identity_name",
        "missing_resource_id",
        "missing_resource_type",
    ]


def test_grant_dangling_endpoint_declines(g):
    inv = _inv(
        grants=[
            {"identity": USER, "resource": "arn:aws:s3:::bucket/ghost"},
            {"identity": "arn:aws:iam::1:user/ghost", "resource": RES},
        ]
    )
    plan = ingest_cloud_inventory_plan(inv, g)
    assert not [u for u in plan.upserts if isinstance(u, EdgeUpsert)]
    assert [d.reason for d in plan.report.declined] == ["grant_dangling_endpoint"] * 2


def test_grant_to_declined_node_is_dangling(g):
    inv = _inv(resources=[{"id": RES}])
    plan = ingest_cloud_inventory_plan(inv, g)
    assert not [u for u in plan.upserts if isinstance(u, EdgeUpsert)]
    assert "grant_dangling_endpoint" in [d.reason for d in plan.report.declined]


def test_plan_face_conforms_and_counts_match(g):
    assert isinstance(ingest_cloud_inventory_plan, IngestionSource)
    inv = _inv(resources=[{"id": RES, "resource_type": "s3_bucket"}, {"id": "arn:x"}])
    plan = ingest_cloud_inventory_plan(inv, g)
    assert isinstance(plan, IngestPlan)
    assert plan.report.source.name == "cloud-inventory"
    assert plan.report.source.version == "1"
    assert plan.report.node_counts == {"CLOUD_RESOURCE": 1, "IDENTITY": 1}
    assert plan.report.edge_counts == {"grants": 1}
    assert len(plan.report.declined) == 1
    assert tuple(ingest_cloud_inventory(inv, g)) == plan.upserts


def test_plan_applies_to_graph(g):
    apply_plan(g, ingest_cloud_inventory_plan(_inv(), g))
    res = g.execute(
        "MATCH (i:IDENTITY {id: $i})-[r:grants]->(c:CLOUD_RESOURCE {id: $c}) RETURN count(r)",
        {"i": USER, "c": RES},
    )
    assert res.get_next()[0] == 1


def test_declined_items_never_contain_raw_input(g):
    secret = "SECRET-TOKEN-abc123"
    docs = [
        "{" + secret,
        json.dumps({"resources": [{"id": secret}]}),
        _inv(
            resources=[{"id": secret}, {"resource_type": secret}],
            identities=[{"id": secret}, {"name": secret}],
            grants=[{"identity": secret, "resource": secret}],
        ),
    ]
    for d in docs:
        plan = ingest_cloud_inventory_plan(d, g)
        assert plan.report.declined
        for item in plan.report.declined:
            assert secret not in item.reason
            assert secret not in item.detail
