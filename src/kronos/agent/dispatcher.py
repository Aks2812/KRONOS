"""Deterministic loop skeleton (SPEC_BRIEF16 §2d). Increment 1: zero graph side effects."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from kronos.agent.contracts import Intent
from kronos.agent.drivers import Driver
from kronos.agent.executor import EVIDENCE_KIND, Executor
from kronos.agent.planner import plan, summarize
from kronos.agent.reviewer import COMMIT_STATUS, Reviewer, ReviewVerdict, validate_verdict
from kronos.evidence import attach_evidence
from kronos.lifecycle import advance_finding_status


@dataclass(frozen=True)
class DispatcherResult:
    complete: bool
    proposed_intents: tuple[Intent, ...]
    steps: int
    committed: tuple[str, ...] = ()
    promoted: tuple[str, ...] = ()
    timed_out: bool = False


@dataclass(frozen=True)
class RunSummary:
    results: tuple[DispatcherResult, ...]
    total_steps: int
    conclusion: str
    committed: tuple[str, ...]
    promoted: tuple[str, ...]


def summarize_run(results: list[DispatcherResult]) -> RunSummary:
    last = results[-1]
    if last.timed_out:
        conclusion = "timed_out"
    elif last.complete:
        conclusion = "complete"
    else:
        conclusion = "max_steps"
    return RunSummary(
        results=tuple(results),
        total_steps=sum(r.steps for r in results),
        conclusion=conclusion,
        committed=tuple(c for r in results for c in r.committed),
        promoted=tuple(p for r in results for p in r.promoted),
    )


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


def run_once(
    engagement,
    driver: Driver,
    reviewer: Reviewer | None = None,
    executor: Executor | None = None,
    engagement_dir=None,
) -> DispatcherResult:
    if executor is not None and engagement_dir is None:
        raise ValueError("engagement_dir is required when an executor is given")
    result = plan(summarize(engagement), driver)
    committed: list[tuple[str, Intent]] = []
    promoted: list[str] = []
    if reviewer is not None and not result.complete:
        # Phase 1: adjudicate every intent; no writes, so a violation leaves the graph untouched.
        verdicts = []
        for intent in result.intents:
            verdict = reviewer.review(intent)
            validate_verdict(verdict)
            verdicts.append((intent, verdict))
        # Phase 2: commit.
        for intent, verdict in verdicts:
            if verdict.approved and engagement.scope.is_in_scope(
                intent.target_id, node_type=verdict.target_type, target_kind="id"
            ):
                committed.append((_commit(engagement, intent, verdict), intent))
        # Phase 3: execute only gated, committed findings; promote only on success WITH evidence.
        if executor is not None:
            for finding_id, intent in committed:
                outcome = executor.execute(intent)
                if outcome.succeeded and outcome.evidence is not None:
                    attach_evidence(
                        engagement,
                        engagement_dir,
                        outcome.evidence,
                        kind=EVIDENCE_KIND,
                        target_type="finding",
                        target_id=finding_id,
                    )
                    advance_finding_status(engagement, finding_id, "reachable")
                    promoted.append(finding_id)
    return DispatcherResult(
        complete=result.complete, proposed_intents=result.intents, steps=1,
        committed=tuple(f for f, _ in committed), promoted=tuple(promoted),
    )


def run(
    engagement,
    driver: Driver,
    *,
    max_steps: int,
    reviewer: Reviewer | None = None,
    executor: Executor | None = None,
    engagement_dir=None,
    deadline: float | None = None,
    clock: Callable[[], float] | None = None,
) -> list[DispatcherResult]:
    if max_steps < 1:
        raise ValueError("max_steps must be >= 1")
    if deadline is not None and deadline <= 0:
        raise ValueError("deadline must be > 0")
    clock = clock or time.monotonic
    start = clock()
    results: list[DispatcherResult] = []
    for _ in range(max_steps):
        if deadline is not None and clock() - start >= deadline:
            results.append(
                DispatcherResult(complete=False, proposed_intents=(), steps=0, committed=(), promoted=(), timed_out=True)
            )
            break
        r = run_once(engagement, driver, reviewer, executor, engagement_dir)
        results.append(r)
        if r.complete:
            break
    return results
