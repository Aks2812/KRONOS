"""The false-positive killer (SPEC.md "VALIDATION LIFECYCLE").

This module is the ONLY place `SECRET.status`, `FINDING.status`, and
`confidence` change after a node's initial creation. `EngagementGraph`
exposes no generic status/confidence setter; `advance_secret_status` and
`advance_finding_status` are the sole *forward* write path (still called
only by the validation runner), so every hard rule below is enforced at
that single chokepoint rather than hoped for by convention:

  1. FINDING -> 'reported' ONLY if status==exploited AND >=1 EVIDENCE node.
  2. SECRET anchors a reported finding ONLY if status==reachable AND its
     authenticates_to target has in_scope==true.
  3. confidence is DERIVED from status, never set freely.
  4. A SECRET whose only authenticates_to target is out-of-scope is
     recorded but flagged (`scope_note`) — never actioned, never reported.

SPEC_BRIEF4 (reconciliation) adds a second, narrowly-scoped write path:
`set_secret_status_from_evidence`, called only by `kronos.reconcile.merge`
after folding a duplicate SECRET's edges into its merge survivor. It is
NOT a forward mutator — it does not consult `SECRET_TRANSITIONS` and may
legitimately move status *backward* (e.g. an evidenceless `reachable`
label collapsing to `extracted` once merged with a twin that carries no
evidence either — see `recompute_status_from_evidence`). That is
deliberate: a merge is a recompute of what the now-combined evidence
actually justifies, not a lifecycle transition, so the forward-only
transition table does not apply to it. `advance_secret_status` remains
the only place a SECRET is advanced *forward*, and remains exclusively
called by the validation runner — reconciliation never calls it, and
never assigns a status value that didn't come out of
`recompute_status_from_evidence`.
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


def _scope_note_if_reachable(graph: "EngagementGraph", secret_id: str, new_status: str) -> str | None:
    """SPEC.md rule 4: a `reachable` SECRET whose only authenticates_to
    target(s) are out-of-scope gets a note, never a silent upgrade.
    Shared by `advance_secret_status` and `set_secret_status_from_evidence`
    — both ultimately write the same `reachable` state and must derive
    `scope_note` identically."""
    if new_status != "reachable":
        return None
    result = graph.execute(
        "MATCH (s:SECRET {id: $id})-[:authenticates_to]->(t) RETURN t.in_scope",
        {"id": secret_id},
    )
    targets_in_scope = []
    while result.has_next():
        (in_scope,) = result.get_next()
        targets_in_scope.append(in_scope)
    if targets_in_scope and not any(targets_in_scope):
        return _OUT_OF_SCOPE_NOTE
    return None


def advance_secret_status(graph: "EngagementGraph", secret_id: str, new_status: str) -> None:
    secret = graph.get_node("SECRET", secret_id)
    if secret is None:
        raise LifecycleError(f"no SECRET with id {secret_id!r}")
    current = secret["status"]
    allowed = SECRET_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise LifecycleError(f"invalid SECRET transition {current} -> {new_status}")

    scope_note = _scope_note_if_reachable(graph, secret_id, new_status)
    has_evidence = _evidence_count(graph, "secret", secret_id) > 0
    confidence = derive_confidence("secret", new_status, has_evidence)
    _set_secret_fields(graph, secret_id, new_status, confidence, scope_note)


def recompute_status_from_evidence(carried_statuses: list[str], has_evidence: bool) -> str:
    """Pure (SPEC_BRIEF4 FORK-B, option 1): given the statuses a merge's
    members carried in BEFORE the merge, and whether the survivor has at
    least one EVIDENCE node linked (`evidences`) AFTER the merge's edges
    have been carried over, return the status the merge justifies.

    Deliberately NOT "max of carried_statuses" (SPEC_BRIEF4 §3.2's core
    FP-safety rule) — a label survives a merge only if the evidence that
    justifies it survives too:

      - "dead" is terminal and sticky: once any twin is proven dead, no
        amount of (possibly stale) evidence on another twin resurrects
        it. A credential that's been rotated/revoked stays dead.
      - Otherwise, evidence is the ONLY thing that can earn "reachable" —
        a node merely *labelled* reachable with no evidence behind it
        (an unbacked optimistic label) is indistinguishable, post-merge,
        from a plain "extracted" secret, and recomputes to "extracted".
      - No evidence and no dead twin -> "extracted" (the floor; this
        function never produces "validated" — that intermediate step
        belongs to the forward lifecycle's real validate-then-reach
        sequence, not to a merge recompute).
    """
    if "dead" in carried_statuses:
        return "dead"
    return "reachable" if has_evidence else "extracted"


def set_secret_status_from_evidence(
    graph: "EngagementGraph", secret_id: str, carried_statuses: list[str]
) -> None:
    """The reconciliation write path (SPEC_BRIEF4 FORK-B). Called ONLY by
    `kronos.reconcile.merge`, after it has already carried every loser's
    edges (including `evidences`) onto `secret_id`, the merge survivor.

    Not a forward mutator: does not consult `SECRET_TRANSITIONS` at all,
    because a merge recompute can legitimately move status backward
    (`reachable` label -> `extracted`, see `recompute_status_from_evidence`),
    which the forward-only transition table would reject. The status it
    writes is never anything other than `recompute_status_from_evidence`'s
    own return value — reconciliation does not get to pick a status.
    """
    has_evidence = _evidence_count(graph, "secret", secret_id) > 0
    new_status = recompute_status_from_evidence(carried_statuses, has_evidence)
    scope_note = _scope_note_if_reachable(graph, secret_id, new_status)
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
