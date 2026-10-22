"""S7.1 transitive invalidation (SPEC_BRIEF15): a secret-derived FINDING
carrying a causal `derived_from` edge to its SECRET, and a pass that moves
dependent FINDINGs to `requires_revalidation` when that SECRET goes `dead`.

Pure graph I/O: no network. The pass changes ONLY FINDING status (via the
`advance_finding_status` chokepoint); EVIDENCE nodes and all edges are kept.
"""

from __future__ import annotations

from kronos.evidence import attach_evidence
from kronos.lifecycle import advance_finding_status

_INVALIDATABLE = ("reachable", "exploited", "reported")


def record_secret_finding(
    engagement, secret_id: str, candidate, *, evidence: bytes | None = None, engagement_dir=None
) -> str:
    finding_id = f"finding:secret-access:{secret_id}:{candidate.id}"
    engagement.upsert_node(
        "FINDING",
        finding_id,
        {
            "source": "secret_validator",
            "title": f"Secret {secret_id} grants access to {candidate.id} (validated)",
            "severity": "info",
            "status": "hypothesis",
        },
    )
    engagement.upsert_edge("derived_from", finding_id, "FINDING", secret_id, "SECRET")
    engagement.upsert_edge("vulnerable_to", candidate.id, candidate.type, finding_id, "FINDING")
    if evidence is not None:
        attach_evidence(
            engagement,
            engagement_dir,
            evidence,
            kind="validation_proof",
            target_type="finding",
            target_id=finding_id,
        )
    # status is create-only, so a re-run finds the FINDING already advanced.
    if engagement.get_node("FINDING", finding_id)["status"] == "hypothesis":
        advance_finding_status(engagement, finding_id, "reachable")
    return finding_id


def invalidate_findings_for_dead_secret(engagement, secret_id: str) -> list[str]:
    result = engagement.execute(
        "MATCH (f:FINDING)-[:derived_from]->(s:SECRET {id: $sid}) RETURN f.id, f.status",
        {"sid": secret_id},
    )
    rows = []
    while result.has_next():
        rows.append(tuple(result.get_next()))
    invalidated = []
    for finding_id, status in rows:
        if status in _INVALIDATABLE:
            advance_finding_status(engagement, finding_id, "requires_revalidation")
            invalidated.append(finding_id)
    return invalidated
