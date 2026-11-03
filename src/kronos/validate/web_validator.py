"""Web reachability validator (SPEC_BRIEF14 S6.1): a two-armed differential
over in-scope WEB_ENDPOINT nodes. A proven-reachable verdict is recorded as a
FINDING linked `WEB_ENDPOINT --vulnerable_to--> FINDING`; anything
undiscriminated creates nothing (abstention).

`validate_web_endpoint_reachable` is pure. The only connection point of the
pass is the caller-supplied `probe`; this module opens no socket itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from kronos.evidence import attach_evidence
from kronos.lifecycle import advance_finding_status
from kronos.validate.controls import ArmResult, run_differential
from kronos.validate.types import ValidationOutcome
from kronos.commit import MutationSource

# A guaranteed-absent path on the SAME origin, used for the negative-control arm.
CONTROL_PATH = "/kronos-negative-control-probe"


def _arm_summary(arm: ArmResult) -> dict:
    return {"label": arm.label, "success": arm.success, "status_code": arm.status_code}


def validate_web_endpoint_reachable(canonical_probe: ArmResult, control_probe: ArmResult) -> ValidationOutcome:
    result = run_differential([canonical_probe, control_probe], kind="http")
    evidence = json.dumps(
        {"arms": [_arm_summary(canonical_probe), _arm_summary(control_probe)]}
    ).encode()
    return ValidationOutcome(
        live=result.live,
        evidence=evidence,
        detail=result.detail,
        classification=result.classification,
        control_outcome=result.control_outcome,
        discriminated=result.discriminated,
    )


def record_web_finding(
    engagement, endpoint_id: str, outcome: ValidationOutcome, *, engagement_dir: str | Path | None = None
) -> str:
    finding_id = f"finding:web-reachable:{endpoint_id}"
    engagement.upsert_node(
        "FINDING",
        finding_id,
        {
            "source": "web_validator",
            "title": f"Web endpoint {endpoint_id} reachable (two-armed differential)",
            "severity": "info",
            "status": "hypothesis",
        },
        source=MutationSource.VALIDATION,
    )
    engagement.upsert_edge("vulnerable_to", endpoint_id, "WEB_ENDPOINT", finding_id, "FINDING", source=MutationSource.VALIDATION)
    if engagement_dir is not None and outcome is not None and outcome.evidence:
        attach_evidence(
            engagement,
            engagement_dir,
            outcome.evidence,
            kind="validation_proof",
            target_type="finding",
            target_id=finding_id,
            source=MutationSource.VALIDATION,
        )
    # status is create-only, so a re-run finds the FINDING already advanced.
    if engagement.get_node("FINDING", finding_id)["status"] == "hypothesis":
        advance_finding_status(engagement, finding_id, "reachable")
    return finding_id


@dataclass
class WebValidationReport:
    findings: list[str] = field(default_factory=list)
    abstained: list[str] = field(default_factory=list)


def run_web_validation_pass(
    engagement, *, probe: Callable[[str, str], ArmResult], engagement_dir: str | Path | None = None
) -> WebValidationReport:
    report = WebValidationReport()
    rows = engagement.execute(
        "MATCH (w:WEB_ENDPOINT) WHERE w.in_scope = true RETURN w.id, w.url, w.method ORDER BY w.id"
    )
    endpoints = []
    while rows.has_next():
        endpoints.append(tuple(rows.get_next()))
    for endpoint_id, url, method in endpoints:
        parts = urlsplit(url)
        control_url = f"{parts.scheme}://{parts.netloc}{CONTROL_PATH}"
        canonical = replace(probe(url, method), label="A_canonical")
        control = replace(probe(control_url, method), label="B_negative_control")
        outcome = validate_web_endpoint_reachable(canonical, control)
        if outcome.live:
            report.findings.append(record_web_finding(engagement, endpoint_id, outcome, engagement_dir=engagement_dir))
        else:
            report.abstained.append(endpoint_id)
    return report
