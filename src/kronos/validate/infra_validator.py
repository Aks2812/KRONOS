"""Infra reachability validator (SPEC_BRIEF12 S4.1): a two-armed differential
over in-scope SERVICE nodes. A proven-reachable verdict is recorded as a
FINDING linked `SERVICE --vulnerable_to--> FINDING`; anything undiscriminated
creates nothing (abstention).

`validate_service_reachable` is pure. The only connection point of the pass is
the caller-supplied `probe`; this module opens no socket itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Callable

from kronos.lifecycle import advance_finding_status
from kronos.validate.controls import ArmResult, run_differential
from kronos.validate.types import ValidationOutcome

# A closed port on the SAME in-scope host, used for the negative-control arm.
CONTROL_PORT = 9999


def _arm_summary(arm: ArmResult) -> dict:
    return {"label": arm.label, "success": arm.success, "status_code": arm.status_code}


def validate_service_reachable(canonical_probe: ArmResult, control_probe: ArmResult) -> ValidationOutcome:
    result = run_differential([canonical_probe, control_probe], kind="infra")
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


def record_infra_finding(engagement, service_id: str, outcome: ValidationOutcome) -> str:
    finding_id = f"finding:infra-reachable:{service_id}"
    engagement.upsert_node(
        "FINDING",
        finding_id,
        {
            "source": "infra_validator",
            "title": f"Service {service_id} reachable (two-armed differential)",
            "severity": "info",
            "status": "hypothesis",
        },
    )
    engagement.upsert_edge("vulnerable_to", service_id, "SERVICE", finding_id, "FINDING")
    # status is create-only, so a re-run finds the FINDING already advanced.
    if engagement.get_node("FINDING", finding_id)["status"] == "hypothesis":
        advance_finding_status(engagement, finding_id, "reachable")
    return finding_id


@dataclass
class InfraValidationReport:
    findings: list[str] = field(default_factory=list)
    abstained: list[str] = field(default_factory=list)


def run_infra_validation_pass(
    engagement, *, probe: Callable[[str, int], ArmResult]
) -> InfraValidationReport:
    report = InfraValidationReport()
    rows = engagement.execute(
        "MATCH (s:SERVICE) WHERE s.in_scope = true RETURN s.id, s.port ORDER BY s.id"
    )
    services = []
    while rows.has_next():
        services.append(tuple(rows.get_next()))
    for service_id, port in services:
        host = service_id.rsplit(":", 1)[0]
        canonical = replace(probe(host, int(port)), label="A_canonical")
        control = replace(probe(host, CONTROL_PORT), label="B_negative_control")
        outcome = validate_service_reachable(canonical, control)
        if outcome.live:
            report.findings.append(record_infra_finding(engagement, service_id, outcome))
        else:
            report.abstained.append(service_id)
    return report
