"""Read-only planner (SPEC_BRIEF16 §2c). Reads via the query surface only; never writes."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from kronos.agent.contracts import ReasonResult, validate_reason_payload
from kronos.agent.drivers import Driver
from kronos.query import list_findings, list_secrets


@dataclass(frozen=True)
class GraphSummary:
    finding_count: int
    secret_count: int
    findings_by_status: tuple[tuple[str, int], ...]


def summarize(engagement) -> GraphSummary:
    findings = list_findings(engagement)
    by_status = Counter(f["status"] for f in findings)
    return GraphSummary(
        finding_count=len(findings),
        secret_count=len(list_secrets(engagement)),
        findings_by_status=tuple(sorted(by_status.items())),
    )


def plan(summary: GraphSummary, driver: Driver) -> ReasonResult:
    return validate_reason_payload(driver.reason(summary))
