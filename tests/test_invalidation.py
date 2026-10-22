"""SPEC_BRIEF15 §8 criteria A-M (expected values derive from the brief's prose)."""

from __future__ import annotations

import re
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kronos.evidence import store_evidence
from kronos.graph import EngagementGraph
from kronos.lifecycle import (
    FINDING_TRANSITIONS,
    LifecycleError,
    advance_finding_status,
    advance_secret_status,
    derive_confidence,
)
from kronos.schema import EDGE_PAIRS
from kronos.validate.invalidation import invalidate_findings_for_dead_secret, record_secret_finding
from kronos.validate.runner import run_validation_pass
from kronos.validate.types import ValidationOutcome

ROOT = Path(__file__).parent.parent
BRIEF_BASE = "17d38a8"
SECTION_3 = {
    "SPEC_BRIEF15.md",
    "src/kronos/schema.py",
    "src/kronos/lifecycle.py",
    "src/kronos/validate/invalidation.py",
    "src/kronos/validate/runner.py",
    "tests/test_invalidation.py",
    "tests/test_web_validator.py",
}
URL = "http://localhost:8091"
CAND = SimpleNamespace(id=URL, type="API_ENDPOINT")


def _live() -> ValidationOutcome:
    return ValidationOutcome(
        live=True, evidence=b"proof", detail="200", classification="live_discriminated", discriminated=True
    )


def _dead() -> ValidationOutcome:
    return ValidationOutcome(live=False, evidence=b"", detail="401", classification="not_live", discriminated=False)


@pytest.fixture
def env(tmp_path, manifest_factory, signing_keypair, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    _, pub = signing_keypair
    g = EngagementGraph.init_engagement(
        tmp_path / "e.kz", manifest_factory(scope={"in_scope": [URL + "*"], "excluded": []}), pub
    )
    info = store_evidence(tmp_path, b"plain-bearer-token", kind="mobile_secret")
    sid = f"secret:{info['sha256'][:16]}"
    g.upsert_node("MOBILE_APP", "com.kronos.lab", {"bundle_id": "com.kronos.lab", "platform": "android", "source": "static"})
    g.upsert_node(
        "SECRET", sid,
        {"value_ref": "sha256:" + info["sha256"], "kind": "api_key", "status": "extracted", "source": "static"},
        scope_key="com.kronos.lab",
    )
    g.upsert_edge("leaks", "com.kronos.lab", "MOBILE_APP", sid, "SECRET")
    g.upsert_node("API_ENDPOINT", URL, {"source": "static"})
    g.upsert_edge("references", "com.kronos.lab", "MOBILE_APP", URL, "API_ENDPOINT")
    return SimpleNamespace(g=g, dir=tmp_path, sid=sid)


def _count(g, q, params=None):
    return g.execute(q, params or {}).get_next()[0]


def _make_secret_reachable(e):
    for s in ("validated", "reachable"):
        advance_secret_status(e.g, e.sid, s)


def _fid(e):
    return f"finding:secret-access:{e.sid}:{URL}"


def test_A_typed_causal_edge(env):
    assert EDGE_PAIRS["derived_from"] == [("FINDING", "SECRET")]
    _make_secret_reachable(env)
    record_secret_finding(env.g, env.sid, CAND, evidence=b"p", engagement_dir=env.dir)
    assert _count(env.g, "MATCH (:FINDING)-[r:derived_from]->(:SECRET) RETURN count(r)") == 1
    assert _count(env.g, "MATCH (:FINDING)-[r:references]->(:SECRET) RETURN count(r)") == 0


def test_B_producer(env):
    g = env.g
    fid = record_secret_finding(g, env.sid, CAND, evidence=b"p", engagement_dir=env.dir)
    assert fid == _fid(env)
    f = g.get_node("FINDING", fid)
    assert f["status"] == "reachable"
    assert f["confidence"] == 9
    assert _count(g, "MATCH (:API_ENDPOINT {id: $i})-[r:vulnerable_to]->(:FINDING {id: $f}) RETURN count(r)", {"i": URL, "f": fid}) == 1
    assert _count(g, "MATCH (:EVIDENCE)-[r:evidences]->(:FINDING {id: $f}) RETURN count(r)", {"f": fid}) == 1
    assert _count(g, "MATCH (:FINDING {id: $f})-[r:derived_from]->(:SECRET {id: $s}) RETURN count(r)", {"f": fid, "s": env.sid}) == 1


def test_C_runner_wiring(env):
    with patch("kronos.validate.http_validator.validate_api_token") as m:
        m.return_value = _live()
        run_validation_pass(env.g, str(env.dir))
    f = env.g.get_node("FINDING", _fid(env))
    assert f is not None and f["status"] == "reachable"
    assert _count(env.g, "MATCH (:FINDING)-[r:derived_from]->(:SECRET {id: $s}) RETURN count(r)", {"s": env.sid}) == 1


def test_C_abstention_creates_no_finding(env):
    with patch("kronos.validate.http_validator.validate_api_token") as m:
        m.return_value = _dead()
        run_validation_pass(env.g, str(env.dir))
    assert _count(env.g, "MATCH (f:FINDING) RETURN count(f)") == 0


def test_D_transitions_and_confidence(env):
    for s in ("reachable", "exploited", "reported"):
        assert "requires_revalidation" in FINDING_TRANSITIONS[s]
    assert FINDING_TRANSITIONS["requires_revalidation"] == {"reachable", "exploited", "discarded"}
    for ev in (True, False):
        assert derive_confidence("finding", "requires_revalidation", ev) == 3
    g = env.g
    fid = record_secret_finding(g, env.sid, CAND, evidence=b"p", engagement_dir=env.dir)
    # reachable/exploited/reported -> requires_revalidation, and out to each allowed target,
    # all through the chokepoint without raising.
    for start, path in (("reachable", []), ("exploited", ["exploited"]), ("reported", ["reported"])):
        for step in path:
            advance_finding_status(g, fid, step)
        assert g.get_node("FINDING", fid)["status"] == start
        advance_finding_status(g, fid, "requires_revalidation")
        advance_finding_status(g, fid, "reachable")
    for target in ("reachable", "exploited"):
        advance_finding_status(g, fid, "requires_revalidation")
        advance_finding_status(g, fid, target)
        if target == "exploited":
            advance_finding_status(g, fid, "requires_revalidation")
    # re-reporting directly from requires_revalidation is refused (report gate: must be exploited)
    with pytest.raises(LifecycleError):
        advance_finding_status(g, fid, "reported")
    # re-report path: requires_revalidation -> exploited -> reported
    advance_finding_status(g, fid, "exploited")
    advance_finding_status(g, fid, "reported")
    advance_finding_status(g, fid, "requires_revalidation")
    advance_finding_status(g, fid, "discarded")


def test_E_transitive_invalidation_preserves_history(env):
    g = env.g
    fid = record_secret_finding(g, env.sid, CAND, evidence=b"p", engagement_dir=env.dir)
    _make_secret_reachable(env)
    advance_secret_status(g, env.sid, "dead")
    ev_before = _count(g, "MATCH (e:EVIDENCE) RETURN count(e)")
    out = invalidate_findings_for_dead_secret(g, env.sid)
    assert out == [fid]
    f = g.get_node("FINDING", fid)
    assert f["status"] == "requires_revalidation" and f["confidence"] == 3
    assert _count(g, "MATCH (e:EVIDENCE) RETURN count(e)") == ev_before
    assert _count(g, "MATCH (:EVIDENCE)-[r:evidences]->(:FINDING {id: $f}) RETURN count(r)", {"f": fid}) == 1
    assert _count(g, "MATCH (:FINDING {id: $f})-[r:derived_from]->(:SECRET) RETURN count(r)", {"f": fid}) == 1
    assert invalidate_findings_for_dead_secret(g, env.sid) == []  # idempotent


def test_F_exploited_and_reported_invalidated(env):
    g = env.g
    fid = record_secret_finding(g, env.sid, CAND, evidence=b"p", engagement_dir=env.dir)
    _make_secret_reachable(env)
    advance_finding_status(g, fid, "exploited")
    advance_secret_status(g, env.sid, "dead")
    assert invalidate_findings_for_dead_secret(g, env.sid) == [fid]
    assert g.get_node("FINDING", fid)["status"] == "requires_revalidation"


def test_G_non_secret_finding_and_other_statuses_untouched(env):
    g = env.g
    g.upsert_node("FINDING", "finding:infra-x", {"source": "infra_validator", "title": "t", "severity": "info", "status": "hypothesis"})
    advance_finding_status(g, "finding:infra-x", "reachable")
    fid = record_secret_finding(g, env.sid, CAND, evidence=b"p", engagement_dir=env.dir)
    advance_finding_status(g, fid, "discarded")
    _make_secret_reachable(env)
    advance_secret_status(g, env.sid, "dead")
    assert invalidate_findings_for_dead_secret(g, env.sid) == []
    assert g.get_node("FINDING", "finding:infra-x")["status"] == "reachable"
    assert g.get_node("FINDING", fid)["status"] == "discarded"


def test_H_other_secrets_finding_untouched(env):
    g = env.g
    fid = record_secret_finding(g, env.sid, CAND, evidence=b"p", engagement_dir=env.dir)
    g.upsert_node("SECRET", "secret:other", {"value_ref": "sha256:x", "kind": "api_key", "status": "extracted", "source": "static"}, scope_key="com.kronos.lab")
    other = record_secret_finding(g, "secret:other", CAND, evidence=b"q", engagement_dir=env.dir)
    _make_secret_reachable(env)
    advance_secret_status(g, env.sid, "dead")
    assert invalidate_findings_for_dead_secret(g, env.sid) == [fid]
    assert g.get_node("FINDING", other)["status"] == "reachable"


def test_I_revalidation_reversible(env):
    g = env.g
    fid = record_secret_finding(g, env.sid, CAND, evidence=b"p", engagement_dir=env.dir)
    advance_finding_status(g, fid, "requires_revalidation")
    advance_finding_status(g, fid, "reachable")
    assert g.get_node("FINDING", fid)["status"] == "reachable"
    assert g.get_node("FINDING", fid)["confidence"] == 9


def test_J_no_network(env):
    fid = record_secret_finding(env.g, env.sid, CAND, evidence=b"p", engagement_dir=env.dir)
    _make_secret_reachable(env)
    advance_secret_status(env.g, env.sid, "dead")
    invalidate_findings_for_dead_secret(env.g, env.sid)  # sockets patched to raise in fixture
    assert env.g.get_node("FINDING", fid)["status"] == "requires_revalidation"


def test_K_scope_audit():
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{BRIEF_BASE}..HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert set(out) <= SECTION_3


def test_L_brief14_seal():
    src = (ROOT / "tests" / "test_web_validator.py").read_text()
    assert 'BRIEF_MERGE = "17d38a8"' in src
    assert 'f"{BRIEF_BASE}..{BRIEF_MERGE}"' in src


def test_M_no_forbidden_columns():
    src = (ROOT / "src" / "kronos" / "validate" / "invalidation.py").read_text()
    for call in re.findall(r"upsert_node\((.*?)\n    \)", src, re.S):
        for bad in ("confidence", "in_scope", "merged_into"):
            assert f'"{bad}"' not in call
    assert src.count('"status":') == 1  # set once, at create
    assert "advance_finding_status(" in src
    assert "import requests" not in src


def test_C_authenticated_not_authorized_creates_no_finding(env):
    out = ValidationOutcome(
        live=False, evidence=b"proof", detail="403", classification="authenticated_not_authorized", discriminated=True
    )
    with patch("kronos.validate.http_validator.validate_api_token") as m:
        m.return_value = out
        run_validation_pass(env.g, str(env.dir))
    assert _count(env.g, "MATCH (f:FINDING) RETURN count(f)") == 0


def test_H_revalidation_without_evidence_restores_confidence_7(env):
    g = env.g
    fid = record_secret_finding(g, env.sid, CAND)  # no evidence attached
    assert g.get_node("FINDING", fid)["confidence"] == 7
    advance_finding_status(g, fid, "requires_revalidation")
    assert g.get_node("FINDING", fid)["confidence"] == 3
    advance_finding_status(g, fid, "reachable")
    assert g.get_node("FINDING", fid)["confidence"] == 7


def test_I_double_invalidation_is_idempotent_on_graph(env):
    g = env.g
    record_secret_finding(g, env.sid, CAND, evidence=b"p", engagement_dir=env.dir)
    _make_secret_reachable(env)
    advance_secret_status(g, env.sid, "dead")
    invalidate_findings_for_dead_secret(g, env.sid)
    qs = [
        "MATCH (f:FINDING) RETURN count(f)",
        "MATCH ()-[r:vulnerable_to]->(:FINDING) RETURN count(r)",
        "MATCH ()-[r:derived_from]->() RETURN count(r)",
        "MATCH ()-[r:evidences]->(:FINDING) RETURN count(r)",
    ]
    before = [_count(g, q) for q in qs]
    assert before == [1, 1, 1, 1]
    assert invalidate_findings_for_dead_secret(g, env.sid) == []
    assert [_count(g, q) for q in qs] == before
