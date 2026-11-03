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
BRIEF_MERGE = "079a76f"  # brief 12 merged to main (PR #20 squash); seals this audit to brief 12's footprint
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
        ["git", "diff", "--name-only", f"{BRIEF_BASE}..{BRIEF_MERGE}"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    assert set(out) <= SECTION_3


# ---- SPEC_BRIEF33: G3 evidence persistence (AC2/AC3/AC4/AC5) ----
def _live_infra_outcome():
    return validate_service_reachable(_arm("A", True, 1), _arm("B", False, 0))


def _evidence_rows(g, finding_id):
    r = g.execute(
        "MATCH (e:EVIDENCE)-[:evidences]->(f:FINDING) WHERE f.id = $fid RETURN e.sha256, e.kind",
        {"fid": finding_id},
    )
    rows = []
    while r.has_next():
        rows.append(tuple(r.get_next()))
    return rows


def test_B33_AC2_AC4_infra_live_persists_evidence(g, tmp_path, nonet):
    import hashlib

    from kronos.lifecycle import _evidence_count
    from kronos.validate.infra_validator import record_infra_finding

    outcome = _live_infra_outcome()
    assert outcome.live
    fid = record_infra_finding(g, IN_SCOPE_IDS[0], outcome, engagement_dir=tmp_path)
    assert _evidence_rows(g, fid) == [(hashlib.sha256(outcome.evidence).hexdigest(), "validation_proof")]
    assert _evidence_count(g, "finding", fid) >= 1
    assert g.get_node("FINDING", fid)["status"] == "reachable"
    assert not nonet


def test_B33_AC3_infra_no_evidence_without_inputs(g, tmp_path, nonet):
    from kronos.validate.infra_validator import record_infra_finding

    fid = record_infra_finding(g, IN_SCOPE_IDS[0], None, engagement_dir=tmp_path)
    assert _evidence_rows(g, fid) == []
    fid2 = record_infra_finding(g, IN_SCOPE_IDS[1], _live_infra_outcome())
    assert _evidence_rows(g, fid2) == []
    assert not nonet


def test_B33_AC2_infra_pass_threads_engagement_dir(g, tmp_path, nonet):
    report = run_infra_validation_pass(g, probe=_open_ports_probe({4566, 4567, 8091}), engagement_dir=tmp_path)
    assert report.findings
    for fid in report.findings:
        assert len(_evidence_rows(g, fid)) == 1
    assert not nonet


def test_B33_AC5_infra_evidence_source_VALIDATION(g, tmp_path, monkeypatch, nonet):
    from kronos.commit import GraphMutationAuthority, MutationSource
    from kronos.validate.infra_validator import record_infra_finding

    seen = []
    orig = GraphMutationAuthority.upsert_node

    def spy(self, label, id_, props, *a, **kw):
        if label == "EVIDENCE":
            seen.append(kw.get("source"))
        return orig(self, label, id_, props, *a, **kw)

    monkeypatch.setattr(GraphMutationAuthority, "upsert_node", spy)
    record_infra_finding(g, IN_SCOPE_IDS[0], _live_infra_outcome(), engagement_dir=tmp_path)
    assert seen == [MutationSource.VALIDATION]
    assert not nonet
