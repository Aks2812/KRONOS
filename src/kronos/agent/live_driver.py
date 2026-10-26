"""LLM-backed Driver (SPEC_BRIEF23 §2). Transport is an injected client; no network, SDK or env here."""

from __future__ import annotations

import json
from typing import Callable

from kronos.agent.planner import GraphSummary


class LiveDriver:
    def __init__(self, client: Callable[[str], str], *, model: str = "claude-sonnet-5") -> None:
        self._client = client
        self._model = model

    def _prompt(self, summary: GraphSummary) -> str:
        return (
            f"Model: {self._model}\n"
            "You propose next actions for a security-validation agent. Engagement summary:\n"
            f"finding_count: {summary.finding_count}\n"
            f"secret_count: {summary.secret_count}\n"
            f"findings_by_status: {list(summary.findings_by_status)}\n"
            "Return a single JSON object of the form "
            '{"complete": bool, "intents": [{"kind": str, "target_id": str, "rationale": str}, ...]}.'
        )

    def reason(self, summary: GraphSummary) -> dict:
        text = self._client(self._prompt(summary))
        decoder = json.JSONDecoder()
        for i, ch in enumerate(text):
            if ch != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(text, i)
            except ValueError:
                continue
            return obj
        raise ValueError("live driver: no JSON object in response")
