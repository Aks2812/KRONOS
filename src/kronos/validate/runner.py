"""The validation orchestrator (SPEC_BRIEF3 "WIRING"): given the graph
post-ingestion, attempt validation on each `extracted` SECRET against
its candidate targets, scope-gated, advancing status + writing evidence
+ creating `authenticates_to` edges per the brief's rules.

Two invariants this module alone is responsible for holding under
adversarial input (SPEC_BRIEF3 "Security lens"):
  1. A credential is NEVER sent to an out-of-scope target — the in_scope
     check on each candidate happens BEFORE the matching validator is
     even called, let alone before any network/boto3 call inside it.
  2. `advance_secret_status` (Brief #1's sole status-writing chokepoint)
     is the ONLY thing that ever changes a SECRET's status here — this
     module never sets status/confidence/evidence any other way.

A third invariant as of SPEC_BRIEF5: every attempted validator call
charges a `BudgetLedger` (the one chokepoint — `kronos.budget`) BEFORE
the validator is invoked, never after and never from inside
`_advance_through`/`attach_evidence` — budget enforcement wraps around
validation, it never reaches into the status/evidence logic those two
guardrails already own (SPEC_BRIEF5 guardrail 2). A `BudgetExceeded`
raised by that charge propagates straight out of this function
uncaught: this module's job is to meter and attempt, not to decide what
"stopped early" means for the run as a whole — that's the caller's
wind-down to perform (see `cybergym/kronos_validation_run.py`).

SPEC_BRIEF8 "Negative-control validation" adds a fourth invariant: a
validator call is now a DIFFERENTIAL of 2 (http) or 3 (cloud) arms run
atomically inside one `validator(...)` call, never bisectable by a
budget ceiling landing mid-differential (FORK-J's DEFAULT). Both the
`validation_attempts` charge (still 1 per *candidate*, unchanged) and the
`tool_invocations` charge (now the arm COUNT for that candidate's kind,
not a flat 1) happen together, before `validator(...)` is invoked at
all — so a `BudgetExceeded` here still means the validator for this
candidate never started, exactly as before SPEC_BRIEF8, just priced
correctly for what a differential actually costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from kronos.budget import BudgetLedger, DEFAULT_BUDGET_LIMITS
from kronos.evidence import attach_evidence, get_evidence
from kronos.lifecycle import advance_secret_status
from kronos.validate.candidates import find_candidate_targets_for_secret
from kronos.validate.controls import Classification
from kronos.validate.invalidation import record_secret_finding
from kronos.validate.registry import classify_validator_kind, get_validator

if TYPE_CHECKING:  # pragma: no cover
    from kronos.graph import EngagementGraph

# SPEC_BRIEF8 FORK-J: how many arms a differential costs for this
# validator kind — charged to `tool_invocations` atomically, up front,
# alongside the single `validation_attempts` charge for the candidate.
_ARM_COUNT_BY_KIND: dict[str, int] = {"api_token": 2, "cloud_credential_pair": 3}


@dataclass(frozen=True)
class ValidationAttempt:
    secret_id: str
    target_id: str
    target_type: str
    live: bool
    detail: str
    classification: Classification
    discriminated: bool


def _decode_secret_value(engagement_dir: str, value_ref: str) -> str:
    """`value_ref` is "sha256:<hash>" (Brief #2's evidence-store pointer,
    never the raw secret inline on the node). A missing/unreadable blob
    decodes to "" — classify_validator_kind("") -> "unknown", so this
    degrades to "no validator", never a crash."""
    _, _, sha256 = value_ref.partition(":")
    try:
        blob = get_evidence(engagement_dir, sha256)
    except FileNotFoundError:
        return ""
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _extracted_secret_ids(graph: "EngagementGraph") -> list[str]:
    result = graph.execute("MATCH (s:SECRET {status: 'extracted'}) RETURN s.id")
    ids = []
    while result.has_next():
        ids.append(result.get_next()[0])
    return ids


def _advance_through(graph: "EngagementGraph", secret_id: str) -> None:
    """Idempotent against repeat live candidates for the same secret —
    only takes the transitions the secret's CURRENT status still allows,
    never re-attempts one it's already past (SECRET_TRANSITIONS forbids
    re-entering "validated" from "reachable")."""
    current = graph.get_node("SECRET", secret_id)["status"]
    if current == "extracted":
        advance_secret_status(graph, secret_id, "validated")
        current = "validated"
    if current == "validated":
        advance_secret_status(graph, secret_id, "reachable")


def _advance_to_validated_only(graph: "EngagementGraph", secret_id: str) -> None:
    """SPEC_BRIEF8 FORK-M: `authenticated_not_authorized` is genuine,
    differentially-proven evidence the credential is real, but NOT that
    it opens this particular candidate — advance only as far as
    "validated", never to "reachable" via this candidate. Idempotent the
    same way `_advance_through` is: if this secret already reached
    "validated" or "reachable" through a DIFFERENT, successful candidate,
    this is a safe no-op, never a backward move or a duplicate-transition
    error (SECRET_TRANSITIONS has no "validated" -> "validated" edge)."""
    current = graph.get_node("SECRET", secret_id)["status"]
    if current == "extracted":
        advance_secret_status(graph, secret_id, "validated")


def run_validation_pass(
    graph: "EngagementGraph",
    engagement_dir: str,
    *,
    cloud_proxy_endpoint: str | None = None,
    http_hints: dict[str, dict[str, Any]] | None = None,
    budget: BudgetLedger | None = None,
) -> list[ValidationAttempt]:
    """Snapshot every `extracted` SECRET once at the start — a secret
    that reaches `reachable` partway through still has its remaining
    candidates tried (needed to prove an over-privileged credential
    authenticates to MORE THAN ONE target, e.g. CyberGym's chain 3).

    `budget` is optional so every existing caller/test keeps working
    unchanged; when omitted, a fresh ledger is built from
    `DEFAULT_BUDGET_LIMITS` rather than skipping metering altogether —
    SPEC_BRIEF5 guardrail 3 is "never unlimited by accident," which
    applies just as much to an unannotated call site as to a missing
    `budget.yaml`. A caller that wants this run's spend to count against
    a shared, engagement-wide ledger (the normal case — see
    `cybergym/kronos_validation_run.py`) passes one in explicitly."""
    http_hints = http_hints or {}
    if budget is None:
        budget = BudgetLedger(DEFAULT_BUDGET_LIMITS, config_source="default", config_reason="no ledger supplied to run_validation_pass")
    attempts: list[ValidationAttempt] = []

    for secret_id in _extracted_secret_ids(graph):
        secret = graph.get_node("SECRET", secret_id)
        decoded_value = _decode_secret_value(engagement_dir, secret["value_ref"])
        kind = classify_validator_kind(decoded_value)
        validator = get_validator(kind)
        if validator is None:
            continue

        expected_target_type = "CLOUD_RESOURCE" if kind == "cloud_credential_pair" else "API_ENDPOINT"

        for candidate in find_candidate_targets_for_secret(graph, secret_id):
            if candidate.type != expected_target_type:
                # A secret's classified kind picks ONE validator with
                # ONE calling convention — an api_token secret has no
                # business being boto3-tested against a bucket, and vice
                # versa. find_candidate_targets_for_secret returns both
                # kinds of candidate for every secret (see candidates.py);
                # this filters to the ones the chosen validator applies to.
                continue
            if not candidate.in_scope:
                # Scope-gated BEFORE any call: the validator (and
                # therefore any network/boto3 call inside it) is never
                # invoked for an out-of-scope candidate.
                continue
            if candidate.type == "CLOUD_RESOURCE" and cloud_proxy_endpoint is None:
                continue

            # SPEC_BRIEF5 chokepoint, SPEC_BRIEF8 FORK-J: charge BEFORE the
            # validator call, which now runs an entire 2-or-3-arm
            # differential atomically inside one Python call — so both
            # charges below cover the WHOLE differential, not one arm.
            # `validation_attempts` stays 1 per candidate (unchanged);
            # `tool_invocations` is now the arm count for this secret's
            # validator kind. If either charge raises `BudgetExceeded`, it
            # propagates uncaught — the validator below is never reached,
            # so an over-cap attempt truly never starts a differential,
            # let alone leaves one half-run.
            detail = f"secret={secret_id} target={candidate.id} ({candidate.type})"
            budget.charge("validation_attempts", 1, actor="validate.runner", detail=detail)
            budget.charge(
                "tool_invocations", _ARM_COUNT_BY_KIND[kind], actor="validate.runner", detail=detail
            )

            if candidate.type == "API_ENDPOINT":
                hint = http_hints.get(candidate.id, {})
                outcome = validator(decoded_value, candidate.id, **hint)
            else:  # CLOUD_RESOURCE
                outcome = validator(decoded_value, candidate.id, cloud_proxy_endpoint)

            attempts.append(
                ValidationAttempt(
                    secret_id,
                    candidate.id,
                    candidate.type,
                    outcome.live,
                    outcome.detail,
                    outcome.classification,
                    outcome.discriminated,
                )
            )

            # SPEC_BRIEF8 §3.5: the edge + full forward lifecycle advance
            # happen ONLY on `live_discriminated` (outcome.live, which the
            # ValidationOutcome invariant already ties to
            # discriminated=True). `authenticated_not_authorized` (FORK-M)
            # is real proof the credential is genuine but NOT that it
            # opens this candidate: advance to "validated" only, write no
            # edge. Every other classification — `not_live`,
            # `indiscriminate_target`, `self_request_malformed`,
            # `inconclusive` — is an abstention: no evidence attached, no
            # edge, no status change, the secret stays exactly where it
            # was (SPEC_BRIEF8 guardrail 4/§1: "abstain rather than
            # guess").
            if outcome.live:
                attach_evidence(
                    graph,
                    engagement_dir,
                    outcome.evidence,
                    kind="validation_proof",
                    target_type="secret",
                    target_id=secret_id,
                )
                graph.upsert_edge("authenticates_to", secret_id, "SECRET", candidate.id, candidate.type)
                _advance_through(graph, secret_id)
                record_secret_finding(
                    graph, secret_id, candidate, evidence=outcome.evidence, engagement_dir=engagement_dir
                )
            elif outcome.classification == "authenticated_not_authorized":
                attach_evidence(
                    graph,
                    engagement_dir,
                    outcome.evidence,
                    kind="validation_proof",
                    target_type="secret",
                    target_id=secret_id,
                )
                _advance_to_validated_only(graph, secret_id)

    return attempts
