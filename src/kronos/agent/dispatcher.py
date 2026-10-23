"""Deterministic loop skeleton (SPEC_BRIEF16 §2d). Increment 1: zero graph side effects."""

from __future__ import annotations

from dataclasses import dataclass

from kronos.agent.contracts import Intent
from kronos.agent.drivers import Driver
from kronos.agent.planner import plan, summarize
from kronos.agent.reviewer import COMMIT_STATUS, Reviewer, ReviewVerdict, validate_verdict


@dataclass(frozen=True)
class DispatcherResult:
    complete: bool
    proposed_intents: tuple[Intent, ...]
    steps: int
    committed: tuple[str, ...] = ()


def _commit(engagement, intent: Intent, verdict: ReviewVerdict) -> str:
    finding_id = f"finding:agent-proposal:{intent.kind}:{intent.target_id}"
    engagement.upsert_node(
        "FINDING",
        finding_id,
        {"source": "agent_dispatcher", "title": intent.rationale, "severity": "info", "status": COMMIT_STATUS},
    )
    if verdict.target_type == "SECRET":
        engagement.upsert_edge("derived_from", finding_id, "FINDING", intent.target_id, "SECRET")
    else:
        engagement.upsert_edge("vulnerable_to", intent.target_id, verdict.target_type, finding_id, "FINDING")
    return finding_id


def run_once(engagement, driver: Driver, reviewer: Reviewer | None = None) -> DispatcherResult:
    result = plan(summarize(engagement), driver)
    committed: list[str] = []
    if reviewer is not None and not result.complete:
        for intent in result.intents:
            verdict = reviewer.review(intent)
            validate_verdict(verdict)
            if verdict.approved and engagement.scope.is_in_scope(
                intent.target_id, node_type=verdict.target_type, target_kind="id"
            ):
                committed.append(_commit(engagement, intent, verdict))
    return DispatcherResult(
        complete=result.complete, proposed_intents=result.intents, steps=1, committed=tuple(committed)
    )


def run(engagement, driver: Driver, *, max_steps: int, reviewer: Reviewer | None = None) -> list[DispatcherResult]:
    if max_steps < 1:
        raise ValueError("max_steps must be >= 1")
    results: list[DispatcherResult] = []
    for _ in range(max_steps):
        r = run_once(engagement, driver, reviewer)
        results.append(r)
        if r.complete:
            break
    return results
