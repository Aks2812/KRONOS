"""Deterministic loop skeleton (SPEC_BRIEF16 §2d). Increment 1: zero graph side effects."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from kronos.agent.contracts import ContractViolation, Intent
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
    withheld: tuple[str, ...] = ()


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


def _key(intent: Intent) -> str:
    return f"{intent.kind}:{intent.target_id}"


def _topo_order(intents) -> list[int]:
    """Phase 0 (SPEC_BRIEF24 D5/D6): fail-closed dependency validation + stable Kahn order.

    Pure. Without any dependency field it returns list order and validates nothing.
    """
    n = len(intents)
    if not any(i.any_of or i.blocked_by for i in intents):
        return list(range(n))
    index: dict[str, int] = {}
    for pos, intent in enumerate(intents):
        k = _key(intent)
        if k in index:
            raise ContractViolation(f"duplicate intent key {k!r} in a batch with dependencies")
        index[k] = pos
    deps: list[set[int]] = []
    for intent in intents:
        refs = set()
        for ref in (*intent.any_of, *intent.blocked_by):
            if ref not in index:
                raise ContractViolation(f"unknown dependency reference {ref!r}")
            refs.add(index[ref])
        deps.append(refs)
    order: list[int] = []
    done: set[int] = set()
    while len(order) < n:
        ready = next((p for p in range(n) if p not in done and deps[p] <= done), None)
        if ready is None:
            raise ContractViolation("dependency cycle")
        order.append(ready)
        done.add(ready)
    return order


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
    order = _topo_order(result.intents)  # phase 0: raises before any adjudication/write
    committed: list[tuple[str, Intent]] = []
    withheld: list[str] = []
    promoted: list[str] = []
    if reviewer is not None and not result.complete:
        # Phase 1: adjudicate every intent; no writes, so a violation leaves the graph untouched.
        verdicts = []
        for intent in result.intents:
            verdict = reviewer.review(intent)
            validate_verdict(verdict)
            verdicts.append((intent, verdict))
        # Phase 2: commit.
        satisfied: set[str] = set()
        for pos in order:
            intent, verdict = verdicts[pos]
            if not (
                all(r in satisfied for r in intent.blocked_by)
                and (not intent.any_of or any(r in satisfied for r in intent.any_of))
            ):
                withheld.append(_key(intent))
                continue
            if verdict.approved and engagement.scope.is_in_scope(
                intent.target_id, node_type=verdict.target_type, target_kind="id"
            ):
                committed.append((_commit(engagement, intent, verdict), intent))
                satisfied.add(_key(intent))
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
        withheld=tuple(withheld),
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
