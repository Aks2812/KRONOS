"""Signed autonomy envelope: pure evaluation (SPEC_BRIEF29).

Representation + pure evaluation ONLY. Nothing here is called by the
dispatcher, an executor, a driver or a tool; there is no runtime, no
watchdog, no `LOCAL` class (O2: A|B|C only). Everything is fail-closed:
absent/malformed/None data denies, and None is never "unlimited".
"""

from __future__ import annotations

import contextvars
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
    "authorize",
    "effective_envelope",
    "in_force_effective_envelope",
    "in_force_manifest",
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
    # Provenance (§8.1(1)): the manifest_id of the VerifiedManifest this envelope
    # was derived from. in_force_effective_envelope() is the only function that
    # sets it; authorize() grants only when it equals verified.manifest_id.
    provenance: str | None = None

    def __post_init__(self) -> None:
        # Construction guard (§8.1(1a)), NOT cryptographic: a module-private
        # ContextVar that only the legitimate producers set, so direct
        # construction and dataclasses.replace() are rejected. In-process code
        # that sets the private token could still bypass it (same documented
        # limitation as VerifiedManifest).
        if not _PRODUCING.get():
            raise AutonomyError("EffectiveEnvelope is produced only by the autonomy producers")


# Module-private construction token (§8.1(1a)): set only inside the producers.
_PRODUCING = contextvars.ContextVar("_kronos_envelope_producing", default=False)


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
    # "none" | "tightening" | "increase" | "mixed" (§7); None when not classified.
    direction: str | None = None


_MODE_RANK = {"calm": 0, "beast": 1}


def _make_envelope(**fields) -> EffectiveEnvelope:
    token = _PRODUCING.set(True)
    try:
        return EffectiveEnvelope(**fields)
    finally:
        _PRODUCING.reset(token)


def _fail_closed_envelope(reason: str | None) -> EffectiveEnvelope:
    return _make_envelope(
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
    (never clamped up). Absent/unusable signed data -> fail-closed Calm.
    NON-authorizing (§8.1(1)): the result carries no provenance, so
    `authorize` denies it; only `in_force_effective_envelope` authorizes."""
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

    return _make_envelope(
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


def _axes(m: VerifiedManifest) -> dict | None:
    """Authority axes of a manifest (§7). Absent autonomy = fail-closed zero
    authority. None if the signed envelope is unusable."""
    env = m.autonomy
    if env is None:
        view = {
            "mode": 0,
            "duration": 0,
            "budget": {d: 0 for d in BUDGET_DIMENSIONS},
            "exfil": (False, 0),
            "watchdog": None,
            "auths": (),
        }
    else:
        if not isinstance(env, AutonomyEnvelope) or env.mode_max not in _MODE_RANK:
            return None
        budget = _budget_dict(env.max_unattended_budget)
        if budget is None or not _num_ok(env.max_unattended_duration_seconds):
            return None
        x = env.exfil_simulation
        view = {
            "mode": _MODE_RANK[env.mode_max],
            "duration": env.max_unattended_duration_seconds,
            "budget": budget,
            "exfil": (bool(x.allowed), x.byte_budget if x.allowed else 0) if x is not None else (False, 0),
            "watchdog": env.watchdog,
            "auths": tuple(env.unattended_authorizations),
        }
    view["destructive"] = m.destructive_allowed is True
    view["in_scope"] = set(m.in_scope)
    view["excluded"] = set(m.excluded)
    return view


def _classify(new: VerifiedManifest, old: VerifiedManifest) -> str | None:
    """Direction of `new` vs `old` over EVERY authority axis (§7): mode_max,
    duration, each budget dim, watchdog, exfil, the authorization set, and
    manifest-level destructive_allowed + in_scope/excluded. None = unusable."""
    try:
        nv, ov = _axes(new), _axes(old)
        if nv is None or ov is None:
            return None
        pairs = [
            (nv["mode"], ov["mode"]),
            (nv["duration"], ov["duration"]),
            *((nv["budget"][d], ov["budget"][d]) for d in BUDGET_DIMENSIONS),
            (nv["exfil"], ov["exfil"]),
            (nv["destructive"], ov["destructive"]),
        ]
        inc = any(n > o for n, o in pairs)
        tight = any(n < o for n, o in pairs)
        if nv["watchdog"] != ov["watchdog"]:
            inc = True  # §7 lists watchdog among permission-increasing changes: any change
        if any(not any(_covers(o, n) for o in ov["auths"]) for n in nv["auths"]):
            inc = True
        if any(not any(_covers(n, o) for n in nv["auths"]) for o in ov["auths"]):
            tight = True
        if nv["in_scope"] - ov["in_scope"] or ov["excluded"] - nv["excluded"]:
            inc = True
        if ov["in_scope"] - nv["in_scope"] or nv["excluded"] - ov["excluded"]:
            tight = True
    except TypeError:
        return None
    if inc and tight:
        return "mixed"
    return "increase" if inc else "tightening" if tight else "none"


def verify_amendment(new: VerifiedManifest, predecessor: VerifiedManifest) -> AmendmentDecision:
    """Valid only for root -> one amendment. Everything else fails closed,
    including a MIXED amendment (≥1 increased AND ≥1 tightened axis, §7)."""
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
    direction = _classify(new, predecessor)
    if direction is None:
        return AmendmentDecision(False, "amendment authority unusable")
    if direction == "mixed":
        return AmendmentDecision(False, "mixed amendment (increase and tightening) is invalid", "mixed")
    return AmendmentDecision(True, "ok", direction)


def in_force_manifest(
    predecessor: VerifiedManifest, amendment: VerifiedManifest | None, now: datetime | None
) -> VerifiedManifest:
    """The governing manifest at `now` (§8.1(2)): the amendment iff it is valid
    AND (tightening-only/no-op, immediate) OR (increase-only AND now >=
    effective_at); otherwise the predecessor (pending, invalid, mixed,
    single-hop-violating)."""
    if amendment is None:
        return predecessor
    decision = verify_amendment(amendment, predecessor)
    if not decision.valid:
        return predecessor
    if decision.direction == "increase" and not (_is_aware(now) and now >= amendment.amends.effective_at):
        return predecessor
    return amendment


def in_force_effective_envelope(
    verified: VerifiedManifest, runtime: RuntimeRestrictions | None = None
) -> EffectiveEnvelope:
    """The ONLY producer of a provenance-bearing (authorizing) envelope
    (§8.1(1)). `verified` must be `in_force_manifest(...)`."""
    if not isinstance(verified, VerifiedManifest):
        return _fail_closed_envelope("manifest is not a VerifiedManifest")
    base = effective_envelope(verified.autonomy, runtime)
    token = _PRODUCING.set(True)
    try:
        return replace(base, provenance=verified.manifest_id)
    finally:
        _PRODUCING.reset(token)


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
    # Caller-MUST (§8.1(2a)): `verified` must be the in-force manifest, i.e. the
    # result of in_force_manifest(...); selecting it is the caller's duty. The
    # (1a) construction guard makes this safe: the only authorizing envelope is
    # one in_force_effective_envelope stamped with that manifest's id, and
    # the provenance check below is the backstop.
    def deny(reason: str) -> AuthorizationResult:
        return AuthorizationResult("DENY", reason)

    if not isinstance(effective, EffectiveEnvelope) or not isinstance(request, AuthorizationRequest):
        return deny("malformed evaluation input")
    if not isinstance(verified, VerifiedManifest):
        return deny("manifest is not a VerifiedManifest")
    # §8.1(1): a bare/non-provenanced or mismatched envelope authorizes nothing.
    if effective.provenance is None or effective.provenance != verified.manifest_id:
        return deny("effective envelope lacks provenance equal to verified.manifest_id")
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
