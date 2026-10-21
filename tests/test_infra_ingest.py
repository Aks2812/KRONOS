"""SPEC_BRIEF11 §8 criteria A-J (K is the scope audit, run against git)."""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import pytest

from kronos.graph import EngagementGraph
from kronos.ingest import EdgeUpsert, NodeUpsert, ingest
from kronos.ingest.contract import DeclinedItem, IngestionSource, IngestPlan, apply_plan
from kronos.ingest.infra.parser import ingest_infra_nmap, ingest_infra_nmap_plan

FIXTURE = Path(__file__).parent / "fixtures" / "infra" / "cybergym_nmap.xml"
SERVICE_PORTS = (4566, 4567, 8091)
BRIEF_BASE = "a2feba3"
BRIEF_MERGE = "19c9464"  # brief 11 merged to main (PR #19 squash); seals this audit to brief 11's footprint
SECTION_3 = {
    "SPEC_BRIEF11.md",
    "src/kronos/ingest/infra/__init__.py",
    "src/kronos/ingest/infra/parser.py",
    "src/kronos/ingest/__init__.py",
    "tests/test_infra_ingest.py",
    "tests/fixtures/infra/cybergym_nmap.xml",
}


@pytest.fixture
def xml_text():
    return FIXTURE.read_text()


@pytest.fixture
def g(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    manifest = manifest_factory(scope={"in_scope": ["127.0.0.1*"], "excluded": []})
    return EngagementGraph.init_engagement(tmp_path / "e.kz", manifest, pub)


def _edge_count(g, host_id, service_id):
    res = g.execute(
        "MATCH (h:HOST {id: $h})-[r:hosts]->(s:SERVICE {id: $s}) RETURN count(r)",
        {"h": host_id, "s": service_id},
    )
    return res.get_next()[0]


def test_A_plan_face_satisfies_ingestion_source():
    assert isinstance(ingest_infra_nmap_plan, IngestionSource)


def test_B_dispatcher(g, xml_text):
    out = ingest(xml_text, "infra_nmap", g)
    assert isinstance(out, list) and out
    assert all(isinstance(u, (NodeUpsert, EdgeUpsert)) for u in out)
    with pytest.raises(NotImplementedError):
        ingest(xml_text, "no_such_tool", g)


def test_C_nodes(g, xml_text):
    apply_plan(g, ingest_infra_nmap_plan(xml_text, g))
    assert g.get_node("HOST", "127.0.0.1") is not None
    for port in SERVICE_PORTS:
        svc = g.get_node("SERVICE", f"127.0.0.1:{port}/tcp")
        assert svc is not None
        assert isinstance(svc["port"], int) and svc["port"] == port
        assert svc["protocol"] == "tcp"


def test_D_edges(g, xml_text):
    apply_plan(g, ingest_infra_nmap_plan(xml_text, g))
    for port in SERVICE_PORTS:
        assert _edge_count(g, "127.0.0.1", f"127.0.0.1:{port}/tcp") == 1


def test_E_open_only(g, xml_text):
    plan = ingest_infra_nmap_plan(xml_text, g)
    apply_plan(g, plan)
    assert g.get_node("SERVICE", "127.0.0.1:9999/tcp") is None
    assert all(not (isinstance(u, NodeUpsert) and u.id.endswith(":9999/tcp")) for u in plan.upserts)
    assert plan.report.declined
    assert all(isinstance(d, DeclinedItem) for d in plan.report.declined)


def test_F_forbidden_props(g, xml_text):
    plan = ingest_infra_nmap_plan(xml_text, g)
    forbidden = {"in_scope", "confidence", "scope_note", "merged_into", "status"}
    for u in plan.upserts:
        if isinstance(u, NodeUpsert):
            assert not (forbidden & u.props.keys())
    apply_plan(g, plan)  # must not raise ValueError


def test_G_scope_gating_inherited(g, xml_text):
    apply_plan(g, ingest_infra_nmap_plan(xml_text, g))
    assert g.get_node("HOST", "127.0.0.1")["in_scope"] is True
    assert g.get_node("HOST", "10.0.0.1")["in_scope"] is False


def test_H_no_socket_io(g, xml_text, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("socket used")

    monkeypatch.setattr(socket, "socket", boom)
    apply_plan(g, ingest_infra_nmap_plan(xml_text, g))
    assert g.get_node("HOST", "127.0.0.1") is not None


def test_H_xxe_entity_not_resolved(g, tmp_path, monkeypatch):
    secret = tmp_path / "secret.txt"
    secret.write_text("XXE_SECRET_MARKER")
    hostile = f"""<?xml version="1.0"?>
<!DOCTYPE nmaprun [<!ENTITY xxe SYSTEM "file://{secret}">]>
<nmaprun><host><address addr="&xxe;" addrtype="ipv4"/>
<ports><port protocol="tcp" portid="80"><state state="open"/></port></ports></host></nmaprun>"""

    def boom(*a, **k):
        raise AssertionError("socket used")

    monkeypatch.setattr(socket, "socket", boom)
    plan = ingest_infra_nmap_plan(hostile, g)  # must not raise
    assert "XXE_SECRET_MARKER" not in repr(plan)


def test_unparseable_xml_declined_not_raised(g):
    plan = ingest_infra_nmap_plan("<nmaprun><host>SECRETBODY", g)
    assert plan.upserts == ()
    assert plan.report.declined
    assert "SECRETBODY" not in repr(plan.report)
    assert ingest_infra_nmap("<<<", g) == []


def test_missing_address_declined(g):
    plan = ingest_infra_nmap_plan(
        '<nmaprun><host><ports><port protocol="tcp" portid="80"><state state="open"/></port></ports></host></nmaprun>',
        g,
    )
    assert plan.upserts == ()
    assert plan.report.declined


def test_I_report(g, xml_text):
    report = ingest_infra_nmap_plan(xml_text, g).report
    assert report.node_counts.get("HOST", 0) >= 1
    assert report.node_counts.get("SERVICE", 0) >= 1
    assert report.edge_counts.get("hosts", 0) >= 1
    assert report.declined


def test_J_idempotent(g, xml_text):
    plan = ingest_infra_nmap_plan(xml_text, g)
    apply_plan(g, plan)
    apply_plan(g, plan)
    assert g.execute("MATCH (h:HOST) RETURN count(h)").get_next()[0] == 2
    assert g.execute("MATCH (s:SERVICE) RETURN count(s)").get_next()[0] == 4
    assert g.execute("MATCH ()-[r:hosts]->() RETURN count(r)").get_next()[0] == 4


def test_source_has_no_direct_graph_writes():
    src = (Path(__file__).parent.parent / "src/kronos/ingest/infra/parser.py").read_text()
    assert "upsert_node" not in src and "upsert_edge" not in src


def test_K_scope_audit():
    root = Path(__file__).parent.parent
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{BRIEF_BASE}..{BRIEF_MERGE}"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    assert set(out) <= SECTION_3
