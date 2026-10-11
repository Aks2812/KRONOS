"""Secret validation (SPEC_BRIEF3): advances SECRETs through their
Brief #1-fixed lifecycle by ACTUALLY TESTING them against live targets —
extracted -> validated (real auth proof) -> reachable (in-scope target).

Source-agnostic: this package never knows about CyberGym or any other
specific target. It dispatches by decoded secret-value shape and
discovers candidates from edges any ingester already writes (`leaks`,
`references`). See `runner.run_validation_pass` for the orchestrator and
`README.md` for how to call it against a real engagement.
"""

from __future__ import annotations

from kronos.validate.runner import ValidationAttempt, run_validation_pass
from kronos.validate.types import CandidateTarget, ValidationOutcome

__all__ = ["run_validation_pass", "ValidationAttempt", "CandidateTarget", "ValidationOutcome"]
