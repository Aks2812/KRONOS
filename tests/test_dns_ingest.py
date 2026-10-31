"""SPEC_BRIEF26 §8 criteria A-K (hermetic; expected values from §2 prose)."""

from __future__ import annotations

import json
import socket
import subprocess

import pytest

from kronos.graph import EngagementGraph
from kronos.ingest import EdgeUpsert, NodeUpsert, apply_upserts, ingest
from kronos.ingest.contract import DeclinedItem, IngestPlan, apply_plan
from kronos.ingest.dns.parser import DNS_SOURCE, ingest_dns_records, ingest_dns_records_plan

B26_BASE = "4ff38f4"
B26_MERGE = "31ca3b5"
SECTION_3 = {
    "SPEC_BRIEF26.md",
    "src/kronos/ingest/dns/__init__.py",
    "src/kronos/ingest/dns/parser.py",
    "src/kronos/ingest/__init__.py",
    "tests/test_dns_ingest.py",
    "tests/test_agent_live_executor.py",
}


@pytest.fixture
def g(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    manifest = manifest_factory(scope={"in_scope": ["host.example.com", "1.2.3.4"], "excluded": []})
    return EngagementGraph.init_engagement(tmp_path / "e.kz", manifest, pub)


def _edges(g, a, b):
    res = g.execute(
        "MATCH (h:HOST {id: $a})-[r:resolves_to]->(s:HOST {id: $b}) RETURN count(r)",
        {"a": a, "b": b},
    )
    return res.get_next()[0]


def _hosts(g):
    res = g.execute("MATCH (h:HOST) RETURN count(h)")
    return res.get_next()[0]


def _raw(*records):
    return json.dumps(list(records))


A_REC = {"name": "host.example.com", "type": "A", "value": "1.2.3.4"}


def test_A_a_record_nodes_edge_idempotent(g):
    raw = _raw(A_REC)
    apply_upserts(g, ingest_dns_records(raw, g))
    assert g.get_node("HOST", "host.example.com") is not None
    assert g.get_node("HOST", "1.2.3.4") is not None
    assert _edges(g, "host.example.com", "1.2.3.4") == 1
    n = _hosts(g)
    apply_plan(g, ingest_dns_records_plan(raw, g))
    assert _hosts(g) == n
    assert _edges(g, "host.example.com", "1.2.3.4") == 1


def test_A_dispatcher(g):
    out = ingest(_raw(A_REC), "dns_records", g)
    assert out == ingest_dns_records(_raw(A_REC), g)
    assert isinstance(ingest_dns_records_plan(_raw(A_REC), g), IngestPlan)


def test_B_aaaa(g):
    apply_upserts(g, ingest_dns_records(_raw({"name": "v6.example.com", "type": "AAAA", "value": "2001:db8::1"}), g))
    assert g.get_node("HOST", "2001:db8::1") is not None
    assert _edges(g, "v6.example.com", "2001:db8::1") == 1


def test_C_cname_normalized(g):
    rec = {"name": "Alias.Example.com.", "type": "CNAME", "value": "Host.Example.com."}
    ups = ingest_dns_records(_raw(rec), g)
    assert ups[-1] == EdgeUpsert("resolves_to", "alias.example.com", "host.example.com")
    apply_upserts(g, ups)
    assert g.get_node("HOST", "host.example.com") is not None
    assert _edges(g, "alias.example.com", "host.example.com") == 1


def test_D_deterministic_order(g):
    recs = [A_REC, {"name": "B.example.com.", "type": "CNAME", "value": "host.example.com"}]
    expected = (
        NodeUpsert("HOST", "host.example.com", {"source": "dns"}, scope_key="host.example.com"),
        NodeUpsert("HOST", "1.2.3.4", {"source": "dns"}, scope_key="1.2.3.4"),
        EdgeUpsert("resolves_to", "host.example.com", "1.2.3.4"),
        NodeUpsert("HOST", "b.example.com", {"source": "dns"}, scope_key="b.example.com"),
        NodeUpsert("HOST", "host.example.com", {"source": "dns"}, scope_key="host.example.com"),
        EdgeUpsert("resolves_to", "b.example.com", "host.example.com"),
    )
    assert ingest_dns_records_plan(_raw(*recs), g).upserts == expected
    assert ingest_dns_records_plan(_raw(*recs), g).upserts == expected


@pytest.mark.parametrize("bad", ["not json {", json.dumps({"name": "a.b", "type": "A", "value": "1.2.3.4"}), None])
def test_E_unparseable_declined(g, bad):
    control = ingest_dns_records_plan(_raw(A_REC), g)
    assert control.upserts  # non-vacuity
    plan = ingest_dns_records_plan(bad, g)
    assert plan.upserts == ()
    assert [d.reason for d in plan.report.declined] == ["unparseable_dns_json"]
    assert ingest_dns_records(bad, g) == []


def test_F_per_record_declines(g):
    recs = [
        A_REC,
        "not an object",
        {"name": "a.example.com", "type": "A"},
        {"name": "a.example.com", "type": "MX", "value": "mail.example.com"},
        {"name": "a.example.com", "type": "A", "value": "not-an-ip"},
        {"name": "a.example.com", "type": "AAAA", "value": "1.2.3.4"},
        {"name": "a.example.com", "type": "CNAME", "value": "1.2.3.4"},
        {"name": "not a host", "type": "A", "value": "1.2.3.4"},
    ]
    plan = ingest_dns_records_plan(_raw(*recs), g)
    assert len(plan.upserts) == 3
    assert all(isinstance(d, DeclinedItem) for d in plan.report.declined)
    assert [d.reason for d in plan.report.declined] == [
        "missing_field",
        "missing_field",
        "unsupported_record_type",
        "malformed_address",
        "malformed_address",
        "malformed_fqdn",
        "malformed_fqdn",
    ]
    assert all(getattr(u, "id", None) in (None, "host.example.com", "1.2.3.4") for u in plan.upserts)


def test_G_provenance(g):
    apply_plan(g, ingest_dns_records_plan(_raw(A_REC), g))
    assert DNS_SOURCE.name == "dns"
    for hid in ("host.example.com", "1.2.3.4"):
        assert g.get_node("HOST", hid)["source"] == DNS_SOURCE.name


def test_H_scope_enforced(g):
    apply_plan(g, ingest_dns_records_plan(_raw(A_REC, {"name": "out.other.org", "type": "A", "value": "9.9.9.9"}), g))
    assert g.get_node("HOST", "host.example.com")["in_scope"] is True
    assert g.get_node("HOST", "out.other.org")["in_scope"] is False


def test_I_no_network(g, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("socket used")

    monkeypatch.setattr(socket, "socket", boom)
    plan = ingest_dns_records_plan(_raw(A_REC), g)
    assert plan.upserts


def test_J_scope_audit():
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{B26_BASE}..{B26_MERGE}"], capture_output=True, text=True, check=True
    ).stdout.split()
    assert set(out) <= SECTION_3, set(out) - SECTION_3
