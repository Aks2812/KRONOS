"""Live Executor (SPEC_BRIEF22 §2). Agent "validate" intents -> real validators via existing helpers."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlsplit

from kronos.agent.contracts import Intent
from kronos.agent.executor import ExecutionOutcome
from kronos.evidence import get_evidence
from kronos.validate.candidates import find_candidate_targets_for_secret
from kronos.validate.controls import ArmResult
from kronos.validate.infra_validator import CONTROL_PORT, record_infra_finding, validate_service_reachable
from kronos.validate.registry import classify_validator_kind, get_validator
from kronos.validate.web_validator import CONTROL_PATH, record_web_finding, validate_web_endpoint_reachable

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
        service_probe: Callable[[str, int], ArmResult] | None = None,
        web_probe: Callable[[str, str], ArmResult] | None = None,
    ) -> None:
        self._graph = graph
        self._engagement_dir = engagement_dir
        self._cloud_proxy_endpoint = cloud_proxy_endpoint
        self._http_hints = http_hints or {}
        self._service_probe = service_probe
        self._web_probe = web_probe

    def _probe_service(self, intent: Intent) -> ExecutionOutcome:
        node = self._graph.get_node("SERVICE", intent.target_id)
        if not node:
            return ExecutionOutcome(False, None, detail=f"no SERVICE node: {intent.target_id}")
        if self._service_probe is None:
            return ExecutionOutcome(False, None, detail="no service probe configured")
        if node.get("in_scope") is not True:
            return ExecutionOutcome(False, None, detail=f"SERVICE out of scope: {intent.target_id}")
        host = intent.target_id.rsplit(":", 1)[0]
        port = int(node["port"])
        canonical = replace(self._service_probe(host, port), label="A_canonical")
        control = replace(self._service_probe(host, CONTROL_PORT), label="B_negative_control")
        outcome = validate_service_reachable(canonical, control)
        if outcome.live:
            finding_id = record_infra_finding(self._graph, intent.target_id, outcome)
            return ExecutionOutcome(succeeded=True, evidence=None, detail=finding_id)
        return ExecutionOutcome(succeeded=False, evidence=None, detail="abstained")

    def _probe_web(self, intent: Intent) -> ExecutionOutcome:
        node = self._graph.get_node("WEB_ENDPOINT", intent.target_id)
        if not node:
            return ExecutionOutcome(False, None, detail=f"no WEB_ENDPOINT node: {intent.target_id}")
        if self._web_probe is None:
            return ExecutionOutcome(False, None, detail="no web probe configured")
        if node.get("in_scope") is not True:
            return ExecutionOutcome(False, None, detail=f"WEB_ENDPOINT out of scope: {intent.target_id}")
        url, method = node["url"], node["method"]
        parts = urlsplit(url)
        control_url = f"{parts.scheme}://{parts.netloc}{CONTROL_PATH}"
        canonical = replace(self._web_probe(url, method), label="A_canonical")
        control = replace(self._web_probe(control_url, method), label="B_negative_control")
        outcome = validate_web_endpoint_reachable(canonical, control)
        if outcome.live:
            finding_id = record_web_finding(self._graph, intent.target_id, outcome)
            return ExecutionOutcome(succeeded=True, evidence=None, detail=finding_id)
        return ExecutionOutcome(succeeded=False, evidence=None, detail="abstained")

    def execute(self, intent: Intent) -> ExecutionOutcome:
        if intent.kind == "probe_service":
            return self._probe_service(intent)
        if intent.kind == "probe_web":
            return self._probe_web(intent)
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
