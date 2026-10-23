"""SPEC_BRIEF16 §8 criteria H-M (planner / dispatcher / scope). Expected values derive from the brief's prose."""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import pytest

from kronos.agent import (
    DispatcherResult,
    GraphSummary,
    MockDriver,
    plan,
    run,
    run_once,
    summarize,
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
