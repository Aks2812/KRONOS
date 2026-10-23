"""Deterministic loop skeleton (SPEC_BRIEF16 §2d). Increment 1: zero graph side effects."""

from __future__ import annotations

from dataclasses import dataclass

from kronos.agent.contracts import Intent
from kronos.agent.drivers import Driver
from kronos.agent.planner import plan, summarize


@dataclass(frozen=True)
class DispatcherResult:
    complete: bool
    proposed_intents: tuple[Intent, ...]
    steps: int


def run_once(engagement, driver: Driver) -> DispatcherResult:
    result = plan(summarize(engagement), driver)
    return DispatcherResult(complete=result.complete, proposed_intents=result.intents, steps=1)


def run(engagement, driver: Driver, *, max_steps: int) -> list[DispatcherResult]:
    if max_steps < 1:
        raise ValueError("max_steps must be >= 1")
    results: list[DispatcherResult] = []
    for _ in range(max_steps):
        r = run_once(engagement, driver)
        results.append(r)
        if r.complete:
            break
    return results
