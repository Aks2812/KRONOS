"""SPEC_BRIEF22 §8 criteria A-G, K, F2. Expected values derive from the brief's §2 prose."""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import pytest

from kronos.agent import ExecutionOutcome, Intent, LiveExecutor
from kronos.evidence import store_evidence
from kronos.validate.types import ValidationOutcome

ROOT = Path(__file__).parent.parent
BRIEF_BASE = "1405ed7"
SECTION_3 = {
    "SPEC_BRIEF22.md",
    "src/kronos/agent/live_executor.py",
    "src/kronos/agent/__init__.py",
    "tests/test_agent_live_executor.py",
}
API_VALUE = "plain-bearer-token"  # no ":" -> api_token
CLOUD_VALUE = "AKIAIOSFODNN7EXAMPLE:wJalrXUtnFEMI"  # long left + right -> cloud_credential_pair
IN_EP = "https://api.acme.example.com"
OUT_EP = "https://evil.example.org"
BUCKET = "bucket.acme.example.com"
PROXY = "http://localhost:4566"
EVID = b"request/response proof"


def _live(evidence: bytes = EVID, detail: str = "live detail") -> ValidationOutcome:
    return ValidationOutcome(live=True, evidence=evidence, detail=detail,
                             classification="live_discriminated", discriminated=True)


def _dead(detail: str = "401") -> ValidationOutcome:
    return ValidationOutcome(live=False, evidence=b"", detail=detail,
                             classification="not_live", discriminated=False)


@pytest.fixture
def engagement_graph(tmp_path, manifest_factory, signing_keypair):
    from kronos.graph import EngagementGraph

    _, pub = signing_keypair
    manifest = manifest_factory(scope={"in_scope": ["*.acme.example.com", "arn:aws:s3:::*"], "excluded": []})
    return EngagementGraph.init_engagement(tmp_path / "e.kz", manifest, pub)


@pytest.fixture
def nonet(monkeypatch):
    used = []

    def _boom(*a, **k):
        used.append(1)
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    return used


@pytest.fixture
def calls(monkeypatch):
    """Spy validators; `result` holds the outcome both return."""
    box = {"api": [], "cloud": [], "result": _dead()}

    def api(value, target, **hint):
        box["api"].append((value, target, hint))
        return box["result"]

    def cloud(value, target, proxy):
        box["cloud"].append((value, target, proxy))
        return box["result"]

    monkeypatch.setattr("kronos.validate.http_validator.validate_api_token", api)
    monkeypatch.setattr("kronos.validate.cloud_validator.validate_cloud_credential", cloud)
    return box


def _seed(g, tmp_path, value: str, *, endpoint=IN_EP, bucket=None, ref=None) -> str:
    info = store_evidence(tmp_path, value.encode(), kind="mobile_secret")
    sid = "secret:s1"
    g.upsert_node("MOBILE_APP", "com.kronos.lab", {"bundle_id": "com.kronos.lab", "platform": "android", "source": "t"})
    g.upsert_node("SECRET", sid, {"value_ref": ref or "sha256:" + info["sha256"], "kind": "api_key",
                                  "status": "extracted", "source": "t"}, scope_key="com.kronos.lab")
    g.upsert_edge("leaks", "com.kronos.lab", "MOBILE_APP", sid, "SECRET")
    if endpoint:
        g.upsert_node("API_ENDPOINT", endpoint, {"source": "t"})
        g.upsert_edge("references", "com.kronos.lab", "MOBILE_APP", endpoint, "API_ENDPOINT")
    if bucket:
        g.upsert_node("CLOUD_RESOURCE", bucket, {"resource_type": "s3_bucket", "provider": "aws", "source": "t"},
                       scope_key=f"arn:aws:s3:::{bucket}")
    return sid


def _validate(sid):
    return Intent(kind="validate", target_id=sid, rationale="r")


def test_A_api_live(engagement_graph, tmp_path, calls, nonet):  # §8 A
    sid = _seed(engagement_graph, tmp_path, API_VALUE)
    calls["result"] = _live()
    ex = LiveExecutor(engagement_graph, tmp_path)
    assert ex.execute(_validate(sid)) == ExecutionOutcome(True, EVID, "live detail")
    assert calls["api"] == [(API_VALUE, IN_EP, {})] and not calls["cloud"] and not nonet


def test_A_http_hints_forwarded(engagement_graph, tmp_path, calls, nonet):  # §2 step 5
    sid = _seed(engagement_graph, tmp_path, API_VALUE)
    calls["result"] = _live()
    LiveExecutor(engagement_graph, tmp_path, http_hints={IN_EP: {"k": "v"}}).execute(_validate(sid))
    assert calls["api"] == [(API_VALUE, IN_EP, {"k": "v"})]


def test_B_cloud_live(engagement_graph, tmp_path, calls, nonet):  # §8 B
    sid = _seed(engagement_graph, tmp_path, CLOUD_VALUE, bucket=BUCKET)
    calls["result"] = _live()
    out = LiveExecutor(engagement_graph, tmp_path, cloud_proxy_endpoint=PROXY).execute(_validate(sid))
    assert out == ExecutionOutcome(True, EVID, "live detail")
    assert calls["cloud"] == [(CLOUD_VALUE, BUCKET, PROXY)] and not calls["api"] and not nonet


def test_B_cloud_skipped_without_proxy(engagement_graph, tmp_path, calls, nonet):  # §2 D3
    sid = _seed(engagement_graph, tmp_path, CLOUD_VALUE, bucket=BUCKET)
    out = LiveExecutor(engagement_graph, tmp_path).execute(_validate(sid))
    assert out.succeeded is False and out.evidence is None
    assert not calls["cloud"] and not calls["api"]


def test_C_not_live(engagement_graph, tmp_path, calls, nonet):  # §8 C
    sid = _seed(engagement_graph, tmp_path, API_VALUE)
    calls["result"] = _dead("401")
    out = LiveExecutor(engagement_graph, tmp_path).execute(_validate(sid))
    assert out.succeeded is False and out.evidence is None and out.detail == "401"
    assert len(calls["api"]) == 1 and not nonet


def test_D_unrecognized_kind(engagement_graph, tmp_path, calls, nonet):  # §8 D
    sid = _seed(engagement_graph, tmp_path, API_VALUE)
    out = LiveExecutor(engagement_graph, tmp_path).execute(Intent(kind="probe", target_id=sid, rationale="r"))
    assert out == ExecutionOutcome(False, None, "unhandled intent kind: probe")
    assert not calls["api"] and not calls["cloud"] and not nonet


def test_E_out_of_scope(engagement_graph, tmp_path, calls, nonet):  # §8 E
    sid = _seed(engagement_graph, tmp_path, API_VALUE, endpoint=OUT_EP)
    assert engagement_graph.get_node("API_ENDPOINT", OUT_EP)["in_scope"] is False  # precondition
    out = LiveExecutor(engagement_graph, tmp_path).execute(_validate(sid))
    assert out.succeeded is False and out.evidence is None
    assert not calls["api"] and not calls["cloud"] and not nonet


def test_F_missing_blob(engagement_graph, tmp_path, calls, nonet):  # §8 F
    sid = _seed(engagement_graph, tmp_path, API_VALUE, ref="sha256:" + "0" * 64)
    out = LiveExecutor(engagement_graph, tmp_path).execute(_validate(sid))
    assert out.succeeded is False and out.evidence is None
    assert not calls["api"] and not calls["cloud"]


def test_F_non_utf8_blob(engagement_graph, tmp_path, calls, nonet):  # §2 step 3
    info = store_evidence(tmp_path, b"\xff\xfe\x80", kind="mobile_secret")
    sid = _seed(engagement_graph, tmp_path, API_VALUE, ref="sha256:" + info["sha256"])
    out = LiveExecutor(engagement_graph, tmp_path).execute(_validate(sid))
    assert out.succeeded is False and out.evidence is None and not calls["api"]


def test_F_absent_secret(engagement_graph, tmp_path, calls, nonet):  # §2 step 2
    out = LiveExecutor(engagement_graph, tmp_path).execute(_validate("secret:nope"))
    assert out.succeeded is False and out.evidence is None and not calls["api"]


@pytest.mark.parametrize("live,evidence,detail", [(True, b"proof", "d1"), (False, b"", "d2"), (False, b"x", "d3")])
def test_G_mapping_exact(engagement_graph, tmp_path, calls, nonet, live, evidence, detail):  # §8 G
    sid = _seed(engagement_graph, tmp_path, API_VALUE)
    if live:
        calls["result"] = _live(evidence, detail)
    else:
        calls["result"] = ValidationOutcome(live=False, evidence=evidence, detail=detail)
    out = LiveExecutor(engagement_graph, tmp_path).execute(_validate(sid))
    assert out.succeeded is live
    assert out.evidence == (evidence or None)
    assert out.detail == detail


def test_G_first_live_wins(engagement_graph, tmp_path, monkeypatch, nonet):  # §2 D3
    sid = _seed(engagement_graph, tmp_path, API_VALUE)
    engagement_graph.upsert_node("API_ENDPOINT", "https://b.acme.example.com", {"source": "t"})
    engagement_graph.upsert_edge("references", "com.kronos.lab", "MOBILE_APP", "https://b.acme.example.com", "API_ENDPOINT")
    seen = []

    def api(value, target, **hint):
        seen.append(target)
        return _dead() if len(seen) == 1 else _live()

    monkeypatch.setattr("kronos.validate.http_validator.validate_api_token", api)
    out = LiveExecutor(engagement_graph, tmp_path).execute(_validate(sid))
    assert out.succeeded is True and out.evidence == EVID and len(seen) == 2


def test_K_no_network_on_all_paths(engagement_graph, tmp_path, calls, nonet):  # §8 K
    sid = _seed(engagement_graph, tmp_path, API_VALUE)
    ex = LiveExecutor(engagement_graph, tmp_path)
    ex.execute(_validate(sid))
    ex.execute(Intent(kind="probe", target_id=sid, rationale="r"))
    ex.execute(_validate("secret:nope"))
    assert not nonet


def test_F2_scope_audit_whole_window():  # §8 F2
    out = subprocess.run(["git", "diff", "--name-only", f"{BRIEF_BASE}..HEAD"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    assert set(out) <= SECTION_3, set(out) - SECTION_3
