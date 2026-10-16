"""The negative-control differential engine (SPEC_BRIEF8 "Negative-control
validation (two-armed proof)") — the one chokepoint for two things:

1. `derive_negative_control` — a deterministic, shape-preserving credential
   that is guaranteed to differ from the real value, used as the
   counterfactual arm.
2. `run_differential` — the ONLY place `discriminated` is ever set `True`.
   Every validator hands it the arms it actually ran; this module alone
   decides the classification and whether the target proved it
   discriminates between a real and a fake credential.

Mirrors the `scope_guard`/`advance_secret_status` pattern deliberately: one
module, one entry point, no per-caller reimplementation of the
classification rules (SPEC_BRIEF8 FORK-I).

Nothing in this module ever receives or logs a raw secret value — arms
carry only labels, success booleans, HTTP status codes and S3 `Error.Code`
strings (SPEC_BRIEF8 guardrail 6/7).
"""

from __future__ import annotations

import hashlib
import hmac
import string
from dataclasses import dataclass
from typing import Literal, Sequence

Classification = Literal[
    "live_discriminated",
    "not_live",
    "authenticated_not_authorized",
    "indiscriminate_target",
    "self_request_malformed",
    "inconclusive",
]

# FORK-L's DEFAULT: HMAC-derived, shape-preserving, with a fixed,
# non-secret domain-separation label. Deterministic and replayable (same
# real_value/target_id/kind always derives the same control), collision-safe
# against the real value, and not a hardcoded sentinel a target could
# special-case to defeat the control.
_DOMAIN_LABEL = b"KRONOS-NEGATIVE-CONTROL"

_DIGITS = string.digits
_UPPER = string.ascii_uppercase
_LOWER = string.ascii_lowercase


def _replacement_alphabet(ch: str) -> str:
    """The character-class alphabet a derived replacement for `ch` is drawn
    from — digits stay digits, upper/lower letters stay upper/lower, and
    any other character (punctuation, `:`, `-`, …) is kept as-is, so the
    control is always the same shape CLASS as the real value, position by
    position, never just the same length."""
    if ch.isdigit():
        return _DIGITS
    if ch.isupper():
        return _UPPER
    if ch.islower():
        return _LOWER
    return ch


def derive_negative_control(real_value: str, *, target_id: str, kind: str) -> str:
    """A deterministic, shape-preserving value that is structurally
    guaranteed NOT to equal `real_value`: every digit/letter position is
    forced to a *different* character within the same character class
    (and punctuation/separators are kept literally, so `"AK:SK"`-shaped
    values stay `X:Y`-shaped). `target_id`/`kind` domain-separate the
    derivation so the same real value derives a different control against
    a different target or arm role, without making the control any less
    deterministic for a given (real_value, target_id, kind) triple.

    Never random, never a hardcoded sentinel (FORK-L) — purely a function
    of its inputs, so a run is reproducible and attributable.
    """
    if not real_value:
        raise ValueError("derive_negative_control requires a non-empty real_value")

    seed = hmac.new(_DOMAIN_LABEL, f"{kind}|{target_id}|{real_value}".encode(), hashlib.sha256).digest()
    stream = bytearray()
    counter = 0
    while len(stream) < len(real_value):
        stream.extend(hmac.new(_DOMAIN_LABEL, seed + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1

    chars: list[str] = []
    for i, ch in enumerate(real_value):
        alphabet = _replacement_alphabet(ch)
        if len(alphabet) <= 1:
            chars.append(alphabet)
            continue
        index = stream[i] % len(alphabet)
        replacement = alphabet[index]
        if replacement == ch:
            # Force a genuine difference at this position rather than
            # trusting the hash to avoid it by chance.
            replacement = alphabet[(index + 1) % len(alphabet)]
        chars.append(replacement)
    control = "".join(chars)

    if control == real_value:
        # Structurally unreachable for any value containing at least one
        # digit/letter (the per-position guarantee above forces a
        # difference there) — this is a fail-closed guard, not a path
        # expected to ever execute, for a real_value made entirely of
        # characters this function cannot vary (e.g. pure punctuation).
        raise RuntimeError(
            "derive_negative_control degenerated to the real value for this input shape; refusing to return it"
        )
    return control


@dataclass(frozen=True)
class ArmResult:
    """One arm's outcome. Deliberately carries no secret/credential value —
    only what a reader needs to classify the differential: did it succeed,
    what HTTP status, what S3 `Error.Code` (cloud only), and whether a
    transport error or an intentional skip is why there's no status."""

    label: str
    success: bool
    status_code: int | None = None
    error_code: str | None = None
    transport_error: bool = False
    skipped: bool = False


@dataclass(frozen=True)
class DifferentialResult:
    classification: Classification
    live: bool
    discriminated: bool
    control_outcome: str
    detail: str


def _arm_outcome_str(arm: ArmResult) -> str:
    if arm.skipped:
        return f"{arm.label}=skipped"
    if arm.transport_error:
        return f"{arm.label}=transport_error"
    if arm.success:
        return f"{arm.label}=success({arm.status_code})"
    if arm.error_code:
        return f"{arm.label}={arm.error_code}"
    return f"{arm.label}=denied({arm.status_code})"


def run_differential(arms: Sequence[ArmResult], *, kind: Literal["http", "cloud"]) -> DifferentialResult:
    """The only place `discriminated` is ever set `True` (SPEC_BRIEF8
    §3.2). `arms` must be exactly the arms SPEC_BRIEF8 §3.3 (`kind="http"`:
    labels `A_canonical`, `B_negative_control`) or §3.4 (`kind="cloud"`:
    labels `A_canonical`, `B_bad_secret`, `C_unknown_key`) describe —
    callers never invent a different arm set or calling convention
    (FORK-I: one chokepoint, not a rule re-derived per validator).
    """
    by_label = {a.label: a for a in arms}

    # self_request_malformed takes priority over every other
    # classification: a 400 AuthorizationHeaderMalformed on ANY arm means
    # WE built a broken request, not that we learned anything about the
    # target (SPEC_BRIEF7 §3.1a's false-negative guard; SPEC_BRIEF8 §3.4
    # names this explicitly so it is never recorded as a target signal).
    if any(a.error_code == "AuthorizationHeaderMalformed" for a in arms):
        control_outcome = " ".join(_arm_outcome_str(a) for a in arms)
        return DifferentialResult(
            classification="self_request_malformed",
            live=False,
            discriminated=False,
            control_outcome=control_outcome,
            detail="our own request was malformed on at least one arm; not a target signal",
        )

    a = by_label["A_canonical"]

    if kind == "http":
        b = by_label["B_negative_control"]
        control_outcome = _arm_outcome_str(b)
        if a.transport_error and b.transport_error:
            return DifferentialResult(
                "inconclusive", False, False, control_outcome, "both arms hit a transport error"
            )
        if not a.success:
            return DifferentialResult(
                "not_live", False, False, control_outcome, "canonical arm did not succeed"
            )
        if b.success:
            return DifferentialResult(
                "indiscriminate_target",
                False,
                False,
                control_outcome,
                "negative control also succeeded — target does not discriminate",
            )
        return DifferentialResult(
            "live_discriminated",
            True,
            True,
            control_outcome,
            "canonical succeeded, negative control was rejected",
        )

    # kind == "cloud"
    b = by_label["B_bad_secret"]
    c = by_label["C_unknown_key"]
    control_outcome = f"{_arm_outcome_str(b)} {_arm_outcome_str(c)}"

    if a.success:
        if b.success:
            return DifferentialResult(
                "indiscriminate_target",
                False,
                False,
                control_outcome,
                "bad-secret control also succeeded — target is not enforcing auth",
            )
        return DifferentialResult(
            "live_discriminated",
            True,
            True,
            control_outcome,
            "canonical succeeded, both controls were rejected",
        )

    if a.error_code == "AccessDenied":
        if b.error_code == "SignatureDoesNotMatch" and c.error_code == "InvalidAccessKeyId":
            return DifferentialResult(
                "authenticated_not_authorized",
                False,
                True,
                control_outcome,
                "signature verified for a real key, but this bucket denies it",
            )
        if b.error_code == "AccessDenied":
            return DifferentialResult(
                "inconclusive",
                False,
                False,
                control_outcome,
                "canonical and bad-secret both denied identically — target does not discriminate",
            )

    return DifferentialResult("not_live", False, False, control_outcome, "canonical arm did not succeed")
