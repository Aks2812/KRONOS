"""Signed autonomy envelope: pure evaluation (SPEC_BRIEF29).

Representation + pure evaluation ONLY. Nothing here is called by the
dispatcher, an executor, a driver or a tool; there is no runtime, no
watchdog, no `LOCAL` class (O2: A|B|C only). Everything is fail-closed:
absent/malformed/None data denies, and None is never "unlimited".
"""

from __future__ import annotations

import ipaddress
import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, Mapping

from kronos.budget.limits import BUDGET_DIMENSIONS, BudgetLimits
from kronos.manifest import (
    WATCHDOG_CONFIRM_WINDOW_MAX,
    AutonomyEnvelope,
    UnattendedAuthorization,
    UnattendedBudget,
    VerifiedManifest,
    compute_manifest_id,
)
from kronos.scope_guard import (
    NODE_TYPE_SHAPES,
    _effective_shape,
    _matches,
    classify_target,
    scope_guard,
)

__all__ = [
    "WATCHDOG_CONFIRM_WINDOW_MAX",
    "AutonomyError",
    "AmendmentDecision",
    "AuthorizationRequest",
    "AuthorizationResult",
    "EffectiveEnvelope",
    "RuntimeRestrictions",
    "active_envelope",
    "authorize",
    "effective_envelope",
    "to_budget_limits",
    "verify_amendment",
]


class AutonomyError(Exception):
    """Runtime restriction tries to widen signed authority, or bad input."""


@dataclass(frozen=True)
class RuntimeRestrictions:
    """Runtime may only narrow. `None` field = no restriction on that axis."""

    mode_max: str | None = None
    max_unattended_duration_seconds: float | None = None
    budget: Mapping[str, float] | None = None
    authorizations: tuple[UnattendedAuthorization, ...] | None = None
    allow_destructive: bool | None = None
    exfil_allowed: bool | None = None
    exfil_byte_budget: int | None = None


@dataclass(frozen=True)
class EffectiveEnvelope:
    mode_max: str
    authorizations: tuple[UnattendedAuthorization, ...]
    max_unattended_duration_seconds: float
    budget: Mapping[str, float]
    exfil_allowed: bool
    exfil_byte_budget: int
    # Non-None => the signed input was unusable; authorize() denies.
    fail_closed_reason: str | None = None
    # Provenance (§7/§8): set only when a valid amendment INCREASES a permission
    # and is not yet effective. authorize() denies while now < this instant.
    pending_increase_until: datetime | None = None


@dataclass(frozen=True)
class AuthorizationRequest:
    """Target-directed A/B/C request only. No operator-approval field exists."""

    mode: str
    action_class: str
    target: str
    node_type: str
    destructive: bool = False
    budget_draw: Mapping[str, float] | None = None
    session_elapsed_seconds: float | None = None


@dataclass(frozen=True)
class AuthorizationResult:
    verdict: Literal["ALLOW", "DENY", "INCONCLUSIVE"]
    reason: str

    @property
    def allowed(self) -> bool:
        return self.verdict == "ALLOW"


@dataclass(frozen=True)
class AmendmentDecision:
    valid: bool
    reason: str


_MODE_RANK = {"calm": 0, "beast": 1}


def _fail_closed_envelope(reason: str | None) -> EffectiveEnvelope:
    return EffectiveEnvelope(
        mode_max="calm",
        authorizations=(),
        max_unattended_duration_seconds=0,
        budget={d: 0 for d in BUDGET_DIMENSIONS},
        exfil_allowed=False,
        exfil_byte_budget=0,
        fail_closed_reason=reason,
    )


def _num_ok(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _budget_dict(budget: object) -> dict[str, float] | None:
    """All five dims present, finite, non-negative, else None (fail-closed)."""
    if budget is None:
        return None
    out: dict[str, float] = {}
    for dim in BUDGET_DIMENSIONS:
        value = getattr(budget, dim, None)
        if not _num_ok(value):
            return None
        out[dim] = value
    return out


def to_budget_limits(budget: UnattendedBudget) -> BudgetLimits:
    """Evaluation-boundary conversion (§4.1). Never yields a None dimension."""
    values = _budget_dict(budget)
    if values is None:
        raise AutonomyError("unattended budget has a missing/None/invalid dimension")
    return BudgetLimits(**values)


def _covers(signed: UnattendedAuthorization, narrowed: UnattendedAuthorization) -> bool:
    return (
        signed.action_class == narrowed.action_class
        and signed.target == narrowed.target
        and signed.target_node_type == narrowed.target_node_type
        and signed.valid_from <= narrowed.valid_from
        and narrowed.valid_until <= signed.valid_until
        and (signed.destructive or not narrowed.destructive)
    )


def effective_envelope(
    signed: AutonomyEnvelope | None, runtime: RuntimeRestrictions | None
) -> EffectiveEnvelope:
    """Intersection of signed authority and runtime restriction (§8).

    Runtime may only restrict; any widening raises `AutonomyError`
    (never clamped up). Absent/unusable signed data -> fail-closed Calm."""
    if signed is None:
        return _fail_closed_envelope(None)  # absent block: Calm, zero authority (§6)
    if not isinstance(signed, AutonomyEnvelope):
        return _fail_closed_envelope("signed autonomy is not an AutonomyEnvelope")

    budget = _budget_dict(signed.max_unattended_budget)
    duration = signed.max_unattended_duration_seconds
    if budget is None:
        return _fail_closed_envelope("signed unattended budget missing/None/invalid dimension")
    if not _num_ok(duration) or duration <= 0:
        return _fail_closed_envelope("signed unattended duration missing/invalid")
    if signed.mode_max not in _MODE_RANK:
        return _fail_closed_envelope("signed mode_max invalid")

    mode_max = signed.mode_max
    auths = tuple(signed.unattended_authorizations)
    exfil = signed.exfil_simulation
    exfil_allowed = bool(exfil.allowed) if exfil is not None else False
    exfil_bytes = exfil.byte_budget if (exfil is not None and exfil_allowed) else 0

    if runtime is not None:
        if runtime.mode_max is not None:
            if runtime.mode_max not in _MODE_RANK:
                raise AutonomyError("runtime mode_max invalid")
            if _MODE_RANK[runtime.mode_max] > _MODE_RANK[mode_max]:
                raise AutonomyError("runtime mode_max exceeds signed authority")
            mode_max = runtime.mode_max
        if runtime.max_unattended_duration_seconds is not None:
            r = runtime.max_unattended_duration_seconds
            if not _num_ok(r):
                raise AutonomyError("runtime max_unattended_duration_seconds invalid")
            if r > duration:
                raise AutonomyError("runtime max_unattended_duration_seconds exceeds signed authority")
            duration = r
        if runtime.budget is not None:
            for dim, r in runtime.budget.items():
                if dim not in BUDGET_DIMENSIONS:
                    raise AutonomyError(f"runtime budget dimension {dim!r} unknown")
                if not _num_ok(r):
                    raise AutonomyError(f"runtime {dim} invalid")
                if r > budget[dim]:
                    raise AutonomyError(f"runtime {dim} exceeds signed authority")
                budget[dim] = r
        if runtime.authorizations is not None:
            for entry in runtime.authorizations:
                if not any(_covers(s, entry) for s in auths):
                    raise AutonomyError("runtime authorization not covered by signed authority")
            auths = tuple(runtime.authorizations)
        if runtime.allow_destructive is not None:
            if runtime.allow_destructive and not any(a.destructive for a in auths):
                raise AutonomyError("runtime enables destructive over signed-disabled")
            if not runtime.allow_destructive:
                auths = tuple(a.model_copy(update={"destructive": False}) for a in auths)
        if runtime.exfil_allowed is not None:
            if runtime.exfil_allowed and not exfil_allowed:
                raise AutonomyError("runtime enables exfil over signed-disabled")
            if not runtime.exfil_allowed:
                exfil_allowed, exfil_bytes = False, 0
        if runtime.exfil_byte_budget is not None:
            r = runtime.exfil_byte_budget
            if not _num_ok(r):
                raise AutonomyError("runtime exfil_byte_budget invalid")
            if r > exfil_bytes:
                raise AutonomyError("runtime exfil_byte_budget exceeds signed authority")
            exfil_bytes = r

    return EffectiveEnvelope(
        mode_max=mode_max,
        authorizations=auths,
        max_unattended_duration_seconds=duration,
        budget=budget,
        exfil_allowed=exfil_allowed,
        exfil_byte_budget=exfil_bytes,
    )


# ---- amendments (bounded single-hop, §7) ----


def _is_aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None


def verify_amendment(new: VerifiedManifest, predecessor: VerifiedManifest) -> AmendmentDecision:
    """Valid only for root -> one amendment. Everything else fails closed."""
    if not isinstance(predecessor, VerifiedManifest) or not isinstance(new, VerifiedManifest):
        return AmendmentDecision(False, "both manifests must be VerifiedManifest")
    if predecessor.amends is not None:
        return AmendmentDecision(False, "predecessor is itself an amendment (single-hop only)")
    ref = new.amends
    if ref is None:
        return AmendmentDecision(False, "manifest is not an amendment")
    if not ref.manifest_id or not ref.reason:
        return AmendmentDecision(False, "amendment manifest_id/reason empty")
    if not _is_aware(ref.effective_at):
        return AmendmentDecision(False, "amendment effective_at missing/naive")
    if ref.manifest_id != compute_manifest_id(predecessor):
        return AmendmentDecision(False, "amendment manifest_id does not match predecessor")
    return AmendmentDecision(True, "ok")


def _more_permissive(new: AutonomyEnvelope | None, old: AutonomyEnvelope | None) -> bool:
    """True if `new` grants anything `old` does not."""
    if new is None:
        return False
    if old is None:
        # old = fail-closed Calm with zero authority: any grant is an increase.
        return True
    if _MODE_RANK.get(new.mode_max, 99) > _MODE_RANK.get(old.mode_max, 99):
        return True
    if new.max_unattended_duration_seconds > old.max_unattended_duration_seconds:
        return True
    for dim in BUDGET_DIMENSIONS:
        if getattr(new.max_unattended_budget, dim) > getattr(old.max_unattended_budget, dim):
            return True
    if new.watchdog != old.watchdog:
        # §7: watchdog changes count as increases (conservative: any change).
        return True
    old_x, new_x = old.exfil_simulation, new.exfil_simulation
    if new_x is not None and new_x.allowed:
        if old_x is None or not old_x.allowed or new_x.byte_budget > old_x.byte_budget:
            return True
    return any(
        not any(_covers(o, n) for o in old.unattended_authorizations) for n in new.unattended_authorizations
    )


def active_envelope(
    root: VerifiedManifest, amendment: VerifiedManifest | None, now: datetime
) -> AutonomyEnvelope | None:
    """The signed envelope in force at `now`.

    No/invalid amendment -> the root's (invalid amendments never downgrade
    or upgrade). A valid amendment that only tightens applies at once;
    one that increases any permission applies only from `effective_at`."""
    if amendment is None:
        return root.autonomy
    if not verify_amendment(amendment, root).valid:
        return root.autonomy
    if not _more_permissive(amendment.autonomy, root.autonomy):
        return amendment.autonomy
    if _is_aware(now) and now >= amendment.amends.effective_at:
        return amendment.autonomy
    return root.autonomy


def in_force_effective_envelope(
    root: VerifiedManifest,
    amendment: VerifiedManifest | None,
    now: datetime,
    runtime: RuntimeRestrictions | None = None,
) -> EffectiveEnvelope:
    """Envelope selection + provenance (§7/§8). Tightening or no/invalid
    amendment: `pending_increase_until` None. A valid INCREASING amendment not
    yet effective: predecessor (root) envelope, gated until `effective_at`."""
    eff = effective_envelope(active_envelope(root, amendment, now), runtime)
    pending = None
    if (
        amendment is not None
        and verify_amendment(amendment, root).valid
        and _more_permissive(amendment.autonomy, root.autonomy)
        and not (_is_aware(now) and now >= amendment.amends.effective_at)
    ):
        pending = amendment.amends.effective_at
    return replace(eff, pending_increase_until=pending)


# ---- authorize (§8) ----


def _exact_literal(target: object) -> bool:
    if not isinstance(target, str) or not target or target != target.strip():
        return False
    if any(ch in target for ch in "*?["):
        return False
    if "/" in target:
        try:
            ipaddress.ip_network(target, strict=False)
        except ValueError:
            pass
        else:
            return False  # CIDR is a pattern, not a concrete identifier
    return True


def _auth_binds(auth: UnattendedAuthorization, request: AuthorizationRequest) -> bool:
    """Per-authorization binding (§4.2): _matches on the selected auth plus
    matching classified shapes. Engagement scope is checked separately."""
    if auth.action_class != request.action_class or auth.target_node_type != request.node_type:
        return False
    if not _exact_literal(auth.target):
        return False
    shape = classify_target(request.target)
    if classify_target(auth.target) != shape:
        return False
    return _matches(auth.target, request.target, is_exclusion=False, shape=shape)


def authorize(
    effective: EffectiveEnvelope,
    request: AuthorizationRequest,
    verified: VerifiedManifest,
    now: datetime | None,
) -> AuthorizationResult:
    def deny(reason: str) -> AuthorizationResult:
        return AuthorizationResult("DENY", reason)

    if not isinstance(effective, EffectiveEnvelope) or not isinstance(request, AuthorizationRequest):
        return deny("malformed evaluation input")
    if not isinstance(verified, VerifiedManifest):
        return deny("manifest is not a VerifiedManifest")
    if effective.fail_closed_reason is not None:
        return deny(f"fail-closed: {effective.fail_closed_reason}")
    if request.action_class not in ("A", "B", "C"):
        return deny("unknown action class")
    if request.mode not in _MODE_RANK:
        return deny("unknown mode")
    if _MODE_RANK[request.mode] > _MODE_RANK.get(effective.mode_max, 0):
        return deny("request mode exceeds effective mode_max")
    if request.mode == "calm" and request.action_class != "A":
        # No trusted operator-approval boundary yet: Calm B/C fails closed.
        return deny("Calm mode: class B/C requires operator approval (deferred)")
    if not isinstance(request.target, str) or not isinstance(request.node_type, str):
        return deny("malformed request target")
    if not isinstance(request.destructive, bool):
        return deny("malformed destructive flag")

    # Engagement scope is necessary but never sufficient.
    if not scope_guard(request.target, verified, node_type=request.node_type, target_kind="id"):
        return deny("target not in engagement scope")
    if request.node_type not in NODE_TYPE_SHAPES or (
        _effective_shape(request.target, request.node_type) not in NODE_TYPE_SHAPES[request.node_type]
    ):
        return deny("target outside node-type family")

    candidates = [a for a in effective.authorizations if _auth_binds(a, request)]
    if not candidates:
        return deny("no matching unattended authorization")

    if not _is_aware(now) and now is not None:
        return deny("now is not timezone-aware")
    # §7/§8: an increasing amendment grants nothing before its effective_at.
    # Self-contained: reads only the in-force envelope's provenance.
    if effective.pending_increase_until is not None:
        if not _is_aware(effective.pending_increase_until):
            return deny("pending increase effective_at naive")
        if now is not None and now < effective.pending_increase_until:
            return deny("amendment increase not yet effective")
    unavailable: list[str] = []
    if now is None:
        unavailable.append("now")

    # budget draw / elapsed
    draw = request.budget_draw
    if draw is None:
        unavailable.append("budget_draw")
    else:
        for dim in BUDGET_DIMENSIONS:
            if dim not in draw:
                unavailable.append(f"budget_draw.{dim}")
            elif not _num_ok(draw[dim]):
                return deny(f"budget draw {dim} invalid")
            elif draw[dim] > effective.budget.get(dim, -1):
                return deny(f"budget draw {dim} exceeds effective budget")
    if request.session_elapsed_seconds is None:
        unavailable.append("session_elapsed_seconds")
    elif not _num_ok(request.session_elapsed_seconds):
        return deny("session elapsed invalid")
    elif request.session_elapsed_seconds > effective.max_unattended_duration_seconds:
        return deny("session duration exceeds effective maximum")

    # per-authorization window + destructive; any candidate passing wins
    chosen = False
    for auth in candidates:
        if now is not None:
            if not (_is_aware(auth.valid_from) and _is_aware(auth.valid_until)):
                continue
            if not (auth.valid_from <= now <= auth.valid_until):
                continue
        if request.destructive and not (verified.destructive_allowed is True and auth.destructive is True):
            continue
        chosen = True
        break
    if not chosen:
        return deny("no authorization active/destructive-permitting for request")
    if unavailable:
        return AuthorizationResult("INCONCLUSIVE", "required evaluation input unavailable: " + ", ".join(unavailable))
    return AuthorizationResult("ALLOW", "ok")
