"""Plain data types shared by every validator and the runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CandidateTarget:
    """A target a secret might authenticate to, discovered from edges an
    ingester already wrote (see `candidates.py`) — never invented."""

    type: Literal["API_ENDPOINT", "CLOUD_RESOURCE"]
    id: str
    in_scope: bool


@dataclass(frozen=True)
class ValidationOutcome:
    """The result of one real auth attempt against one candidate target.

    `evidence` is the exact bytes stored via `kronos.evidence.store_evidence`
    on a live outcome — the request/response proof, never the raw secret
    value. Must be non-empty whenever `live` is True.
    """

    live: bool
    evidence: bytes
    detail: str
