"""SPEC_BRIEF30 §12 C1-C3 (stop primitive) + C10 + brief-30 whole-window scope audit.
Expected values derive from the brief's prose."""

from __future__ import annotations

import os
import re
import socket
import sys
import subprocess
from pathlib import Path

import pytest

from kronos.stop import Stopped, StopState, is_stopped, raise_if_stopped, request_stop

ROOT = Path(__file__).parent.parent
B30_BASE = "93fb05e"
B30_SECTION_10 = {
    "SPEC_BRIEF30.md",
    "src/kronos/stop.py",
    "src/kronos/watchdog.py",
    "tests/test_stop.py",
    "tests/test_watchdog.py",
    "src/kronos/agent/dispatcher.py",
    "tests/test_agent_dispatcher.py",
    "tests/test_autonomy.py",
    "src/kronos/__init__.py",
}


@pytest.fixture
def nonet(monkeypatch):
    used = []

    def _boom(*a, **k):
        used.append(1)
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    return used


def test_B30_not_stopped_without_record(tmp_path, nonet):  # §4.1 present/non-empty => stopped
    assert is_stopped(tmp_path) is None
    (tmp_path / "stop.jsonl").write_text("")
    assert is_stopped(tmp_path) is None
    raise_if_stopped(tmp_path)
    assert not nonet


def test_B30_F6_torn_trailing_line_tolerated(tmp_path, nonet):  # §4.1 concurrently-growing file
    request_stop(tmp_path, "operator", "first")
    with open(tmp_path / "stop.jsonl", "a", encoding="utf-8") as f:
        f.write('{"source": "watch')  # torn partial trailing line
    assert is_stopped(tmp_path) == StopState("operator", "first")
    assert not nonet


def test_B30_N1_torn_first_line_fails_closed(tmp_path, nonet):  # §4.1 non-empty unparsable first line => stopped
    (tmp_path / "stop.jsonl").write_text('{"source": "oper')
    assert is_stopped(tmp_path) == StopState("unknown", "unparsable stop record")
    request_stop(tmp_path, "watchdog", "later")  # concatenates onto the fragment
    assert is_stopped(tmp_path) == StopState("unknown", "unparsable stop record")
    with pytest.raises(Stopped):
        raise_if_stopped(tmp_path)
    assert not nonet


def test_B30_N3_whitespace_first_line_fails_closed(tmp_path, nonet):  # §4.1 non-empty first line => stopped
    (tmp_path / "stop.jsonl").write_text("   \n")
    assert is_stopped(tmp_path) == StopState("unknown", "unparsable stop record")
    assert not nonet


def test_B30_N3_empty_or_missing_not_stopped(tmp_path, nonet):  # §4.1 no first line => not stopped
    assert is_stopped(tmp_path) is None
    (tmp_path / "stop.jsonl").write_text("")
    assert is_stopped(tmp_path) is None
    assert not nonet


def test_B30_C2_first_wins_and_audit(tmp_path, nonet):  # §12 C2
    request_stop(tmp_path, "operator", "first")
    request_stop(tmp_path, "watchdog", "second")
    assert is_stopped(tmp_path) == StopState("operator", "first")
    lines = (tmp_path / "stop.jsonl").read_text().splitlines()
    assert len(lines) == 2 and '"second"' in lines[1]
    with pytest.raises(Stopped) as ei:
        raise_if_stopped(tmp_path)
    assert (ei.value.source, ei.value.reason) == ("operator", "first")
    assert not nonet


def test_B30_C2b_cross_process(tmp_path, nonet):  # §12 C2b: no shared memory, only the file
    writer = tmp_path / "e"
    writer.mkdir()
    request_stop(writer, "budget", "wall_clock_seconds")
    reader = Path(str(writer))  # independent handle on the same directory
    assert reader is not writer
    assert is_stopped(reader) == StopState("budget", "wall_clock_seconds")
    code = (
        "import sys; from kronos.stop import is_stopped; s = is_stopped(sys.argv[1]); print(s.source, s.reason)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, str(writer)], capture_output=True, text=True, check=True, cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    ).stdout.split()
    assert out == ["budget", "wall_clock_seconds"]


def test_B30_source_enum(tmp_path, nonet):  # §4.1 StopSource in {operator, watchdog, budget, deadline}
    for s in ("operator", "watchdog", "budget", "deadline"):
        request_stop(tmp_path, s, "r")
    with pytest.raises(ValueError):
        request_stop(tmp_path, "other", "r")
    assert not nonet


def test_B30_no_concurrency_primitives(nonet):  # §4.1 no os.replace/tempfile/flock/threads
    src = (ROOT / "src/kronos/stop.py").read_text()
    for banned in ("os.replace", "tempfile", "flock", "fcntl", "threading", "asyncio"):
        assert banned not in src
    assert not nonet


def test_B30_C1_single_stop_entry(nonet):  # §12 C1 / A5
    diff = subprocess.run(
        ["git", "diff", "-U0", f"{B30_BASE}..a229b0d", "--", "src/kronos"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    added = re.findall(r"^\+\s*def (stop|cancel|kill|abort|halt|shutdown)\b", diff, re.M)
    assert added == []
    assert not nonet


def test_B30_Q_scope_audit(nonet):  # brief-30 whole window
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{B30_BASE}..a229b0d"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert set(out) <= B30_SECTION_10, set(out) - B30_SECTION_10
    assert not nonet
