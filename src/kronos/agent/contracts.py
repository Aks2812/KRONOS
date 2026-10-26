"""Strict structured-output contract for the planner (SPEC_BRIEF16 §2a). Pure; no I/O, no graph."""

from __future__ import annotations

from dataclasses import dataclass

MAX_INTENTS = 4
FORBIDDEN_FIELDS = frozenset({"status", "in_scope", "confidence", "merged_into"})
_INTENT_KEYS = ("kind", "target_id", "rationale")


class ContractViolation(ValueError):
    pass


@dataclass(frozen=True)
class Intent:
    kind: str
    target_id: str
    rationale: str


@dataclass(frozen=True)
class ReasonResult:
    complete: bool
    intents: tuple[Intent, ...]


def validate_reason_payload(payload: dict) -> ReasonResult:
    if not isinstance(payload, dict):
        raise ContractViolation("payload must be a dict")
    bad = FORBIDDEN_FIELDS & payload.keys()
    if bad:
        raise ContractViolation(f"forbidden field(s) {sorted(bad)} at top level")
    raw = payload.get("intents") or []
    if not isinstance(raw, (list, tuple)):
        raise ContractViolation("intents must be a list")
    # Policy: unknown keys are intentionally ignored; only FORBIDDEN_FIELDS are rejected (create-only contract model).
    complete = payload.get("complete", False)
    if not isinstance(complete, bool):
        raise ContractViolation("complete must be a bool")
    if complete and raw:
        raise ContractViolation("complete and intents cannot coexist")
    if not complete and not raw:
        raise ContractViolation("neither complete nor intents present")
    if len(raw) > MAX_INTENTS:
        raise ContractViolation(f"more than {MAX_INTENTS} intents")
    intents = []
    for item in raw:
        if not isinstance(item, dict):
            raise ContractViolation("intent must be a dict")
        bad = FORBIDDEN_FIELDS & item.keys()
        if bad:
            raise ContractViolation(f"forbidden field(s) {sorted(bad)} in intent")
        for k in _INTENT_KEYS:
            if not isinstance(item.get(k), str):
                raise ContractViolation(f"intent {k!r} missing or not a str")
        intents.append(Intent(item["kind"], item["target_id"], item["rationale"]))
    return ReasonResult(complete=complete, intents=tuple(intents))
