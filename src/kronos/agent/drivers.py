"""Driver boundary + deterministic mock (SPEC_BRIEF16 §2b). No LLM, no network."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Sequence

if TYPE_CHECKING:  # pragma: no cover
    from kronos.agent.planner import GraphSummary


class Driver(Protocol):
    def reason(self, summary: "GraphSummary") -> dict: ...


class MockDriver:
    def __init__(self, scripted: Sequence[dict]) -> None:
        self._scripted = list(scripted)
        self._i = 0

    def reason(self, summary: "GraphSummary") -> dict:
        if self._i >= len(self._scripted):
            raise RuntimeError("mock driver exhausted")
        payload = self._scripted[self._i]
        self._i += 1
        return payload
