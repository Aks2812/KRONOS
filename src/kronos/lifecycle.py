"""The false-positive killer (SPEC.md "VALIDATION LIFECYCLE").

This module is the ONLY place `SECRET.status`, `FINDING.status`, and
`confidence` change after a node's initial creation. `EngagementGraph`
exposes no generic status/confidence setter; `advance_secret_status` and
`advance_finding_status` are the sole write path, so every hard rule below
is enforced at that single chokepoint rather than hoped for by convention:

  1. FINDING -> 'reported' ONLY if status==exploited AND >=1 EVIDENCE node.
  2. SECRET anchors a reported finding ONLY if status==reachable AND its
     authenticates_to target has in_scope==true.
  3. confidence is DERIVED from status, never set freely.
  4. A SECRET whose only authenticates_to target is out-of-scope is
     recorded but flagged (`scope_note`) — never actioned, never reported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # pragma: no cover - avoids a runtime import cycle with graph.py
    from kronos.graph import EngagementGraph

SECRET_TRANSITIONS: dict[str, set[str]] = {
    "extracted": {"validated", "dead"},
    "validated": {"reachable", "dead"},
    "reachable": {"dead"},
    "dead": set(),
}

FINDING_TRANSITIONS: dict[str, set[str]] = {
    "hypothesis": {"reachable", "discarded"},
    "reachable": {"exploited", "discarded"},
    "exploited": {"reported", "discarded"},
    "reported": set(),
    "discarded": set(),
}

_OUT_OF_SCOPE_NOTE = "reachable target(s) out-of-scope; recorded only, not actionable"

# Entities whose authenticates_to/references far end we need to check for
# the scope-anchor rule. Kuzu lets an untyped node pattern span a rel
# group's whole set of target tables, so a single query covers all of
# them regardless of which specific type a given SECRET points at.


class LifecycleError(Exception):
    """Raised when a caller attempts a transition or report the spec forbids."""


def derive_confidence(entity_type: Literal["secret", "finding"], status: str, has_evidence: bool) -> int:
    """Pure function: the ONLY source of confidence values.

    Fixed constants (SPEC.md's confidence rule, with the "reachable
    without evidence" gap it leaves unstated filled in at the floor of
    the validated/reachable bracket — see DECISIONS.md):
      exploited / reported                -> 10
      reachable, has_evidence             -> 9
      reachable, not has_evidence         -> 7
      validated                           -> 7
      extracted / hypothesis              -> 3   (hard cap: always < 7)
      dead / discarded                    -> 0
    """
    if status in ("exploited", "reported"):
        return 10
    if status == "reachable":
        return 9 if has_evidence else 7
    if status == "validated":
        return 7
    if status in ("extracted", "hypothesis"):
        return 3
    if status in ("dead", "discarded"):
        return 0
    raise ValueError(f"unrecognized ({entity_type!r}, {status!r}) for derive_confidence")


def _evidence_count(graph: "EngagementGraph", target_type: Literal["finding", "secret"], target_id: str) -> int:
    table = "FINDING" if target_type == "finding" else "SECRET"
    result = graph.execute(
        f"MATCH (e:EVIDENCE)-[:evidences]->(n:{table} {{id: $id}}) RETURN count(e)",
        {"id": target_id},
    )
    return result.get_next()[0]


def can_anchor_finding(graph: "EngagementGraph", secret_id: str) -> bool:
    """SPEC.md rule 2: reachable AND at least one in-scope authenticates_to target."""
    secret = graph.get_node("SECRET", secret_id)
    if secret is None or secret.get("status") != "reachable":
        return False
    result = graph.execute(
        "MATCH (s:SECRET {id: $id})-[:authenticates_to]->(t) RETURN t.in_scope",
        {"id": secret_id},
    )
    while result.has_next():
        (in_scope,) = result.get_next()
        if in_scope:
            return True
    return False


def _set_secret_fields(graph: "EngagementGraph", secret_id: str, status: str, confidence: int, scope_note: str | None) -> None:
    graph.execute(
        "MATCH (s:SECRET {id: $id}) SET s.status = $status, s.confidence = $confidence, s.scope_note = $scope_note",
        {"id": secret_id, "status": status, "confidence": confidence, "scope_note": scope_note},
    )


def _set_finding_fields(graph: "EngagementGraph", finding_id: str, status: str, confidence: int) -> None:
    graph.execute(
        "MATCH (f:FINDING {id: $id}) SET f.status = $status, f.confidence = $confidence",
        {"id": finding_id, "status": status, "confidence": confidence},
    )


def advance_secret_status(graph: "EngagementGraph", secret_id: str, new_status: str) -> None:
    secret = graph.get_node("SECRET", secret_id)
    if secret is None:
        raise LifecycleError(f"no SECRET with id {secret_id!r}")
    current = secret["status"]
    allowed = SECRET_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise LifecycleError(f"invalid SECRET transition {current} -> {new_status}")

    scope_note = None
    if new_status == "reachable":
        result = graph.execute(
            "MATCH (s:SECRET {id: $id})-[:authenticates_to]->(t) RETURN t.in_scope",
            {"id": secret_id},
        )
        targets_in_scope = []
        while result.has_next():
            (in_scope,) = result.get_next()
            targets_in_scope.append(in_scope)
        if targets_in_scope and not any(targets_in_scope):
            scope_note = _OUT_OF_SCOPE_NOTE

    has_evidence = _evidence_count(graph, "secret", secret_id) > 0
    confidence = derive_confidence("secret", new_status, has_evidence)
    _set_secret_fields(graph, secret_id, new_status, confidence, scope_note)


def advance_finding_status(graph: "EngagementGraph", finding_id: str, new_status: str) -> None:
    finding = graph.get_node("FINDING", finding_id)
    if finding is None:
        raise LifecycleError(f"no FINDING with id {finding_id!r}")
    current = finding["status"]
    allowed = FINDING_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise LifecycleError(f"invalid FINDING transition {current} -> {new_status}")

    if new_status == "reported":
        # SPEC.md rule 1, asserted independently of the transition table.
        if current != "exploited":
            raise LifecycleError("cannot report a finding that is not exploited")
        if _evidence_count(graph, "finding", finding_id) < 1:
            raise LifecycleError("cannot report finding without evidence")

        result = graph.execute(
            "MATCH (f:FINDING {id: $id})-[:references]->(s:SECRET) RETURN s.id",
            {"id": finding_id},
        )
        anchor_secret_ids = []
        while result.has_next():
            anchor_secret_ids.append(result.get_next()[0])
        if anchor_secret_ids and not any(can_anchor_finding(graph, sid) for sid in anchor_secret_ids):
            raise LifecycleError("finding's only secret anchor(s) are not reachable+in-scope")

    has_evidence = _evidence_count(graph, "finding", finding_id) > 0
    confidence = derive_confidence("finding", new_status, has_evidence)
    _set_finding_fields(graph, finding_id, new_status, confidence)
