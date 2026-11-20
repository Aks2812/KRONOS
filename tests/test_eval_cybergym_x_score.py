"""Hermetic tests for kronos.eval.cybergym_x_score (SPEC_BRIEF_R10_impl.md). No run()."""
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
