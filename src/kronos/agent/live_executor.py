"""Live Executor (SPEC_BRIEF22 §2). Agent "validate" intents -> real validators via existing helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kronos.agent.contracts import Intent
from kronos.agent.executor import ExecutionOutcome
from kronos.evidence import get_evidence
from kronos.validate.candidates import find_candidate_targets_for_secret
from kronos.validate.registry import classify_validator_kind, get_validator

if TYPE_CHECKING:  # pragma: no cover
    from kronos.graph import EngagementGraph


def _decode_secret_value(engagement_dir: str, value_ref: str) -> str:
    """Mirrors runner._decode_secret_value: missing/non-UTF-8 blob -> "" (never crash)."""
    _, _, sha256 = value_ref.partition(":")
    try:
        blob = get_evidence(engagement_dir, sha256)
    except FileNotFoundError:
        return ""
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        return ""


class LiveExecutor:
    def __init__(
        self,
        graph: "EngagementGraph",
        engagement_dir: str,
        *,
        cloud_proxy_endpoint: str | None = None,
        http_hints: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._graph = graph
        self._engagement_dir = engagement_dir
        self._cloud_proxy_endpoint = cloud_proxy_endpoint
        self._http_hints = http_hints or {}

    def execute(self, intent: Intent) -> ExecutionOutcome:
        if intent.kind != "validate":
            return ExecutionOutcome(succeeded=False, evidence=None, detail=f"unhandled intent kind: {intent.kind}")

        secret = self._graph.get_node("SECRET", intent.target_id)
        if not secret:
            return ExecutionOutcome(False, None, detail=f"no SECRET node: {intent.target_id}")

        decoded_value = _decode_secret_value(self._engagement_dir, secret["value_ref"])
        kind = classify_validator_kind(decoded_value)
        validator = get_validator(kind)
        if validator is None:
            return ExecutionOutcome(False, None, detail=f"no validator for secret kind: {kind}")

        expected_type = "CLOUD_RESOURCE" if kind == "cloud_credential_pair" else "API_ENDPOINT"
        last = ExecutionOutcome(False, None, detail="no eligible candidate")

        for candidate in find_candidate_targets_for_secret(self._graph, intent.target_id):
            if candidate.type != expected_type:
                continue
            if not candidate.in_scope:
                continue
            if candidate.type == "CLOUD_RESOURCE" and self._cloud_proxy_endpoint is None:
                continue

            if candidate.type == "API_ENDPOINT":
                outcome = validator(decoded_value, candidate.id, **self._http_hints.get(candidate.id, {}))
            else:
                outcome = validator(decoded_value, candidate.id, self._cloud_proxy_endpoint)

            mapped = ExecutionOutcome(
                succeeded=outcome.live, evidence=outcome.evidence or None, detail=outcome.detail
            )
            if outcome.live:
                return mapped
            last = mapped
        return last
