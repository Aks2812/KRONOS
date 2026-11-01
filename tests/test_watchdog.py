"""SPEC_BRIEF30 §12 C6-C8 (watchdog). Expected values derive from the brief's prose
and the manifest validator (1 <= confirm_window_seconds <= 300 when may_auto_stop)."""

from __future__ import annotations

import socket

import pytest

from kronos.manifest import load_and_verify
from kronos.stop import is_stopped, request_stop
from kronos.watchdog import Watchdog

W = 30
BUDGET = {
    "validation_attempts": 5, "tool_invocations": 10, "wall_clock_seconds": 60.0,
    "llm_tokens": 1000, "llm_cost_usd": 1.5,
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


@pytest.fixture
def verified(manifest_factory, signing_keypair):
    _, pub = signing_keypair

    def _v(watchdog):
        a = {"mode_max": "calm", "unattended_authorizations": [], "max_unattended_duration_seconds": 600,
             "max_unattended_budget": dict(BUDGET)}
        if watchdog is not None:
            a["watchdog"] = watchdog
        return load_and_verify(manifest_factory(autonomy=a), pub)

    return _v


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


HOLDS = {"on": True}


def _cond(events):
    return HOLDS["on"]


@pytest.fixture(autouse=True)
def _reset():
    HOLDS["on"] = True


def _wd(verified, tmp_path, wd, clock):
    return Watchdog(verified(wd), tmp_path, _cond, clock)


@pytest.mark.parametrize("policy", [None, {"may_auto_stop": False}])
def test_B30_C7_alert_only(verified, tmp_path, nonet, policy):  # §12 C7
    clock = Clock()
    w = _wd(verified, tmp_path, policy, clock)
    for t in (0, 1, W, W + 1, 10_000):
        clock.t = t
        assert w.poll() == "alert"
    assert is_stopped(tmp_path) is None


def test_B30_C7_no_autonomy_block(manifest_factory, signing_keypair, tmp_path):
    _, pub = signing_keypair
    v = load_and_verify(manifest_factory(), pub)
    clock = Clock()
    assert Watchdog(v, tmp_path, _cond, clock).poll() == "alert"
    clock.t = 10_000
    assert is_stopped(tmp_path) is None


@pytest.mark.parametrize(
    "elapsed,stops", [(W - 1, False), (W, True), (W + 1, True)]
)
def test_B30_C8_boundaries(verified, tmp_path, nonet, elapsed, stops):  # §12 C8
    clock = Clock()
    w = _wd(verified, tmp_path, {"may_auto_stop": True, "confirm_window_seconds": W}, clock)
    assert w.poll() == "grace" and is_stopped(tmp_path) is None
    clock.t = elapsed
    w.poll()
    state = is_stopped(tmp_path)
    assert (state is not None) is stops
    if stops:
        assert state.source == "watchdog"


def test_B30_C8_cleared_mid_window_stands_down(verified, tmp_path, nonet):  # §12 C8
    clock = Clock()
    w = _wd(verified, tmp_path, {"may_auto_stop": True, "confirm_window_seconds": W}, clock)
    assert w.poll() == "grace"
    clock.t = W // 2
    HOLDS["on"] = False
    assert w.poll() == "stood_down"
    clock.t = W + 1
    HOLDS["on"] = True  # re-fires: a fresh grace window must start, not resume
    assert w.poll() == "grace"
    assert is_stopped(tmp_path) is None
    clock.t = W + 1 + W
    assert w.poll() == "stopped"


def test_B30_C8_operator_stop_preempts(verified, tmp_path, nonet):  # §12 C8 first-wins
    clock = Clock()
    w = _wd(verified, tmp_path, {"may_auto_stop": True, "confirm_window_seconds": W}, clock)
    w.poll()
    request_stop(tmp_path, "operator", "halt")
    clock.t = W + 5
    w.poll()
    assert is_stopped(tmp_path).source == "operator"
    assert len((tmp_path / "stop.jsonl").read_text().splitlines()) == 1


def test_B30_C6_read_only(verified, tmp_path, nonet):  # §12 C6
    (tmp_path / "events.jsonl").write_text('{"kind": "ingest_started"}\n')
    before = (tmp_path / "events.jsonl").read_bytes()
    clock = Clock()
    w = _wd(verified, tmp_path, {"may_auto_stop": True, "confirm_window_seconds": W}, clock)
    w.poll()
    clock.t = W
    w.poll()
    assert (tmp_path / "events.jsonl").read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["events.jsonl", "stop.jsonl"]
    assert is_stopped(tmp_path).source == "watchdog"
    assert not nonet


def test_B30_condition_sees_events(verified, tmp_path):
    (tmp_path / "events.jsonl").write_text('{"kind": "ingest_declined"}\n')
    seen = []
    Watchdog(verified(None), tmp_path, lambda ev: seen.append(ev) or False, Clock()).poll()
    assert seen == [[{"kind": "ingest_declined"}]]


def test_B30_F6_events_torn_trailing_line(verified, tmp_path, nonet):  # §4.1 tolerate growing file
    (tmp_path / "events.jsonl").write_text('{"kind": "a"}\n{"kind": "b')
    seen = []
    Watchdog(verified(None), tmp_path, lambda ev: seen.append(ev) or False, Clock()).poll()
    assert seen == [[{"kind": "a"}]]
    assert not nonet
