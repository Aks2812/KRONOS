"""SPEC_BRIEF17 §8 criteria F-O (commit gate / rails). Expected values derive from the brief's prose."""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import pytest

from kronos.agent import MockDriver, MockReviewer, ReviewVerdict, ReviewViolation, run, run_once
from kronos.agent import dispatcher
from kronos.schema import ALL_NODE_TABLES

ROOT = Path(__file__).parent.parent
BRIEF_BASE = "f4559a2"
SECTION_3 = {
    "SPEC_BRIEF17.md",
    "src/kronos/agent/reviewer.py",
    "src/kronos/agent/dispatcher.py",
    "src/kronos/agent/__init__.py",
    "tests/test_agent_reviewer.py",
    "tests/test_agent_commit.py",
    "tests/test_agent_dispatcher.py",
}
HOST_IN = "web.acme.example.com"  # matches manifest_factory default in_scope "*.acme.example.com"
HOST_OUT = "evil.other.example.org"
OK = ReviewVerdict(approved=True, target_type="HOST", status="hypothesis")


def _counts(g):
    nodes = sum(g.execute(f"MATCH (n:{t}) RETURN count(n)").get_next()[0] for t in ALL_NODE_TABLES)
    edges = g.execute("MATCH ()-[r]->() RETURN count(r)").get_next()[0]
    return nodes, edges


def _payload(target, kind="probe"):
    return {"intents": [{"kind": kind, "target_id": target, "rationale": "why"}]}


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


def test_F_in_scope_commit(g):  # §8 F
    res = run_once(g, MockDriver([_payload(HOST_IN)]), MockReviewer([OK]))
    fid = f"finding:agent-proposal:probe:{HOST_IN}"
    assert res.committed == (fid,)
    node = g.get_node("FINDING", fid)
    assert node["status"] == "hypothesis" and node["confidence"] == 0
    n = g.execute(
        "MATCH (a:HOST {id: $a})-[r:vulnerable_to]->(b:FINDING {id: $b}) RETURN count(r)", {"a": HOST_IN, "b": fid}
    ).get_next()[0]
    assert n == 1


def test_F_secret_derived_from(g):  # §8 F (SECRET branch)
    # SECRET ids match no scope shape family (scope_guard FORK-Y), so the by-id scope gate
    # fails closed for them; the edge shape is therefore exercised via _commit directly.
    from kronos.agent import Intent

    sid = "secret:abc123"
    g.upsert_node("SECRET", sid, {"value_ref": "sha256:x", "kind": "api_key", "status": "extracted", "source": "t"})
    fid = dispatcher._commit(g, Intent("probe", sid, "why"), ReviewVerdict(True, "SECRET", "hypothesis"))
    assert fid == f"finding:agent-proposal:probe:{sid}"
    n = g.execute(
        "MATCH (a:FINDING {id: $a})-[r:derived_from]->(b:SECRET {id: $b}) RETURN count(r)", {"a": fid, "b": sid}
    ).get_next()[0]
    assert n == 1


def test_G_out_of_scope_writes_nothing(g):  # §8 G
    before = _counts(g)
    res = run_once(g, MockDriver([_payload(HOST_OUT)]), MockReviewer([OK]))
    assert _counts(g) == before and res.committed == ()


def test_H_rejected_writes_nothing(g):  # §8 H
    before = _counts(g)
    res = run_once(g, MockDriver([_payload(HOST_IN)]), MockReviewer([ReviewVerdict(False, "HOST", "hypothesis")]))
    assert _counts(g) == before and res.committed == ()


@pytest.mark.parametrize("bad", [ReviewVerdict(True, "HOST", "reachable"), ReviewVerdict(True, "IDENTITY", "hypothesis")])
def test_I_hostile_verdict(g, bad):  # §8 I
    before = _counts(g)
    with pytest.raises(ReviewViolation):
        run_once(g, MockDriver([_payload(HOST_IN)]), MockReviewer([bad]))
    assert _counts(g) == before


def test_J_no_forbidden_columns():  # §8 J
    import inspect

    src = inspect.getsource(dispatcher._commit)
    for col in ("confidence", "in_scope", "merged_into", '"id"'):
        assert col not in src
    assert "advance_finding_status" not in src
    assert '"status": "hypothesis"' in src or "COMMIT_STATUS" in src


def test_K_backward_compat_zero_side_effects(g, nonet):  # §8 K
    before = _counts(g)
    r = run_once(g, MockDriver([_payload(HOST_IN)]))
    assert r.committed == () and _counts(g) == before
    rs = run(g, MockDriver([_payload(HOST_IN), {"complete": True}]), max_steps=3)
    assert all(x.committed == () for x in rs) and _counts(g) == before


def test_L_end_to_end(g, nonet):  # §8 L
    rev = MockReviewer([OK, OK])
    drv = MockDriver([_payload(HOST_IN, "a"), _payload(HOST_IN, "b"), {"complete": True}, _payload(HOST_IN, "never")])
    rs = run(g, drv, max_steps=5, reviewer=rev)
    assert len(rs) == 3 and rs[-1].complete
    assert [x.committed for x in rs] == [
        (f"finding:agent-proposal:a:{HOST_IN}",),
        (f"finding:agent-proposal:b:{HOST_IN}",),
        (),
    ]
    assert not nonet


def test_M_no_live_network(g, nonet):  # §8 M
    res = run_once(g, MockDriver([_payload(HOST_IN)]), MockReviewer([OK]))
    assert res.committed and not nonet  # no socket at all, hence none outside the CyberGym range


def test_N_scope_audit():  # §8 N
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{BRIEF_BASE}..HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert set(out) <= SECTION_3


def test_O_brief16_seal():  # §8 O
    src = (ROOT / "tests" / "test_agent_dispatcher.py").read_text()
    assert 'BRIEF_MERGE = "f4559a2"' in src
    assert 'f"{BRIEF_BASE}..{BRIEF_MERGE}"' in src
    assert 'f"{BRIEF_BASE}..HEAD"]' not in src  # bare string also appears in the brief-15 seal assertion (l.118), untouchable
