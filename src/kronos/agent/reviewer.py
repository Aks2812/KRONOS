"""Reviewer contract + mock (SPEC_BRIEF17 §2a). Downgrade-only; no LLM, no network."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from kronos.agent.contracts import Intent

LEGAL_TARGET_TYPES = frozenset({
    "HOST", "SERVICE", "WEB_ENDPOINT", "API_ENDPOINT", "CLOUD_RESOURCE",
    "MOBILE_APP", "MOBILE_COMPONENT", "SECRET",
})
COMMIT_STATUS = "hypothesis"


class ReviewViolation(ValueError):
    pass


@dataclass(frozen=True)
class ReviewVerdict:
    approved: bool
    target_type: str
    status: str


class Reviewer(Protocol):
    def review(self, intent: Intent) -> ReviewVerdict: ...


class MockReviewer:
    def __init__(self, scripted: Sequence[ReviewVerdict]) -> None:
        self._scripted = list(scripted)
        self._i = 0

    def review(self, intent: Intent) -> ReviewVerdict:
        if self._i >= len(self._scripted):
            raise RuntimeError("mock reviewer exhausted")
        verdict = self._scripted[self._i]
        self._i += 1
        return verdict


def validate_verdict(verdict: ReviewVerdict) -> None:
    if not isinstance(verdict, ReviewVerdict):
        raise ReviewViolation("verdict must be a ReviewVerdict")
    if not verdict.approved:
        return
    if verdict.target_type not in LEGAL_TARGET_TYPES:
        raise ReviewViolation(f"illegal target_type {verdict.target_type!r}")
    if verdict.status != COMMIT_STATUS:
        raise ReviewViolation(f"approved verdict may only carry status {COMMIT_STATUS!r}, got {verdict.status!r}")
