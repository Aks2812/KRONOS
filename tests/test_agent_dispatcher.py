"""SPEC_BRIEF16 §8 criteria H-M (planner / dispatcher / scope). Expected values derive from the brief's prose."""

from __future__ import annotations

import dataclasses
import socket
import subprocess
from pathlib import Path

import pytest

from kronos.agent import (
    DispatcherResult,
    GraphSummary,
    MockDriver,
    ReviewVerdict,
    RunSummary,
    plan,
    run,
    run_once,
    summarize,
    summarize_run,
)
from kronos.schema import ALL_NODE_TABLES

ROOT = Path(__file__).parent.parent
BRIEF_BASE = "81796b4"
BRIEF_MERGE = "f4559a2"  # brief 16 merged to main (PR #24 squash); seals this audit to brief 16's footprint
SECTION_3 = {
    "SPEC_BRIEF16.md",
    "src/kronos/agent/__init__.py",
    "src/kronos/agent/contracts.py",
    "src/kronos/agent/drivers.py",
    "src/kronos/agent/planner.py",
    "src/kronos/agent/dispatcher.py",
    "tests/test_agent_contracts.py",
    "tests/test_agent_dispatcher.py",
    "tests/test_invalidation.py",
}
INTENT = {"kind": "k", "target_id": "t", "rationale": "r"}


def _counts(g):
    nodes = sum(g.execute(f"MATCH (n:{t}) RETURN count(n)").get_next()[0] for t in ALL_NODE_TABLES)
    edges = g.execute("MATCH ()-[r]->() RETURN count(r)").get_next()[0]
    return nodes, edges


@pytest.fixture
def g(engagement_graph):
    g = engagement_graph
    for i, st in enumerate(["reachable", "reachable", "requires_revalidation"]):
        g.upsert_node("FINDING", f"finding:t{i}", {"source": "t", "status": st})
    for i in range(2):
        g.upsert_node("SECRET", f"secret:t{i}", {"value_ref": "sha256:x", "kind": "api_key", "status": "extracted", "source": "t"})
    return g


def test_H_read_only_planner(g):  # §8 H
    before = _counts(g)
    s = summarize(g)
    assert isinstance(s, GraphSummary)
    assert s.finding_count == 3 and s.secret_count == 2
    assert dict(s.findings_by_status) == {"reachable": 2, "requires_revalidation": 1}
    assert _counts(g) == before


def test_plan_validates_driver_output(g):
    r = plan(summarize(g), MockDriver([{"intents": [INTENT]}]))
    assert r.complete is False and len(r.intents) == 1


def test_I_zero_side_effects(g):  # §8 I
    before = _counts(g)
    drv = MockDriver([{"intents": [INTENT]}, {"intents": [INTENT, INTENT]}, {"complete": True}])
    res = run(g, drv, max_steps=5)
    assert res[-1].complete is True and len(res) == 3
    assert all(isinstance(r, DispatcherResult) for r in res)
    assert _counts(g) == before
    with pytest.raises(RuntimeError):  # all 3 scripted calls consumed, no extra LLM call
        drv.reason(None)


def test_run_once_result(g):
    r = run_once(g, MockDriver([{"intents": [INTENT]}]))
    assert r.complete is False and len(r.proposed_intents) == 1


def test_J_termination(g):  # §8 J
    res = run(g, MockDriver([{"intents": [INTENT]}, {"complete": True}, {"intents": [INTENT]}]), max_steps=10)
    assert len(res) == 2 and res[-1].complete
    res = run(g, MockDriver([{"intents": [INTENT]}] * 4), max_steps=4)
    assert len(res) == 4 and not any(r.complete for r in res)
    for bad in (0, -1):
        with pytest.raises(ValueError):
            run(g, MockDriver([{"complete": True}]), max_steps=bad)


def test_K_no_network(g, monkeypatch):  # §8 K
    used = []

    def _boom(*a, **k):
        used.append(1)
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    res = run(g, MockDriver([{"intents": [INTENT]}, {"complete": True}]), max_steps=3)
    assert res[-1].complete and not used  # no traffic at all, hence none outside the CyberGym range


def test_L_scope_audit():  # §8 L
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{BRIEF_BASE}..{BRIEF_MERGE}"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert set(out) <= SECTION_3


def test_M_brief15_seal():  # §8 M
    src = (ROOT / "tests" / "test_invalidation.py").read_text()
    assert 'BRIEF_MERGE = "81796b4"' in src
    assert 'f"{BRIEF_BASE}..{BRIEF_MERGE}"' in src
    assert 'f"{BRIEF_BASE}..HEAD"' not in src


def _fake_clock(step=1.0):
    t = [-step]

    def clock():
        t[0] += step
        return t[0]

    return clock


def test_N_conclude_on_timeout(g):  # §8 N
    # timeout fires: clock advances 1.0 per call, deadline 2.5, driver never completes
    res = run(g, MockDriver([{"intents": [INTENT]}] * 50), max_steps=50, deadline=2.5, clock=_fake_clock())
    last = res[-1]
    assert last.timed_out is True and last.complete is False
    assert last.committed == () and last.promoted == ()
    assert len(res) < 50
    assert not any(r.timed_out for r in res[:-1])
    # no premature timeout: completes before deadline
    res = run(g, MockDriver([{"intents": [INTENT]}, {"complete": True}]), max_steps=10, deadline=1000.0, clock=_fake_clock())
    assert res[-1].complete is True and res[-1].timed_out is False
    # backward compat: deadline=None
    res = run(g, MockDriver([{"intents": [INTENT]}, {"complete": True}, {"intents": [INTENT]}]), max_steps=10)
    assert len(res) == 2 and res[-1].complete and not any(r.timed_out for r in res)
    # deadline <= 0 rejected
    for bad in (0, -1.0):
        with pytest.raises(ValueError):
            run(g, MockDriver([{"complete": True}]), max_steps=3, deadline=bad)


def test_O_run_summary(g):  # §8 O
    def dr(steps, complete=False, timed_out=False, committed=(), promoted=()):
        return DispatcherResult(
            complete=complete, proposed_intents=(), steps=steps,
            committed=committed, promoted=promoted, timed_out=timed_out,
        )

    # conclusion precedence (§2): timed_out, then complete, else max_steps
    assert summarize_run([dr(1), dr(1, complete=True)]).conclusion == "complete"
    assert summarize_run([dr(1), dr(0, timed_out=True)]).conclusion == "timed_out"
    assert summarize_run([dr(1, complete=True, timed_out=True)]).conclusion == "timed_out"
    assert summarize_run([dr(1), dr(1)]).conclusion == "max_steps"
    # total_steps exact sum, including a steps=0 timeout result; aggregates in list order
    inp = [
        dr(1, committed=("a", "b"), promoted=("a",)),
        dr(3, committed=("c",), promoted=("c", "b")),
        dr(0, timed_out=True),
    ]
    s = summarize_run(inp)
    assert s.total_steps == 4
    assert s.committed == ("a", "b", "c")
    assert s.promoted == ("a", "c", "b")
    assert s.results == tuple(inp)
    # frozen
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.total_steps = 0
    assert isinstance(s, RunSummary)
    # composition with run()
    res = run(g, MockDriver([{"complete": True}]), max_steps=3)
    cs = summarize_run(res)
    assert cs.conclusion == "complete"
    assert cs.total_steps == sum(r.steps for r in res)


# ---- SPEC_BRIEF24 §8 (dependency DAG: any_of / blocked_by). Expected values from brief §2 prose. ----
B24_BASE = "73cbe8b"
SECTION_3_B24 = {
    "SPEC_BRIEF24.md",
    "src/kronos/agent/contracts.py",
    "src/kronos/agent/dispatcher.py",
    "tests/test_agent_dispatcher.py",
    "tests/test_agent_contracts.py",
}
H_X, H_Y, H_Z, H_W = (f"{n}.acme.example.com" for n in ("x", "y", "z", "w"))
_OK = ReviewVerdict(approved=True, target_type="HOST", status="hypothesis")
_NO = ReviewVerdict(approved=False, target_type="HOST", status="hypothesis")


def _key(host):
    return f"probe:{host}"


def _fid(host):
    return f"finding:agent-proposal:probe:{host}"


def _it(host, **deps):
    d = {"kind": "probe", "target_id": host, "rationale": "r"}
    d.update(deps)
    return d


@pytest.fixture
def g24(g):
    for h in (H_X, H_Y, H_Z, H_W):
        g.upsert_node("HOST", h, {"source": "t"})
    return g


@pytest.fixture
def nonet(monkeypatch):
    used = []

    def _boom(*a, **k):
        used.append(1)
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    return used


def _run24(g, intents, verdicts):
    from kronos.agent import MockReviewer

    return run_once(g, MockDriver([{"intents": intents}]), MockReviewer(verdicts))


def test_P_A_blocked_by_satisfied(g24, nonet):  # §8 A
    res = _run24(g24, [_it(H_X), _it(H_Y, blocked_by=[_key(H_X)])], [_OK, _OK])
    assert res.committed == (_fid(H_X), _fid(H_Y)) and res.withheld == () and not nonet


def test_P_B_blocked_by_unsatisfied(g24):  # §8 B (rejected, then out of scope)
    res = _run24(g24, [_it(H_X), _it(H_Y, blocked_by=[_key(H_X)])], [_NO, _OK])
    assert res.committed == () and res.withheld == (_key(H_Y),)
    g24.upsert_node("HOST", "evil.other.example.org", {"source": "t"})
    res = _run24(
        g24,
        [_it("evil.other.example.org"), _it(H_Y, blocked_by=[_key("evil.other.example.org")])],
        [_OK, _OK],
    )
    assert res.committed == () and res.withheld == (_key(H_Y),)


def test_P_C_any_of(g24):  # §8 C
    z = _it(H_Z, any_of=[_key(H_X), _key(H_W)])
    res = _run24(g24, [_it(H_X), _it(H_W), z], [_NO, _OK, _OK])
    assert res.committed == (_fid(H_W), _fid(H_Z)) and res.withheld == ()
    res = _run24(g24, [_it(H_X), _it(H_W), z], [_NO, _NO, _OK])
    assert res.committed == () and res.withheld == (_key(H_Z),)
    # eligible but itself rejected: not withheld, just not committed
    res = _run24(g24, [_it(H_X), _it(H_W), z], [_OK, _NO, _NO])
    assert res.committed == (_fid(H_X),) and res.withheld == ()


def test_P_D_transitive_withholding(g24):  # §8 D
    res = _run24(
        g24,
        [_it(H_X), _it(H_Y, blocked_by=[_key(H_X)]), _it(H_Z, blocked_by=[_key(H_Y)])],
        [_NO, _OK, _OK],
    )
    assert res.committed == () and res.withheld == (_key(H_Y), _key(H_Z))


@pytest.mark.parametrize(
    "intents",
    [
        [_it(H_X), _it(H_Y, blocked_by=["nope:0"])],  # E unknown ref
        [_it(H_X), _it(H_Y, any_of=["nope:0"])],  # E unknown ref via any_of
        [_it(H_X, blocked_by=[_key(H_Y)]), _it(H_Y, blocked_by=[_key(H_X)])],  # F cycle
        [_it(H_X, blocked_by=[_key(H_X)])],  # F self-reference
        [_it(H_X), _it(H_X), _it(H_Y, blocked_by=[_key(H_X)])],  # G duplicate key with deps
    ],
)
def test_P_EFG_fail_closed_no_writes(g24, intents):  # §8 E, F, G
    from kronos.agent import ContractViolation, MockReviewer

    before = _counts(g24)
    assert before[0] > 0  # non-vacuity
    with pytest.raises(ContractViolation):
        run_once(g24, MockDriver([{"intents": intents}]), MockReviewer([_OK] * 4))
    assert _counts(g24) == before


def test_P_H_topo_order(g24):  # §8 H
    # verdicts are consumed in list order (phase 1): Y first, then X
    res = _run24(g24, [_it(H_Y, blocked_by=[_key(H_X)]), _it(H_X)], [_OK, _OK])
    assert res.committed == (_fid(H_X), _fid(H_Y)) and res.withheld == ()


def test_P_I_backward_compat_golden(g24):  # §8 I
    from kronos.agent import MockReviewer

    res = run_once(g24, MockDriver([{"intents": [_it(H_Y), _it(H_X), _it(H_Y)]}]), MockReviewer([_OK, _NO, _OK]))
    # pre-change behaviour: list order, duplicates allowed, rejected skipped
    assert res.committed == (_fid(H_Y), _fid(H_Y)) and res.promoted == () and res.withheld == ()


def test_P_L2_scope_audit_b24():  # §8 L2
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{B24_BASE}..HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert set(out) <= SECTION_3_B24
