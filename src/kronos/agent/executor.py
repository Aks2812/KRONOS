"""Executor boundary + mock (SPEC_BRIEF18 §2a). No concrete live executor; no LLM, no network."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from kronos.agent.contracts import Intent

EVIDENCE_KIND = "agent_execution_proof"


@dataclass(frozen=True)
class ExecutionOutcome:
    succeeded: bool
    evidence: bytes | None
    detail: str = ""


class Executor(Protocol):
    def execute(self, intent: Intent) -> ExecutionOutcome: ...


class MockExecutor:
    def __init__(self, scripted: Sequence[ExecutionOutcome]) -> None:
        self._scripted = list(scripted)
        self._i = 0

    def execute(self, intent: Intent) -> ExecutionOutcome:
        if self._i >= len(self._scripted):
            raise RuntimeError("mock executor exhausted")
        outcome = self._scripted[self._i]
        self._i += 1
        return outcome
