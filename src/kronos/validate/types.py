"""Plain data types shared by every validator and the runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from kronos.validate.controls import Classification


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

    `live` remains the single field the runner acts on for the forward
    lifecycle/edge-writing decision (SPEC_BRIEF8 §3.1) — `lifecycle.py`
    and every pre-existing caller are untouched. SPEC_BRIEF8 adds:

    - `classification` — which arm of the differential matrix this
      outcome landed in (SPEC_BRIEF8 §3.3/§3.4).
    - `control_outcome` — what the control arm(s) observed (status/code
      only, never a secret).
    - `discriminated` — did the arms differ in a way that isolates the
      credential as the cause? The runner, not this type, writes an
      `authenticates_to` edge or advances a secret; this field is what it
      reads to decide.

    `evidence` is the exact bytes stored via `kronos.evidence.store_evidence`
    on a live or `authenticated_not_authorized` outcome — the
    request/response proof, never the raw secret value. Must be non-empty
    whenever `live` is True.

    **Structural invariant (SPEC_BRIEF8 §3.1, enforced here, not just by
    convention):** `live=True` is impossible unless `discriminated=True`
    and `classification == "live_discriminated"` — there is no code path,
    anywhere, that can construct a `ValidationOutcome` claiming `live=True`
    from a single, undiscriminated arm.
    """

    live: bool
    evidence: bytes
    detail: str
    classification: Classification = "inconclusive"
    control_outcome: str = ""
    discriminated: bool = False

    def __post_init__(self) -> None:
        if self.live and not self.discriminated:
            raise ValueError(
                "ValidationOutcome.live=True requires discriminated=True (SPEC_BRIEF8 §3.1 invariant)"
            )
        if self.live and self.classification != "live_discriminated":
            raise ValueError(
                "ValidationOutcome.live=True requires classification=='live_discriminated' "
                f"(got {self.classification!r})"
            )
