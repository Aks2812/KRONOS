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
BRIEF_MERGE = "056f441"  # brief 22 merged to main (PR #30 squash); seals this audit to brief 22's footprint
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
    out = subprocess.run(["git", "diff", "--name-only", f"{BRIEF_BASE}..{BRIEF_MERGE}"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    assert set(out) <= SECTION_3, set(out) - SECTION_3


# ---------------------------------------------------------------------------
# SPEC_BRIEF25 §8 A-K. Expected values derive from SPEC_BRIEF25 §2 D1-D4 prose.
# ---------------------------------------------------------------------------
B25_BASE = "98636e5"
B25_MERGE = "4ff38f4"
SECTION_3_B25 = {
    "SPEC_BRIEF25.md",
    "src/kronos/agent/live_executor.py",
    "tests/test_agent_live_executor.py",
    "tests/test_agent_dispatcher.py",
}
SVC_IN = "127.0.0.1:4566/tcp"
SVC_OUT = "10.0.0.1:22/tcp"
WEB_IN = "http://127.0.0.1:8091/api/items"
WEB_OUT = "http://10.0.0.1:8091/api/items"


@pytest.fixture
def lab_graph(tmp_path, manifest_factory, signing_keypair):
    from kronos.graph import EngagementGraph

    _, pub = signing_keypair
    manifest = manifest_factory(scope={"in_scope": ["127.0.0.1*"], "excluded": []})
    return EngagementGraph.init_engagement(tmp_path / "lab.kz", manifest, pub)


def _count_q(g, q):
    return g.execute(q).get_next()[0]


def _findings(g):
    return _count_q(g, "MATCH (f:FINDING) RETURN count(f)")


def _svc(g, sid=SVC_IN, port=4566):
    g.upsert_node("SERVICE", sid, {"port": port, "protocol": "tcp", "source": "t"})


def _web(g, url=WEB_IN, method="GET"):
    from urllib.parse import urlsplit

    g.upsert_node("WEB_ENDPOINT", url, {"url": url, "method": method, "source": "t"}, scope_key=urlsplit(url).hostname)


def _arm25(success):
    from kronos.validate.controls import ArmResult

    return ArmResult(label="probe", success=success, status_code=200 if success else 404)


def _svc_probe(live=True, calls=None):
    from kronos.validate.infra_validator import CONTROL_PORT

    def probe(host, port):
        if calls is not None:
            calls.append((host, port))
        if live:
            return _arm25(port != CONTROL_PORT)
        return _arm25(True)  # canonical and control indistinguishable

    return probe


def _web_probe(live=True, calls=None):
    from urllib.parse import urlsplit

    from kronos.validate.web_validator import CONTROL_PATH

    def probe(url, method):
        if calls is not None:
            calls.append((url, method))
        if live:
            return _arm25(urlsplit(url).path != CONTROL_PATH)
        return _arm25(True)

    return probe


def _pi(kind, target):
    return Intent(kind=kind, target_id=target, rationale="r")


def test_B25_A_probe_service_live(lab_graph, tmp_path, nonet):  # §8 A (D2)
    from kronos.validate.infra_validator import CONTROL_PORT

    _svc(lab_graph)
    calls = []
    before = _findings(lab_graph)
    out = LiveExecutor(lab_graph, tmp_path, service_probe=_svc_probe(True, calls)).execute(_pi("probe_service", SVC_IN))
    fid = f"finding:infra-reachable:{SVC_IN}"
    assert out.succeeded is True and out.detail == fid
    assert calls == [("127.0.0.1", 4566), ("127.0.0.1", CONTROL_PORT)]
    assert _findings(lab_graph) == before + 1
    assert _count_q(lab_graph, f"MATCH (s:SERVICE {{id: '{SVC_IN}'}})-[r:vulnerable_to]->(f:FINDING {{id: '{fid}'}}) RETURN count(r)") == 1
    assert not nonet


def test_B25_B_probe_service_abstain(lab_graph, tmp_path, nonet):  # §8 B (D2)
    _svc(lab_graph)
    assert lab_graph.get_node("SERVICE", SVC_IN)
    before = _findings(lab_graph)
    out = LiveExecutor(lab_graph, tmp_path, service_probe=_svc_probe(False)).execute(_pi("probe_service", SVC_IN))
    assert out.succeeded is False and out.detail == "abstained"
    assert _findings(lab_graph) == before
    assert not nonet


def test_B25_C_probe_service_out_of_scope(lab_graph, tmp_path, nonet):  # §8 C (D2 scope gate)
    _svc(lab_graph, SVC_OUT, 22)
    assert lab_graph.get_node("SERVICE", SVC_OUT)["in_scope"] is False
    calls = []
    before = _findings(lab_graph)
    out = LiveExecutor(lab_graph, tmp_path, service_probe=_svc_probe(True, calls)).execute(_pi("probe_service", SVC_OUT))
    assert out.succeeded is False and out.detail.startswith("SERVICE out of scope:")
    assert calls == [] and _findings(lab_graph) == before
    assert not nonet


def test_B25_D_probe_service_missing(lab_graph, tmp_path, nonet):  # §8 D (D2)
    calls = []
    out = LiveExecutor(lab_graph, tmp_path, service_probe=_svc_probe(True, calls)).execute(_pi("probe_service", "nope:1/tcp"))
    assert out.succeeded is False and out.detail == "no SERVICE node: nope:1/tcp"
    assert calls == [] and not nonet


def test_B25_E_probe_service_unconfigured(lab_graph, tmp_path, nonet):  # §8 E (D2)
    _svc(lab_graph)
    out = LiveExecutor(lab_graph, tmp_path, service_probe=None).execute(_pi("probe_service", SVC_IN))
    assert out.succeeded is False and out.detail == "no service probe configured"
    assert not nonet


def test_B25_F_probe_web_live(lab_graph, tmp_path, nonet):  # §8 F (D3)
    from kronos.validate.web_validator import CONTROL_PATH

    _web(lab_graph)
    calls = []
    before = _findings(lab_graph)
    out = LiveExecutor(lab_graph, tmp_path, web_probe=_web_probe(True, calls)).execute(_pi("probe_web", WEB_IN))
    fid = f"finding:web-reachable:{WEB_IN}"
    assert out.succeeded is True and out.detail == fid
    assert calls == [(WEB_IN, "GET"), (f"http://127.0.0.1:8091{CONTROL_PATH}", "GET")]
    assert _findings(lab_graph) == before + 1
    assert _count_q(lab_graph, f"MATCH (w:WEB_ENDPOINT {{id: '{WEB_IN}'}})-[r:vulnerable_to]->(f:FINDING {{id: '{fid}'}}) RETURN count(r)") == 1
    assert not nonet


def test_B25_F_probe_web_abstain(lab_graph, tmp_path, nonet):  # §8 F (D3)
    _web(lab_graph)
    assert lab_graph.get_node("WEB_ENDPOINT", WEB_IN)
    before = _findings(lab_graph)
    out = LiveExecutor(lab_graph, tmp_path, web_probe=_web_probe(False)).execute(_pi("probe_web", WEB_IN))
    assert out.succeeded is False and out.detail == "abstained"
    assert _findings(lab_graph) == before
    assert not nonet


def test_B25_F_probe_web_out_of_scope(lab_graph, tmp_path, nonet):  # §8 F (D3)
    _web(lab_graph, WEB_OUT)
    assert lab_graph.get_node("WEB_ENDPOINT", WEB_OUT)["in_scope"] is False
    calls = []
    before = _findings(lab_graph)
    out = LiveExecutor(lab_graph, tmp_path, web_probe=_web_probe(True, calls)).execute(_pi("probe_web", WEB_OUT))
    assert out.succeeded is False and out.detail.startswith("WEB_ENDPOINT out of scope:")
    assert calls == [] and _findings(lab_graph) == before
    assert not nonet


def test_B25_F_probe_web_missing(lab_graph, tmp_path, nonet):  # §8 F (D3)
    calls = []
    out = LiveExecutor(lab_graph, tmp_path, web_probe=_web_probe(True, calls)).execute(_pi("probe_web", "http://127.0.0.1/none"))
    assert out.succeeded is False and out.detail == "no WEB_ENDPOINT node: http://127.0.0.1/none"
    assert calls == [] and not nonet


def test_B25_F_probe_web_unconfigured(lab_graph, tmp_path, nonet):  # §8 F (D3)
    _web(lab_graph)
    out = LiveExecutor(lab_graph, tmp_path, web_probe=None).execute(_pi("probe_web", WEB_IN))
    assert out.succeeded is False and out.detail == "no web probe configured"
    assert not nonet


def test_B25_G_validate_unchanged(lab_graph, tmp_path, nonet):  # §8 G (D4)
    out = LiveExecutor(lab_graph, tmp_path, service_probe=_svc_probe(True)).execute(_pi("validate", "secret:nope"))
    assert out.succeeded is False and out.detail == "no SECRET node: secret:nope"
    assert not nonet


def test_B25_H_unknown_kind_unchanged(lab_graph, tmp_path, nonet):  # §8 H (D4)
    out = LiveExecutor(lab_graph, tmp_path).execute(_pi("frobnicate", SVC_IN))
    assert out.succeeded is False and out.detail == "unhandled intent kind: frobnicate"
    assert not nonet


def test_B25_I_no_network_all_paths(lab_graph, tmp_path, nonet):  # §8 I
    _svc(lab_graph)
    _web(lab_graph)
    ex = LiveExecutor(lab_graph, tmp_path, service_probe=_svc_probe(True), web_probe=_web_probe(True))
    for kind, tgt in [("probe_service", SVC_IN), ("probe_web", WEB_IN), ("probe_service", "x:1/tcp"),
                      ("probe_web", "http://x"), ("validate", "secret:nope"), ("zzz", "t")]:
        ex.execute(_pi(kind, tgt))
    assert not nonet


def test_B25_J_scope_audit_whole_window():  # §8 J
    out = subprocess.run(["git", "diff", "--name-only", f"{B25_BASE}..{B25_MERGE}"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    assert set(out) <= SECTION_3_B25, set(out) - SECTION_3_B25
