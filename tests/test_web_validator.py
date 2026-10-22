"""SPEC_BRIEF14 §8 criteria A-L (expected values derive from the brief's prose)."""

from __future__ import annotations

import json
import re
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from kronos.graph import EngagementGraph
from kronos.ingest.contract import apply_plan
from kronos.ingest.web.parser import ingest_web_openapi_plan
from kronos.validate.controls import ArmResult, run_differential
from kronos.validate.types import ValidationOutcome
from kronos.validate.web_validator import (
    CONTROL_PATH,
    run_web_validation_pass,
    validate_web_endpoint_reachable,
)

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "web" / "cybergym_openapi.json"
BRIEF_BASE = "33ab362"
SECTION_3 = {
    "SPEC_BRIEF14.md",
    "src/kronos/validate/web_validator.py",
    "tests/test_web_validator.py",
    "tests/test_web_ingest.py",
}
IN_SCOPE_IDS = [
    "web:GET:http://127.0.0.1:8091/health",
    "web:GET:http://127.0.0.1:8091/items/{item_id}",
]
OUT_OF_SCOPE_ID = "web:GET:http://10.0.0.1:8091/health"
REAL_PATHS = {"/health", "/items/{item_id}"}


@pytest.fixture
def g(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    manifest = manifest_factory(scope={"in_scope": ["127.0.0.1*"], "excluded": []})
    graph = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest, pub)
    apply_plan(graph, ingest_web_openapi_plan(FIXTURE.read_text(), graph))
    oos = json.loads(FIXTURE.read_text())
    oos["servers"] = [{"url": "http://10.0.0.1:8091"}]
    apply_plan(graph, ingest_web_openapi_plan(json.dumps(oos), graph))
    return graph


def _arm(label, success, status=None, transport_error=False):
    return ArmResult(label=label, success=success, status_code=status, transport_error=transport_error)


def _probe(control_ok=False, canonical_ok=True, calls=None):
    def probe(url, method):
        if calls is not None:
            calls.append((url, method))
        ok = control_ok if urlsplit(url).path == CONTROL_PATH else canonical_ok
        return ArmResult(label="probe", success=ok, status_code=200 if ok else 404)

    return probe


def _count(g, q):
    return g.execute(q).get_next()[0]


def test_A_differential_kind_http():
    r = run_differential([_arm("A_canonical", True), _arm("B_negative_control", False)], kind="http")
    assert r.classification == "live_discriminated" and r.live is True and r.discriminated is True
    r = run_differential([_arm("A_canonical", True), _arm("B_negative_control", True)], kind="http")
    assert r.classification == "indiscriminate_target" and r.live is False
    r = run_differential([_arm("A_canonical", False), _arm("B_negative_control", False)], kind="http")
    assert r.classification == "not_live" and r.live is False


def test_B_outcome_invariant():
    live = validate_web_endpoint_reachable(_arm("A_canonical", True, 200), _arm("B_negative_control", False, 404))
    assert isinstance(live, ValidationOutcome)
    assert live.live and live.discriminated and live.classification == "live_discriminated"
    for a, b in [(True, True), (False, False), (False, True)]:
        o = validate_web_endpoint_reachable(_arm("A_canonical", a), _arm("B_negative_control", b))
        assert isinstance(o, ValidationOutcome) and o.live is False
    inc = validate_web_endpoint_reachable(
        _arm("A_canonical", False, transport_error=True), _arm("B_negative_control", False, transport_error=True)
    )
    assert inc.classification == "inconclusive" and inc.live is False


def test_C_in_scope_only(g):
    calls = []
    run_web_validation_pass(g, probe=_probe(calls=calls))
    assert calls
    assert {urlsplit(u).hostname for u, _ in calls} == {"127.0.0.1"}
    assert not any("10.0.0.1" in u for u, _ in calls)


def test_D_finding_on_live(g):
    run_web_validation_pass(g, probe=_probe())
    for eid in IN_SCOPE_IDS:
        fid = f"finding:web-reachable:{eid}"
        f = g.get_node("FINDING", fid)
        assert f is not None
        assert f["status"] == "reachable" and f["confidence"] == 7
        res = g.execute(
            "MATCH (w:WEB_ENDPOINT {id: $w})-[r:vulnerable_to]->(f:FINDING {id: $f}) RETURN count(r)",
            {"w": eid, "f": fid},
        )
        assert res.get_next()[0] == 1
    assert g.get_node("FINDING", f"finding:web-reachable:{OUT_OF_SCOPE_ID}") is None


@pytest.mark.parametrize(
    "canonical_ok,control_ok",
    [
        (False, False),  # canonical fails -> not_live
        (True, True),  # control also succeeds -> indiscriminate
    ],
)
def test_E_abstention(g, canonical_ok, control_ok):
    run_web_validation_pass(g, probe=_probe(control_ok=control_ok, canonical_ok=canonical_ok))
    assert _count(g, "MATCH (f:FINDING) RETURN count(f)") == 0
    assert _count(g, "MATCH ()-[r:vulnerable_to]->() RETURN count(r)") == 0


def test_E_abstention_inconclusive(g):
    def probe(url, method):
        return ArmResult(label="probe", success=False, transport_error=True)

    run_web_validation_pass(g, probe=probe)
    assert _count(g, "MATCH (f:FINDING) RETURN count(f)") == 0
    assert _count(g, "MATCH ()-[r:vulnerable_to]->() RETURN count(r)") == 0


def test_F_no_leak():
    o = validate_web_endpoint_reachable(_arm("A_canonical", True, 200), _arm("B_negative_control", False, 404))
    text = (o.evidence.decode() + " " + o.detail + " " + o.control_outcome).lower()
    assert "a_canonical" in text and "b_negative_control" in text
    for bad in ("password", "secret", "token", "authorization", "bearer"):
        assert bad not in text
    assert o.evidence


def test_G_no_live_network(g, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("socket used")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    calls = []
    run_web_validation_pass(g, probe=_probe(calls=calls))
    assert calls
    assert g.get_node("FINDING", f"finding:web-reachable:{IN_SCOPE_IDS[0]}") is not None


def test_H_control_same_origin_different_path(g):
    calls = []
    run_web_validation_pass(g, probe=_probe(calls=calls))
    assert len(calls) % 2 == 0
    for (cu, _), (ku, _) in zip(calls[0::2], calls[1::2]):
        c, k = urlsplit(cu), urlsplit(ku)
        assert (c.scheme, c.netloc) == (k.scheme, k.netloc)
        assert k.path != c.path
        assert k.path == CONTROL_PATH
        assert k.path not in REAL_PATHS


def test_I_idempotent(g):
    probe = _probe()
    run_web_validation_pass(g, probe=probe)
    run_web_validation_pass(g, probe=probe)
    assert _count(g, "MATCH (f:FINDING) RETURN count(f)") == 2
    assert _count(g, "MATCH ()-[r:vulnerable_to]->() RETURN count(r)") == 2
    assert g.get_node("FINDING", f"finding:web-reachable:{IN_SCOPE_IDS[0]}")["status"] == "reachable"


def test_J_scope_audit():
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{BRIEF_BASE}..HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert set(out) <= SECTION_3


def test_K_no_forbidden_columns():
    src = (ROOT / "src" / "kronos" / "validate" / "web_validator.py").read_text()
    for call in re.findall(r"upsert_node\((.*?)\n    \)", src, re.S):
        for bad in ("confidence", "in_scope", "merged_into"):
            assert f'"{bad}"' not in call
    assert src.count('"status":') == 1  # set once, at create
    assert "import requests" not in src


def test_L_brief13_seal():
    src = (ROOT / "tests" / "test_web_ingest.py").read_text()
    assert 'BRIEF_MERGE = "33ab362"' in src
    assert 'f"{BRIEF_BASE}..{BRIEF_MERGE}"' in src
    assert 'f"{BRIEF_BASE}..HEAD"' not in src
