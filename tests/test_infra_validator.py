"""SPEC_BRIEF12 §8 criteria A-J (expected values derive from the brief's prose)."""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import pytest

from kronos.graph import EngagementGraph
from kronos.ingest.contract import apply_plan
from kronos.ingest.infra.parser import ingest_infra_nmap_plan
from kronos.validate.controls import ArmResult, run_differential
from kronos.validate.infra_validator import (
    run_infra_validation_pass,
    validate_service_reachable,
)
from kronos.validate.types import ValidationOutcome

FIXTURE = Path(__file__).parent / "fixtures" / "infra" / "cybergym_nmap.xml"
BRIEF_BASE = "19c9464"
SECTION_3 = {
    "SPEC_BRIEF12.md",
    "src/kronos/validate/controls.py",
    "src/kronos/validate/infra_validator.py",
    "tests/test_infra_validator.py",
    "tests/test_infra_ingest.py",
}
IN_SCOPE_IDS = [f"127.0.0.1:{p}/tcp" for p in (4566, 4567, 8091)]
OUT_OF_SCOPE_ID = "10.0.0.1:22/tcp"


@pytest.fixture
def g(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    manifest = manifest_factory(scope={"in_scope": ["127.0.0.1*"], "excluded": []})
    graph = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest, pub)
    apply_plan(graph, ingest_infra_nmap_plan(FIXTURE.read_text(), graph))
    return graph


def _arm(label, success, status=None, transport_error=False):
    return ArmResult(label=label, success=success, status_code=status, transport_error=transport_error)


def _open_ports_probe(open_ports, calls=None):
    def probe(host, port):
        if calls is not None:
            calls.append((host, port))
        ok = port in open_ports
        return ArmResult(label="probe", success=ok, status_code=1 if ok else 0)

    return probe


def _count(g, q):
    return g.execute(q).get_next()[0]


def test_A_differential_kind_infra():
    r = run_differential([_arm("A_canonical", True), _arm("B_negative_control", False)], kind="infra")
    assert r.classification == "live_discriminated" and r.live is True and r.discriminated is True
    r = run_differential([_arm("A_canonical", True), _arm("B_negative_control", True)], kind="infra")
    assert r.classification == "indiscriminate_target" and r.live is False
    r = run_differential([_arm("A_canonical", False), _arm("B_negative_control", False)], kind="infra")
    assert r.classification == "not_live" and r.live is False


def test_B_outcome_invariant():
    live = validate_service_reachable(_arm("A_canonical", True, 1), _arm("B_negative_control", False, 0))
    assert isinstance(live, ValidationOutcome)
    assert live.live and live.discriminated and live.classification == "live_discriminated"
    for a, b in [(True, True), (False, False), (False, True)]:
        o = validate_service_reachable(_arm("A_canonical", a), _arm("B_negative_control", b))
        assert isinstance(o, ValidationOutcome) and o.live is False
    inc = validate_service_reachable(
        _arm("A_canonical", False, transport_error=True), _arm("B_negative_control", False, transport_error=True)
    )
    assert inc.classification == "inconclusive" and inc.live is False


def test_C_in_scope_only(g):
    calls = []
    run_infra_validation_pass(g, probe=_open_ports_probe({4566, 4567, 8091}, calls))
    assert calls
    assert {h for h, _ in calls} == {"127.0.0.1"}
    assert 22 not in {p for _, p in calls}
    assert {p for _, p in calls} >= {4566, 4567, 8091}


def test_D_finding_on_live(g):
    run_infra_validation_pass(g, probe=_open_ports_probe({4566, 4567, 8091}))
    for sid in IN_SCOPE_IDS:
        fid = f"finding:infra-reachable:{sid}"
        f = g.get_node("FINDING", fid)
        assert f is not None
        assert f["status"] == "reachable" and f["confidence"] == 7
        res = g.execute(
            "MATCH (s:SERVICE {id: $s})-[r:vulnerable_to]->(f:FINDING {id: $f}) RETURN count(r)",
            {"s": sid, "f": fid},
        )
        assert res.get_next()[0] == 1
    assert g.get_node("FINDING", f"finding:infra-reachable:{OUT_OF_SCOPE_ID}") is None


@pytest.mark.parametrize(
    "open_ports",
    [
        set(),  # canonical fails -> not_live
        {4566, 4567, 8091, 9999},  # control also succeeds -> indiscriminate
    ],
)
def test_E_abstention(g, open_ports):
    run_infra_validation_pass(g, probe=_open_ports_probe(open_ports))
    assert _count(g, "MATCH (f:FINDING) RETURN count(f)") == 0
    assert _count(g, "MATCH ()-[r:vulnerable_to]->() RETURN count(r)") == 0


def test_E_abstention_inconclusive(g):
    def probe(host, port):
        return ArmResult(label="probe", success=False, transport_error=True)

    run_infra_validation_pass(g, probe=probe)
    assert _count(g, "MATCH (f:FINDING) RETURN count(f)") == 0
    assert _count(g, "MATCH ()-[r:vulnerable_to]->() RETURN count(r)") == 0


def test_F_no_leak():
    o = validate_service_reachable(
        _arm("A_canonical", True, 200), _arm("B_negative_control", False, 0)
    )
    text = (o.evidence.decode() + " " + o.detail + " " + o.control_outcome).lower()
    assert "a_canonical" in text and "b_negative_control" in text
    for bad in ("password", "secret", "token", "authorization", "bearer"):
        assert bad not in text
    assert o.evidence


def test_G_no_live_network(g, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("socket used")

    monkeypatch.setattr(socket, "socket", boom)
    calls = []
    run_infra_validation_pass(g, probe=_open_ports_probe({4566, 4567, 8091}, calls))
    assert calls
    assert g.get_node("FINDING", f"finding:infra-reachable:{IN_SCOPE_IDS[0]}") is not None


def test_H_control_same_host_closed_port(g):
    calls = []
    run_infra_validation_pass(g, probe=_open_ports_probe({4566, 4567, 8091}, calls))
    assert len(calls) % 2 == 0
    for (ch, cp), (kh, kp) in zip(calls[0::2], calls[1::2]):
        assert ch == kh == "127.0.0.1"
        assert kp != cp
        assert kp not in {4566, 4567, 8091}


def test_I_idempotent(g):
    probe = _open_ports_probe({4566, 4567, 8091})
    run_infra_validation_pass(g, probe=probe)
    run_infra_validation_pass(g, probe=probe)
    assert _count(g, "MATCH (f:FINDING) RETURN count(f)") == 3
    assert _count(g, "MATCH ()-[r:vulnerable_to]->() RETURN count(r)") == 3
    assert g.get_node("FINDING", f"finding:infra-reachable:{IN_SCOPE_IDS[0]}")["status"] == "reachable"


def test_J_scope_audit():
    root = Path(__file__).parent.parent
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{BRIEF_BASE}..HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    assert set(out) <= SECTION_3
