"""SPEC_BRIEF23 §8 criteria A-E, K, F2. Expected values derive from the brief's §2 prose (D1-D4)."""

from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

import pytest

from kronos.agent import ContractViolation, GraphSummary, Intent, LiveDriver, ReasonResult, validate_reason_payload

ROOT = Path(__file__).parent.parent
BRIEF_BASE = "056f441"
BRIEF_MERGE = "73cbe8b"
SECTION_3 = {
    "SPEC_BRIEF23.md",
    "src/kronos/agent/live_driver.py",
    "src/kronos/agent/__init__.py",
    "tests/test_agent_live_driver.py",
    "tests/test_agent_live_executor.py",
}
SUMMARY = GraphSummary(finding_count=7, secret_count=13, findings_by_status=(("open", 5), ("closed", 2)))


def _intent(i: int) -> dict:
    return {"kind": "probe", "target_id": f"secret:{i}", "rationale": f"r{i}"}


def _fake(text: str):
    seen: list[str] = []

    def client(prompt: str) -> str:
        seen.append(prompt)
        return text

    client.seen = seen
    return client


@pytest.fixture
def nonet(monkeypatch):
    used = []

    def _boom(*a, **k):
        used.append(1)
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    return used


def test_A_contract_valid_intents(nonet):  # §8 A
    payload = {"complete": False, "intents": [_intent(1), _intent(2)]}
    out = LiveDriver(_fake(json.dumps(payload))).reason(SUMMARY)
    assert out == payload
    assert validate_reason_payload(out) == ReasonResult(
        complete=False, intents=(Intent("probe", "secret:1", "r1"), Intent("probe", "secret:2", "r2")))
    assert not nonet


def test_B_fenced_json(nonet):  # §8 B
    payload = {"complete": False, "intents": [_intent(1)]}
    text = f"Sure, here you go:\n```json\n{json.dumps(payload, indent=2)}\n```\nHope that helps."
    out = LiveDriver(_fake(text)).reason(SUMMARY)
    assert out == payload
    assert validate_reason_payload(out).intents == (Intent("probe", "secret:1", "r1"),)
    assert not nonet


def test_C_complete_payload(nonet):  # §8 C
    out = LiveDriver(_fake('{"complete": true, "intents": []}')).reason(SUMMARY)
    assert out == {"complete": True, "intents": []}
    assert validate_reason_payload(out) == ReasonResult(complete=True, intents=())
    assert not nonet


def test_D_no_json_raises(nonet):  # §8 D
    with pytest.raises(ValueError, match="live driver: no JSON object in response"):
        LiveDriver(_fake("I could not decide what to do.")).reason(SUMMARY)
    assert not nonet


def test_E_prompt_carries_summary_and_passthrough(nonet):  # §8 E
    client = _fake(json.dumps({"complete": False, "intents": [_intent(i) for i in range(5)]}))
    out = LiveDriver(client).reason(SUMMARY)
    assert len(client.seen) == 1
    assert str(SUMMARY.finding_count) in client.seen[0]
    assert str(SUMMARY.secret_count) in client.seen[0]
    assert len(out["intents"]) == 5  # no truncation (D3)
    with pytest.raises(ContractViolation):
        validate_reason_payload(out)
    assert not nonet


def test_F2_scope_audit_whole_window():  # §8 F2
    out = subprocess.run(["git", "diff", "--name-only", f"{BRIEF_BASE}..{BRIEF_MERGE}"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    assert set(out) <= SECTION_3, set(out) - SECTION_3
