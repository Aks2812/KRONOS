"""SPEC_BRIEF13 §8 criteria A-L. Expected values derive from the brief prose."""

from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

import pytest

from kronos.graph import EngagementGraph
from kronos.ingest import EdgeUpsert, NodeUpsert, apply_upserts, ingest
from kronos.ingest.contract import DeclinedItem, IngestionSource, apply_plan
from kronos.ingest.infra.parser import ingest_infra_nmap_plan
from kronos.ingest.web.parser import ingest_web_openapi, ingest_web_openapi_plan

ROOT = Path(__file__).parent
FIXTURE = ROOT / "fixtures" / "web" / "cybergym_openapi.json"
NMAP_FIXTURE = ROOT / "fixtures" / "infra" / "cybergym_nmap.xml"
BRIEF_BASE = "079a76f"
SECTION_3 = {
    "SPEC_BRIEF13.md",
    "src/kronos/ingest/web/__init__.py",
    "src/kronos/ingest/web/parser.py",
    "src/kronos/ingest/__init__.py",
    "tests/test_web_ingest.py",
    "tests/fixtures/web/cybergym_openapi.json",
    "tests/test_infra_validator.py",
}
HEALTH = "web:GET:http://127.0.0.1:8091/health"
ITEMS = "web:GET:http://127.0.0.1:8091/items/{item_id}"
SID = "127.0.0.1:8091/tcp"
P_ITEM = f"param:{ITEMS}:path:item_id"
P_VERBOSE = f"param:{ITEMS}:query:verbose"


@pytest.fixture
def doc():
    return FIXTURE.read_text()


@pytest.fixture
def g(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    manifest = manifest_factory(scope={"in_scope": ["127.0.0.1*"], "excluded": []})
    return EngagementGraph.init_engagement(tmp_path / "e.kz", manifest, pub)


def _count(g, q, params=None):
    return g.execute(q, params or {}).get_next()[0]


def _has_param(g, e, p):
    return _count(
        g,
        "MATCH (w:WEB_ENDPOINT {id: $e})-[r:has_param]->(p:PARAMETER {id: $p}) RETURN count(r)",
        {"e": e, "p": p},
    )


def _exposes(g, e):
    return _count(
        g,
        "MATCH (s:SERVICE {id: $s})-[r:exposes]->(w:WEB_ENDPOINT {id: $e}) RETURN count(r)",
        {"s": SID, "e": e},
    )


def test_A_plan_face_satisfies_ingestion_source():
    assert isinstance(ingest_web_openapi_plan, IngestionSource)


def test_B_dispatcher(g, doc):
    out = ingest(doc, "web_openapi", g)
    assert isinstance(out, list) and out
    assert all(isinstance(u, (NodeUpsert, EdgeUpsert)) for u in out)
    with pytest.raises(NotImplementedError):
        ingest(doc, "no_such_tool", g)


def test_C_endpoints(g, doc):
    apply_plan(g, ingest_web_openapi_plan(doc, g))
    for eid, url in ((HEALTH, "http://127.0.0.1:8091/health"), (ITEMS, "http://127.0.0.1:8091/items/{item_id}")):
        n = g.get_node("WEB_ENDPOINT", eid)
        assert n is not None
        assert n["url"] == url and n["method"] == "GET"


def test_C_accepts_parsed_dict(g, doc):
    apply_plan(g, ingest_web_openapi_plan(json.loads(doc), g))
    assert g.get_node("WEB_ENDPOINT", HEALTH) is not None


def test_D_parameters_and_has_param(g, doc):
    apply_plan(g, ingest_web_openapi_plan(doc, g))
    assert g.get_node("PARAMETER", P_ITEM)["param_type"] == "path"
    assert g.get_node("PARAMETER", P_ITEM)["name"] == "item_id"
    assert g.get_node("PARAMETER", P_VERBOSE)["param_type"] == "query"
    assert _has_param(g, ITEMS, P_ITEM) == 1
    assert _has_param(g, ITEMS, P_VERBOSE) == 1
    assert _count(g, "MATCH (p:PARAMETER) RETURN count(p)") == 2  # /health has none


def test_E_scope_gating_inherited(g, doc):
    apply_plan(g, ingest_web_openapi_plan(doc, g))
    for t, i in (("WEB_ENDPOINT", HEALTH), ("WEB_ENDPOINT", ITEMS), ("PARAMETER", P_ITEM), ("PARAMETER", P_VERBOSE)):
        assert g.get_node(t, i)["in_scope"] is True
    props = {"source": "openapi", "url": "http://x/y", "method": "GET"}
    g.upsert_node("WEB_ENDPOINT", "web:GET:noscope", props)
    assert g.get_node("WEB_ENDPOINT", "web:GET:noscope")["in_scope"] is False
    g.upsert_node("WEB_ENDPOINT", "web:GET:oos", props, scope_key="10.0.0.1")
    assert g.get_node("WEB_ENDPOINT", "web:GET:oos")["in_scope"] is False


def test_E_out_of_scope_host_via_parser(g, doc):
    d = json.loads(doc)
    d["servers"] = [{"url": "http://10.0.0.1:8091"}]
    apply_plan(g, ingest_web_openapi_plan(d, g))
    assert g.get_node("WEB_ENDPOINT", "web:GET:http://10.0.0.1:8091/health")["in_scope"] is False


def test_F_seeded_from_s3(g, doc):
    apply_plan(g, ingest_infra_nmap_plan(NMAP_FIXTURE.read_text(), g))
    assert g.get_node("SERVICE", SID) is not None
    apply_plan(g, ingest_web_openapi_plan(doc, g))
    assert _exposes(g, HEALTH) == 1
    assert _exposes(g, ITEMS) == 1


def test_F_unseeded_no_exposes_no_error(g, doc):
    plan = ingest_web_openapi_plan(doc, g)
    apply_plan(g, plan)
    assert not [u for u in plan.upserts if isinstance(u, EdgeUpsert) and u.label == "exposes"]
    assert _count(g, "MATCH ()-[r:exposes]->() RETURN count(r)") == 0
    assert g.get_node("SERVICE", SID) is None  # parser never creates a SERVICE


def test_F_node_before_edges(g, doc):
    apply_plan(g, ingest_infra_nmap_plan(NMAP_FIXTURE.read_text(), g))
    seen = set()
    for u in ingest_web_openapi_plan(doc, g).upserts:
        if isinstance(u, NodeUpsert):
            seen.add(u.id)
        elif u.label == "has_param":
            assert u.from_id in seen and u.to_id in seen
        elif u.label == "exposes":
            assert u.to_id in seen


def test_G_forbidden_props(g, doc):
    plan = ingest_web_openapi_plan(doc, g)
    forbidden = {"in_scope", "confidence", "scope_note", "merged_into"}
    for u in plan.upserts:
        if isinstance(u, NodeUpsert):
            assert not (forbidden & u.props.keys())
            assert u.scope_key == "127.0.0.1"
    apply_plan(g, plan)  # must not raise ValueError


def test_H_no_socket_io(g, doc, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("socket used")

    monkeypatch.setattr(socket, "socket", boom)
    apply_plan(g, ingest_web_openapi_plan(doc, g))
    assert g.get_node("WEB_ENDPOINT", HEALTH) is not None


@pytest.mark.parametrize("bad", ["{not json", '{"openapi": "3.0.3"}', "[]", None])
def test_H_bad_input_declined_not_raised(g, bad):
    plan = ingest_web_openapi_plan(bad, g)
    assert plan.upserts == ()
    assert plan.report.declined
    assert all(isinstance(d, DeclinedItem) for d in plan.report.declined)
    assert ingest_web_openapi(bad, g) == []


def test_I_report(g, doc):
    plan = ingest_web_openapi_plan(doc, g)
    assert plan.report.node_counts == {"WEB_ENDPOINT": 2, "PARAMETER": 2}
    assert plan.report.edge_counts == {"has_param": 2}
    apply_plan(g, ingest_infra_nmap_plan(NMAP_FIXTURE.read_text(), g))
    seeded = ingest_web_openapi_plan(doc, g)
    assert seeded.report.edge_counts == {"has_param": 2, "exposes": 2}


def test_J_idempotent(g, doc):
    apply_plan(g, ingest_infra_nmap_plan(NMAP_FIXTURE.read_text(), g))
    plan = ingest_web_openapi_plan(doc, g)
    apply_plan(g, plan)
    apply_plan(g, plan)
    assert _count(g, "MATCH (w:WEB_ENDPOINT) RETURN count(w)") == 2
    assert _count(g, "MATCH (p:PARAMETER) RETURN count(p)") == 2
    assert _count(g, "MATCH ()-[r:has_param]->() RETURN count(r)") == 2
    assert _count(g, "MATCH ()-[r:exposes]->() RETURN count(r)") == 2


def test_K_scope_audit():
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{BRIEF_BASE}..HEAD"], cwd=ROOT.parent, capture_output=True, text=True, check=True
    ).stdout.split()
    assert set(out) <= SECTION_3


def test_L_brief12_seal():
    src = (ROOT / "test_infra_validator.py").read_text()
    assert 'BRIEF_MERGE = "079a76f"' in src
    assert 'f"{BRIEF_BASE}..{BRIEF_MERGE}"' in src
    assert "..HEAD" not in src
