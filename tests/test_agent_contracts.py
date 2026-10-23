"""SPEC_BRIEF16 §8 criteria A-G, N (contracts/drivers/source). Expected values derive from the brief's prose."""

from __future__ import annotations

from pathlib import Path

import pytest

from kronos.agent.contracts import (
    FORBIDDEN_FIELDS,
    MAX_INTENTS,
    ContractViolation,
    Intent,
    ReasonResult,
    validate_reason_payload,
)
from kronos.agent.drivers import MockDriver

ROOT = Path(__file__).parent.parent
AGENT = ROOT / "src" / "kronos" / "agent"


def _intent(i=0):
    return {"kind": "k", "target_id": f"t{i}", "rationale": "r"}


def test_A_valid_complete():  # §2a(ii),(vi): complete -> intents == ()
    r = validate_reason_payload({"complete": True})
    assert isinstance(r, ReasonResult) and r.complete is True and r.intents == ()


@pytest.mark.parametrize("n", range(1, MAX_INTENTS + 1))
def test_B_valid_intents(n):  # §8 B: 1..MAX_INTENTS, order preserved
    payload = {"intents": [_intent(i) for i in range(n)]}
    r = validate_reason_payload(payload)
    assert r.complete is False
    assert all(isinstance(x, Intent) for x in r.intents)
    assert [x.target_id for x in r.intents] == [f"t{i}" for i in range(n)]


def test_C_mutual_exclusion():  # §2a(ii),(iii)
    with pytest.raises(ContractViolation):
        validate_reason_payload({"complete": True, "intents": [_intent()]})
    with pytest.raises(ContractViolation):
        validate_reason_payload({})
    with pytest.raises(ContractViolation):
        validate_reason_payload({"complete": False, "intents": []})


def test_D_intent_cap():  # §2a(iv); MAX_INTENTS == 4 per §2a
    assert MAX_INTENTS == 4
    validate_reason_payload({"intents": [_intent(i) for i in range(MAX_INTENTS)]})
    with pytest.raises(ContractViolation):
        validate_reason_payload({"intents": [_intent(i) for i in range(MAX_INTENTS + 1)]})


@pytest.mark.parametrize("missing", ["kind", "target_id", "rationale"])
def test_E_missing_key(missing):  # §2a(v)
    bad = _intent()
    del bad[missing]
    with pytest.raises(ContractViolation):
        validate_reason_payload({"intents": [bad]})


@pytest.mark.parametrize("key", ["kind", "target_id", "rationale"])
def test_E_non_str_value(key):
    bad = _intent()
    bad[key] = 5
    with pytest.raises(ContractViolation):
        validate_reason_payload({"intents": [bad]})


@pytest.mark.parametrize("bad", ["x", 1, None, ["a"]])
def test_E_intent_not_dict(bad):
    with pytest.raises(ContractViolation):
        validate_reason_payload({"intents": [bad]})


def test_E_payload_not_dict():  # §2a(i)
    for bad in (None, [], "complete", 3):
        with pytest.raises(ContractViolation):
            validate_reason_payload(bad)


def test_F_forbidden_fields_set():
    assert FORBIDDEN_FIELDS == frozenset({"status", "in_scope", "confidence", "merged_into"})


@pytest.mark.parametrize("field", sorted(FORBIDDEN_FIELDS))
def test_F_hostile_top_level(field):  # §2a(vi) top level, even with a valid body
    with pytest.raises(ContractViolation):
        validate_reason_payload({"complete": True, field: "x"})
    with pytest.raises(ContractViolation):
        validate_reason_payload({"intents": [_intent()], field: "x"})


@pytest.mark.parametrize("field", sorted(FORBIDDEN_FIELDS))
def test_F_hostile_inside_intent(field):  # §2a(vi) inside any intent
    ok, bad = _intent(0), _intent(1)
    bad[field] = "x"
    with pytest.raises(ContractViolation):
        validate_reason_payload({"intents": [ok, bad]})


def test_G_mock_driver_determinism():  # §2b
    p1, p2 = {"complete": False, "intents": [_intent()]}, {"complete": True}
    d = MockDriver([p1, p2])
    assert d.reason(None) == p1
    assert d.reason(None) == p2
    with pytest.raises(RuntimeError):
        d.reason(None)


WRITERS = ("upsert_node", "upsert_edge", "advance_secret_status", "advance_finding_status", "charge")


@pytest.mark.parametrize("mod", ["contracts.py", "planner.py", "dispatcher.py"])
def test_N_no_writer_calls(mod):  # §8 N
    src = (AGENT / mod).read_text()
    for w in WRITERS:
        assert f"{w}(" not in src, f"{mod} calls {w}"
