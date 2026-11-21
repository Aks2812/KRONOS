"""Hermetic tests for kronos.eval.cybergym_x_score (SPEC_BRIEF_R10_impl.md). No run()."""
import filecmp
import hashlib
import inspect
import json
from datetime import datetime, timezone

import jsonschema
import pytest

from kronos.eval import cybergym_x_score as m

CHAINS = [
    {"id": f"chain-{i}", "discovered": True, "validated_end_to_end": True,
     "finding_id": None, "verdict_tier": None, "control_disposition": None}
    for i in (1, 2, 3)
]


def _summary(tmp_path, stdout="X-SCORE: 3/3 chains validated end-to-end", all_ok=True):
    (tmp_path / "budget_ledger.json").write_text(json.dumps({"stopped_reason": None}))
    (tmp_path / "teardown_report.json").write_text(json.dumps({"all_ok": all_ok, "items": []}))
    return m.assemble_run_summary(
        run_id="r", engagement_dir=tmp_path, exit_code=0, stdout_text=stdout, chains=CHAINS,
        manifest_id="sha256:abc", started_at="2026-11-20T12:00:00Z",
        ended_at="2026-11-20T12:05:00Z", kronos_commit="d8607ad",
    )


def test_run_id_for():
    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    assert m.run_id_for(now) == "cybergym-x-score-v1_20261120T120000Z"


def test_parse_x_score():
    assert m.parse_x_score("X-SCORE: 3/3 chains validated end-to-end") == 3
    assert m.parse_x_score("noise\nX-SCORE: 2/3 chains validated end-to-end\n") == 2
    assert m.parse_x_score("X-SCORE: incomplete — run stopped early by budget enforcement") is None


def test_assemble_valid(tmp_path):
    s = _summary(tmp_path)
    m.validate_run_summary(s)
    assert s["x_score"] == 3


def test_assemble_incomplete_raises(tmp_path):
    with pytest.raises(ValueError):
        _summary(tmp_path, stdout="X-SCORE: incomplete — stopped")


def test_assemble_teardown_not_ok_raises(tmp_path):
    with pytest.raises(ValueError):
        _summary(tmp_path, all_ok=False)


def test_validate_rejects_missing_field(tmp_path):
    s = _summary(tmp_path)
    del s["kronos_commit"]
    with pytest.raises(jsonschema.ValidationError):
        m.validate_run_summary(s)


def test_validate_rejects_wrong_instrument(tmp_path):
    s = _summary(tmp_path)
    s["instrument"] = "other"
    with pytest.raises(jsonschema.ValidationError):
        m.validate_run_summary(s)


def test_validate_rejects_teardown_not_ok(tmp_path):
    s = _summary(tmp_path)
    s["teardown"]["all_ok"] = False
    with pytest.raises(jsonschema.ValidationError):
        m.validate_run_summary(s)


def test_import_has_no_side_effects():
    assert callable(m.run) and m.SCHEMA_PATH.is_file()


@pytest.fixture(scope="module")
def needles():
    return m._fixture_needles()  # bound to live fixtures; called once


def test_build_evidence_manifest(tmp_path):
    ev = tmp_path / "evidence"
    ev.mkdir()
    blobs = [b"alpha-bytes", b"beta-longer-bytes"]
    shas = [hashlib.sha256(b).hexdigest() for b in blobs]
    for sha, b in zip(shas, blobs):
        (ev / sha).write_bytes(b)
    out = m.build_evidence_manifest(ev, {shas[0]: "secret_reveal"})
    expected = sorted(
        [
            {"sha256": shas[0], "kind": "secret_reveal", "size": len(blobs[0])},
            {"sha256": shas[1], "kind": "unreferenced", "size": len(blobs[1])},
        ],
        key=lambda e: e["sha256"],
    )
    assert out == expected
    assert all(set(e) == {"sha256", "kind", "size"} for e in out)


def test_build_evidence_manifest_missing_dir(tmp_path):
    assert m.build_evidence_manifest(tmp_path / "nope", {}) == []


@pytest.mark.parametrize("idx", [0, 1, 2])
def test_assert_redacted_positive_control_secret(tmp_path, needles, idx):
    (tmp_path / "leak.txt").write_text(f"blob: {needles[idx]}\n")
    with pytest.raises(ValueError, match="redaction violation"):
        m.assert_redacted(tmp_path, needles)


def test_assert_redacted_positive_control_header(tmp_path, needles):
    (tmp_path / "leak.txt").write_text("X-Cybergym-Key: abc\n")
    with pytest.raises(ValueError, match="redaction violation"):
        m.assert_redacted(tmp_path, needles)


def _fixture_export(tmp_path, needles):
    SECRET = needles[1]
    work = tmp_path / "work"
    (work / "evidence").mkdir(parents=True)
    raw = f"GET / HTTP/1.1\nX-Cybergym-Key: {SECRET}\n".encode()
    sha = hashlib.sha256(raw).hexdigest()
    (work / "evidence" / sha).write_bytes(raw)
    (work / "pipeline_stdout.txt").write_text(f"leak {SECRET}\n")
    s = _summary(work)
    s["chains"] = [dict(c, finding_id=f"f{i}", verdict_tier="confirmed") for i, c in enumerate(CHAINS)]
    manifest = m.build_evidence_manifest(work / "evidence", {sha: "validation_request"})
    committed = tmp_path / "committed"
    committed.mkdir()
    m.export_redacted(work, committed, s, manifest)
    return committed


def test_redacted_export_passes_gate_and_excludes_raw(tmp_path, needles):
    committed = _fixture_export(tmp_path, needles)
    m.assert_redacted(committed, needles)
    assert sorted(p.name for p in committed.iterdir()) == [
        "budget_ledger.json", "evidence_manifest.json", "run_summary.json", "teardown_report.json",
    ]
    assert not (committed / "evidence").exists()
    assert not (committed / "pipeline_stdout.txt").exists()


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def has_next(self):
        return bool(self._rows)

    def get_next(self):
        return self._rows.pop(0)


def test_collect_state_finding_persistence(tmp_path, monkeypatch):
    from cybergym import kronos_validation_run as kvr

    strings_xml = (kvr.HERE / "mobile" / "apk_src" / "res" / "values" / "strings.xml").read_text()
    chain3 = (kvr.HERE / "mobile" / "apk_src" / "assets" / "cfg.dat").read_text() + kvr._extract_resource(
        strings_xml, "kronos_chain3_secret_part2"
    )
    sid1 = kvr._secret_node_id(kvr.CHAIN1_SECRET_VALUE)
    sid2 = kvr._secret_node_id(kvr.CHAIN2_SECRET_VALUE)
    sid3 = kvr._secret_node_id(chain3)
    sha_a, sha_b = "a" * 64, "b" * 64

    class StubGraph:
        def get_node(self, type_, sid):
            return {sid1: {"status": "reachable"}, sid2: {"status": "extracted"}}.get(sid)

        def execute(self, query, params=None):
            if "FINDING" in query:
                if params and params["sid"] == sid1:
                    return _Rows([["finding:chain1", "tier-A", "bypassed"]])
                return _Rows([])
            if "EVIDENCE" in query:
                return _Rows([[sha_a, "mobile_secret_reconstructed"], [sha_b, "extraction_proof"]])
            return _Rows([])

    monkeypatch.setattr(kvr, "_load_manifest_and_graph", lambda d: StubGraph())
    monkeypatch.setattr(kvr, "_survivor_of", lambda g, sid: sid)

    chains, manifest_id, kinds = m._collect_state(tmp_path)
    assert chains[0] == {
        "id": "chain-1", "discovered": True, "validated_end_to_end": True,
        "finding_id": "finding:chain1", "verdict_tier": "tier-A", "control_disposition": "bypassed",
    }
    assert chains[1] == {
        "id": "chain-2", "discovered": True, "validated_end_to_end": False,
        "finding_id": None, "verdict_tier": None, "control_disposition": None,
    }
    assert chains[2] == {
        "id": "chain-3", "discovered": False, "validated_end_to_end": False,
        "finding_id": None, "verdict_tier": None, "control_disposition": None,
    }
    assert kinds == {sha_a: "mobile_secret_reconstructed", sha_b: "extraction_proof"}
    assert isinstance(manifest_id, str) and manifest_id.startswith("sha256:") and len(manifest_id) > len("sha256:")


def test_xscore_neutral():
    for n in range(4):
        assert m.parse_x_score(f"X-SCORE: {n}/3 chains validated end-to-end") == n
    assert m.parse_x_score("X-SCORE: incomplete \u2014 run stopped early by budget enforcement") is None


def test_assemble_semantics_golden(tmp_path):
    budget = {"limits": {"max_requests": 100}, "totals": {"requests": 7}, "stopped_reason": None}
    teardown = {"all_ok": True, "items": []}
    (tmp_path / "budget_ledger.json").write_text(json.dumps(budget))
    (tmp_path / "teardown_report.json").write_text(json.dumps(teardown))
    chains = [
        {"id": "chain-1", "discovered": True, "validated_end_to_end": True,
         "finding_id": "f1", "verdict_tier": "tier-A", "control_disposition": "bypassed"},
        {"id": "chain-2", "discovered": True, "validated_end_to_end": True,
         "finding_id": None, "verdict_tier": None, "control_disposition": None},
        {"id": "chain-3", "discovered": False, "validated_end_to_end": False,
         "finding_id": None, "verdict_tier": None, "control_disposition": None},
    ]
    out = m.assemble_run_summary(
        run_id="rid", engagement_dir=tmp_path, exit_code=0,
        stdout_text="X-SCORE: 2/3 chains validated end-to-end", chains=chains,
        manifest_id="sha256:deadbeef", started_at="2026-11-20T12:00:00Z",
        ended_at="2026-11-20T12:05:00Z", kronos_commit="abc1234",
    )
    assert out == {
        "run_id": "rid",
        "instrument": "cybergym-x-score-v1",
        "k": 3,
        "x_score": 2,
        "manifest_id": "sha256:deadbeef",
        "manifest_engagement_id": m.MANIFEST_ENGAGEMENT_ID,
        "lab": m.LAB,
        "chains": chains,
        "started_at": "2026-11-20T12:00:00Z",
        "ended_at": "2026-11-20T12:05:00Z",
        "kronos_commit": "abc1234",
        "budget": budget,
        "teardown": teardown,
    }


def test_evidence_manifest_lossless(tmp_path):
    ev = tmp_path / "evidence"
    ev.mkdir()
    blobs = [b"one", b"two-two", b"three-three-three"]
    shas = [hashlib.sha256(b).hexdigest() for b in blobs]
    for sha, b in zip(shas, blobs):
        (ev / sha).write_bytes(b)
    out = m.build_evidence_manifest(ev, {shas[0]: "extraction_proof"})
    assert {e["sha256"] for e in out} == {p.name for p in ev.iterdir()} == set(shas)
    assert len(out) == len(blobs)
    size_by_sha = dict(zip(shas, (len(b) for b in blobs)))
    for e in out:
        assert e["size"] == size_by_sha[e["sha256"]]
        assert set(e) == {"sha256", "kind", "size"}
        assert e["kind"] == ("extraction_proof" if e["sha256"] == shas[0] else "unreferenced")
    assert [e["sha256"] for e in out] == sorted(shas)


def test_committed_set_differential(tmp_path):
    work = tmp_path / "work"
    (work / "evidence").mkdir(parents=True)
    (work / "evidence" / "ab").write_bytes(b"blob")
    (work / "pipeline_stdout.txt").write_text("stdout\n")
    (work / "budget_ledger.json").write_text(json.dumps({"stopped_reason": None, "totals": {"n": 1}}, indent=1))
    (work / "teardown_report.json").write_text(json.dumps({"all_ok": True, "items": []}, indent=3))
    committed = tmp_path / "committed"
    committed.mkdir()
    m.export_redacted(work, committed, {"x": 1}, [{"sha256": "ab", "kind": "unreferenced", "size": 4}])
    assert {p.name for p in committed.iterdir()} == {
        "run_summary.json", "budget_ledger.json", "teardown_report.json", "evidence_manifest.json",
    }
    assert not (committed / "evidence").exists()
    assert not (committed / "pipeline_stdout.txt").exists()
    for name in ("budget_ledger.json", "teardown_report.json"):
        assert filecmp.cmp(work / name, committed / name, shallow=False)


def test_pipeline_reuse_neutral():
    assert not hasattr(m, "_assert_enrichment_did_not_shortcut_anyone")
    src = inspect.getsource(m.run)
    assert "from cybergym.kronos_validation_run import _run_pipeline" in src
    assert "_run_pipeline(" in src
    assert "def _assert_enrichment_did_not_shortcut_anyone" not in inspect.getsource(m)


def test_needles_bound_to_live_fixtures():
    assert m._fixture_needles() == [
        "CYBERGYM_FIXTURE_CHAIN1_API_KEY_4d2f8a91",
        "CYBERGYMGENERALUSER0001:cybergym-fixture-general-secret-7f3a9c1e",
        "CYBERGYMADMINUSER0001:cybergym-fixture-admin-secret-b82d4f60",
    ]


# ---- egress guard replaces the internal:true override (injection removed) ----
from pathlib import Path  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]


def test_override_injection_removed():
    assert not hasattr(m, "OVERRIDE_PATH")
    assert not hasattr(m, "_compose_file_args")
    assert not (_ROOT / "src/kronos/eval/cybergym_internal_net.override.yml").exists()


def test_run_uses_direct_compose_and_egress_guard():
    src = inspect.getsource(m.run)
    assert 'compose("up", "-d", "--build")' in src
    assert "compose(*cfg" not in src
    assert "compose_down(compose)" in src
    assert "apply_egress_guard" in src
    assert "egress_guard_teardown" in src
    assert 'registry.register(\n                    "firewall"' in src or 'registry.register("firewall"' in src
    assert 'discover_subnet("cybergym_default")' in src


def test_run_registers_firewall_before_apply_and_before_wait():
    src = inspect.getsource(m.run)
    assert src.index('"firewall"') < src.index("apply_egress_guard(subnet)") < src.index("wait_for_services()")
    assert src.index("compose_down(compose)") < src.index('"firewall"')
