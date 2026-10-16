"""SPEC_BRIEF9 §8 test 9: the owned event stream — append-only,
parseable JSONL, the documented kinds with the right fields, no secret
value or raw tool output in any event, and an unwritable stream
degrades to a warning rather than failing the run.
"""

from __future__ import annotations

import json
import logging

import pytest

from kronos.events import ALLOWED_KINDS, emit


def _read_events(path):
    lines = (path / "events.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def test_emit_appends_parseable_jsonl(tmp_path):
    emit(tmp_path, "ingest_started", source_name="static", source_version="1")
    emit(tmp_path, "ingest_finished", source_name="static", node_count=3, edge_count=2, declined_count=0)
    records = _read_events(tmp_path)
    assert len(records) == 2
    assert records[0]["kind"] == "ingest_started"
    assert records[0]["source_name"] == "static"
    assert records[1]["kind"] == "ingest_finished"
    assert records[1]["node_count"] == 3


def test_emit_is_append_only_never_truncates(tmp_path):
    emit(tmp_path, "ingest_started", source_name="static", source_version="1")
    first = (tmp_path / "events.jsonl").read_text()
    emit(tmp_path, "ingest_finished", source_name="static", node_count=0, edge_count=0, declined_count=0)
    second = (tmp_path / "events.jsonl").read_text()
    assert second.startswith(first)
    assert len(second) > len(first)


def test_emit_every_record_has_kind_and_timestamp(tmp_path):
    for kind in ALLOWED_KINDS:
        emit(tmp_path, kind)
    records = _read_events(tmp_path)
    for record in records:
        assert record["kind"] in ALLOWED_KINDS
        assert record["timestamp"]  # non-empty ISO timestamp


def test_emit_reconcile_merged_carries_documented_fields(tmp_path):
    emit(tmp_path, "reconcile_merged", node_type="WEB_ENDPOINT", survivor_id="web:1", loser_ids=["web:2"])
    record = _read_events(tmp_path)[0]
    assert record["node_type"] == "WEB_ENDPOINT"
    assert record["survivor_id"] == "web:1"
    assert record["loser_ids"] == ["web:2"]


def test_emit_rejects_unknown_kind(tmp_path):
    with pytest.raises(ValueError):
        emit(tmp_path, "something_not_in_the_brief")
    assert not (tmp_path / "events.jsonl").exists()


def test_emit_never_contains_secret_values_or_raw_tool_output(tmp_path):
    """Mechanical, not just convention: the fields this codebase actually
    passes to `emit` are ids/counts/reasons (grep every call site), never
    a decoded secret value or raw tool output text."""
    import kronos

    root = __import__("pathlib").Path(kronos.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "emit(" in line and ("decoded_value" in line or "raw_value" in line or "secret_value" in line):
                offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert offenders == [], f"emit() called with a raw/secret-shaped field: {offenders}"


def test_emit_unwritable_stream_degrades_to_warning_not_a_crash(tmp_path, caplog):
    """An unwritable path (here: a file, not a directory, where
    `events.jsonl` would need to go) must never raise — observability
    is not allowed to break the engagement (contrast kronos.budget,
    which fails closed by design)."""
    not_a_directory = tmp_path / "not_a_dir"
    not_a_directory.write_text("x")  # a FILE at the path emit() will try to use as a directory

    with caplog.at_level(logging.WARNING, logger="kronos.events"):
        emit(not_a_directory, "ingest_started", source_name="static", source_version="1")  # must not raise

    assert any(rec.levelno == logging.WARNING for rec in caplog.records)


def test_emit_non_serializable_field_degrades_to_warning_not_a_crash(tmp_path):
    class Unserializable:
        pass

    emit(tmp_path, "ingest_started", source_name="static", weird=Unserializable())  # must not raise
    assert not (tmp_path / "events.jsonl").exists() or (tmp_path / "events.jsonl").read_text() == ""
