"""Hermetic tests for kronos.eval.cybergym_x_score (SPEC_BRIEF_R10_impl.md). No run()."""
import hashlib
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


CHAIN1 = "CYBERGYM_FIXTURE_CHAIN1_API_KEY_4d2f8a91"
SECRET = CHAIN2 = "CYBERGYMGENERALUSER0001:cybergym-fixture-general-secret-7f3a9c1e"
CHAIN3 = "CYBERGYMADMINUSER0001:cybergym-fixture-admin-secret-b82d4f60"
NEEDLES = [CHAIN1, CHAIN2, CHAIN3]


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


@pytest.mark.parametrize("value", NEEDLES)
def test_assert_redacted_positive_control_secret(tmp_path, value):
    (tmp_path / "leak.txt").write_text(f"blob: {value}\n")
    with pytest.raises(ValueError, match="redaction violation"):
        m.assert_redacted(tmp_path, NEEDLES)


def test_assert_redacted_positive_control_header(tmp_path):
    (tmp_path / "leak.txt").write_text("X-Cybergym-Key: abc\n")
    with pytest.raises(ValueError, match="redaction violation"):
        m.assert_redacted(tmp_path, NEEDLES)


def _fixture_export(tmp_path):
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


def test_redacted_export_passes_gate_and_excludes_raw(tmp_path):
    committed = _fixture_export(tmp_path)
    m.assert_redacted(committed, NEEDLES)
    assert sorted(p.name for p in committed.iterdir()) == [
        "budget_ledger.json", "evidence_manifest.json", "run_summary.json", "teardown_report.json",
    ]
    assert not (committed / "evidence").exists()
    assert not (committed / "pipeline_stdout.txt").exists()
