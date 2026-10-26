"""SPEC_BRIEF18 §8 criteria A-M (executor behind the gate, promotion). Expected values derive from the brief's prose."""

from __future__ import annotations

import dataclasses
import inspect
import re
import socket
import subprocess
from pathlib import Path

import pytest

from kronos.agent import (
    EVIDENCE_KIND,
    ExecutionOutcome,
    MockDriver,
    MockExecutor,
    MockReviewer,
    ReviewVerdict,
    ReviewViolation,
    run,
    run_once,
)
from kronos.agent import dispatcher
from kronos.schema import ALL_NODE_TABLES

ROOT = Path(__file__).parent.parent
BRIEF_BASE = "a9f37ec"
BRIEF_MERGE = "5b7001d"  # sealed at the Brief18 merge; later briefs have their own audits
SECTION_3 = {
    "SPEC_BRIEF18.md",
    "src/kronos/agent/executor.py",
    "src/kronos/agent/dispatcher.py",
    "src/kronos/agent/__init__.py",
    "tests/test_agent_executor.py",
    "tests/test_agent_commit.py",
}
HOST_IN = "web.acme.example.com"  # matches manifest_factory default in_scope "*.acme.example.com"
HOST_OUT = "evil.other.example.org"
OK = ReviewVerdict(approved=True, target_type="HOST", status="hypothesis")
FID = f"finding:agent-proposal:probe:{HOST_IN}"
PROOF = ExecutionOutcome(succeeded=True, evidence=b"proof")


def _counts(g):
    nodes = sum(g.execute(f"MATCH (n:{t}) RETURN count(n)").get_next()[0] for t in ALL_NODE_TABLES)
    edges = g.execute("MATCH ()-[r]->() RETURN count(r)").get_next()[0]
    return nodes, edges


def _payload(target, kind="probe"):
    return {"intents": [{"kind": kind, "target_id": target, "rationale": "why"}]}


def _evidence_n(g):
    return g.execute("MATCH (e:EVIDENCE) RETURN count(e)").get_next()[0]


@pytest.fixture
def g(engagement_graph):
    engagement_graph.upsert_node("HOST", HOST_IN, {"source": "t"})
    engagement_graph.upsert_node("HOST", HOST_OUT, {"source": "t"})
    return engagement_graph


@pytest.fixture
def nonet(monkeypatch):
    used = []

    def _boom(*a, **k):
        used.append(1)
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    return used


class _Spy(MockExecutor):
    def __init__(self, scripted):
        super().__init__(scripted)
        self.seen = []

    def execute(self, intent):
        self.seen.append(intent)
        return super().execute(intent)


def test_A_outcome_and_mock():  # §8 A
    o = ExecutionOutcome(succeeded=True, evidence=b"x")
    assert o.detail == ""
    with pytest.raises(dataclasses.FrozenInstanceError):
        o.succeeded = False
    o2 = ExecutionOutcome(succeeded=False, evidence=None)
    m = MockExecutor([o, o2])
    assert m.execute(None) is o and m.execute(None) is o2
    with pytest.raises(RuntimeError):
        m.execute(None)
    assert EVIDENCE_KIND == "agent_execution_proof"


def test_B_promotion_happy(g, tmp_path):  # §8 B
    res = run_once(g, MockDriver([_payload(HOST_IN)]), MockReviewer([OK]), executor=MockExecutor([PROOF]),
                   engagement_dir=tmp_path)
    assert res.committed == (FID,) and res.promoted == (FID,)
    node = g.get_node("FINDING", FID)
    assert node["status"] == "reachable" and node["confidence"] == 9
    assert _evidence_n(g) == 1
    kind = g.execute(
        "MATCH (e:EVIDENCE)-[r:evidences]->(f:FINDING {id: $f}) RETURN e.kind", {"f": FID}
    ).get_next()[0]
    assert kind == "agent_execution_proof"


def test_C_evidenceless_not_promoted(g, tmp_path):  # §8 C
    ex = MockExecutor([ExecutionOutcome(succeeded=True, evidence=None)])
    res = run_once(g, MockDriver([_payload(HOST_IN)]), MockReviewer([OK]), executor=ex, engagement_dir=tmp_path)
    assert res.committed == (FID,) and res.promoted == ()
    node = g.get_node("FINDING", FID)
    assert node["status"] == "hypothesis"
    # SPEC_BRIEF18 §8 C: create-time confidence is 0 (_commit is create-only); nothing here may write it,
    # so assert only the hypothesis cap (< 7).
    assert node["confidence"] < 7
    assert _evidence_n(g) == 0


@pytest.mark.parametrize("ev", [None, b"proof"])
def test_D_failed_not_promoted(g, tmp_path, ev):  # §8 D
    ex = MockExecutor([ExecutionOutcome(succeeded=False, evidence=ev)])
    res = run_once(g, MockDriver([_payload(HOST_IN)]), MockReviewer([OK]), executor=ex, engagement_dir=tmp_path)
    assert res.promoted == ()
    assert g.get_node("FINDING", FID)["status"] == "hypothesis"


def test_E_executor_behind_gate(g, tmp_path):  # §8 E
    drv = MockDriver([{"intents": [
        {"kind": "probe", "target_id": HOST_IN, "rationale": "r"},
        {"kind": "probe", "target_id": HOST_OUT, "rationale": "r"},
        {"kind": "rej", "target_id": HOST_IN, "rationale": "r"},
    ]}])
    rev = MockReviewer([OK, OK, ReviewVerdict(False, "HOST", "hypothesis")])
    ex = _Spy([PROOF])
    res = run_once(g, drv, rev, executor=ex, engagement_dir=tmp_path)
    assert res.committed == (FID,) and res.promoted == (FID,)
    assert [i.target_id for i in ex.seen] == [HOST_IN] and [i.kind for i in ex.seen] == ["probe"]


def test_F_engagement_dir_required(g):  # §8 F
    before = _counts(g)
    with pytest.raises(ValueError):
        run_once(g, MockDriver([_payload(HOST_IN)]), MockReviewer([OK]), executor=MockExecutor([PROOF]))
    assert _counts(g) == before
    assert g.get_node("FINDING", FID) is None


def test_G_backward_compat(g):  # §8 G
    res = run_once(g, MockDriver([_payload(HOST_IN)]), MockReviewer([OK]))
    assert res.committed == (FID,) and res.promoted == ()
    assert g.get_node("FINDING", FID)["status"] == "hypothesis"
    before = _counts(g)
    r = run_once(g, MockDriver([_payload(HOST_IN, "other")]))
    assert r.committed == () and r.promoted == () and _counts(g) == before


def test_H_atomicity(g, tmp_path):  # §8 H
    before = _counts(g)
    ex = _Spy([PROOF])
    with pytest.raises(ReviewViolation):
        run_once(g, MockDriver([_payload(HOST_IN)]), MockReviewer([ReviewVerdict(True, "HOST", "reachable")]),
                 executor=ex, engagement_dir=tmp_path)
    assert _counts(g) == before and ex.seen == []


def test_I_no_live_network(g, nonet, tmp_path):  # §8 I
    drv = MockDriver([_payload(HOST_IN), {"complete": True}])
    rs = run(g, drv, max_steps=3, reviewer=MockReviewer([OK]), executor=MockExecutor([PROOF]),
             engagement_dir=tmp_path)
    assert rs[0].promoted == (FID,) and not nonet  # no socket at all, hence none outside the CyberGym range


def test_J_chokepoints_only():  # §8 J
    src = inspect.getsource(dispatcher)
    assert re.search(r"\battach_evidence\(", src) and re.search(r"\badvance_finding_status\(", src)
    assert 'EVIDENCE_KIND' in src
    # strip the Phase-1/2 helper _commit (pre-existing create-only write) and inspect the rest
    body = inspect.getsource(dispatcher.run_once)
    forbidden_patterns = ('"confidence"', '"status"', "'confidence'", "'status'", '"in_scope"', '"merged_into"',
                          "upsert_node", "upsert_edge", "_set_finding_fields")
    for forbidden in forbidden_patterns:
        assert forbidden not in body
    assert not re.search(r"\.(status|confidence)\s*=[^=]", body)
    # non-vacuity: the same tuple used for the scan flags a direct write
    bad = 'engagement.upsert_node("FINDING", fid, {"status": "reachable", "confidence": 9})'
    assert any(f in bad for f in forbidden_patterns)


def test_K_end_to_end(g, nonet, tmp_path):  # §8 K
    drv = MockDriver([_payload(HOST_IN, "a"), _payload(HOST_IN, "b"), {"complete": True}, _payload(HOST_IN, "never")])
    ex = MockExecutor([PROOF, ExecutionOutcome(succeeded=False, evidence=None)])
    rs = run(g, drv, max_steps=5, reviewer=MockReviewer([OK, OK]), executor=ex, engagement_dir=tmp_path)
    assert len(rs) == 3 and rs[-1].complete
    assert [x.promoted for x in rs] == [(f"finding:agent-proposal:a:{HOST_IN}",), (), ()]
    assert g.get_node("FINDING", f"finding:agent-proposal:a:{HOST_IN}")["status"] == "reachable"
    assert g.get_node("FINDING", f"finding:agent-proposal:b:{HOST_IN}")["status"] == "hypothesis"
    assert not nonet


def test_L_scope_audit():  # §8 L
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{BRIEF_BASE}..{BRIEF_MERGE}"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert set(out) <= SECTION_3


def test_M_brief17_seal():  # §8 M
    src = (ROOT / "tests" / "test_agent_commit.py").read_text()
    assert 'BRIEF_MERGE = "a9f37ec"' in src
    assert 'f"{BRIEF_BASE}..{BRIEF_MERGE}"' in src
