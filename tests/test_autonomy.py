"""SPEC_BRIEF29 (hermetic): signed autonomy envelope, pure evaluation.

Every expected verdict derives from the brief prose (section noted per cell),
never from observed behaviour. No `hypothesis` (D5): generators are
deterministic itertools/random(seed) enumerations."""

from __future__ import annotations

import copy
import dataclasses
import dataclasses
from dataclasses import replace as _plain_replace
import inspect
import itertools
import random
import socket
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from kronos import autonomy as A
from kronos.autonomy import (
    AuthorizationRequest,
    EffectiveEnvelope,
    AutonomyError,
    RuntimeRestrictions,
    authorize,
    effective_envelope,
    in_force_effective_envelope,
    in_force_manifest,
    to_budget_limits,
    verify_amendment,
)
from kronos.budget.limits import BUDGET_DIMENSIONS, BudgetLimits
from kronos.manifest import (
    AmendmentRef,
    UnattendedAuthorization,
    compute_manifest_id,
    load_and_verify,
)

NOW = datetime.now(timezone.utc)
PAST = NOW - timedelta(days=2)
FUTURE = NOW + timedelta(days=2)
TARGET = "host.acme.example.com"  # in engagement scope *.acme.example.com (factory)
OTHER = "other.acme.example.com"
BUDGET = {
    "validation_attempts": 5,
    "tool_invocations": 10,
    "wall_clock_seconds": 60.0,
    "llm_tokens": 1000,
    "llm_cost_usd": 1.5,
}
WITHIN = {k: v for k, v in BUDGET.items()}
OVER = {**BUDGET, "llm_tokens": 1001}


def auth(cls="A", target=TARGET, vf=PAST, vu=FUTURE, destructive=False, node="HOST"):
    return {
        "action_class": cls,
        "target": target,
        "target_node_type": node,
        "valid_from": vf.isoformat(),
        "valid_until": vu.isoformat(),
        "destructive": destructive,
    }


def auto(auths=None, mode="beast", duration=600, budget=None, **kw):
    return {
        "mode_max": mode,
        "unattended_authorizations": [auth()] if auths is None else auths,
        "max_unattended_duration_seconds": duration,
        "max_unattended_budget": dict(BUDGET if budget is None else budget),
        **kw,
    }


@pytest.fixture
def nonet(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)


@pytest.fixture
def load(manifest_factory, signing_keypair):
    _, pub = signing_keypair

    def _l(autonomy=None, amends=None, **ov):
        return load_and_verify(manifest_factory(autonomy=autonomy, amends=amends, **ov), pub)

    return _l


def req(mode="beast", cls="A", target=TARGET, destructive=False, draw=WITHIN, elapsed=1.0, node="HOST"):
    return AuthorizationRequest(
        mode=mode,
        action_class=cls,
        target=target,
        node_type=node,
        destructive=destructive,
        budget_draw=draw,
        session_elapsed_seconds=elapsed,
    )


def run(verified, request, runtime=None, now=NOW):
    eff = in_force_effective_envelope(verified, runtime)  # §8.1: sole authorizing producer
    return authorize(eff, request, verified, now)


# ---------------------------------------------------------------- decision table (§13)
# (row, autonomy-kwargs, request-kwargs, verified-engagement-overrides, expected)
D_OK = {"destructive_allowed": True}


@pytest.mark.parametrize(
    "row,a_kw,r_kw,ov,expected",
    [
        # Each row: expected verdict derives from the cited §8 clause / decision-table row (brief prose).
        # row1: §8 class rule A ("allowed in calm or beast within limits") + mode clause (calm req <= calm ceiling)
        (1, dict(mode="calm", auths=[auth("A")]), dict(mode="calm", cls="A"), {}, "ALLOW"),
        # row2: §8 class rule A in beast; mode clause (beast req needs mode_max==beast)
        (2, dict(), dict(mode="beast", cls="A"), {}, "ALLOW"),
        # row3: §8 class rule A "ALWAYS requires a matching signed authorization"; scope != authz
        (3, dict(auths=[auth("A", OTHER)]), dict(cls="A"), {}, "DENY"),
        # row4: §8 class rule B "calm => DENY (fail closed, P0)"
        (4, dict(auths=[auth("B")]), dict(mode="calm", cls="B"), {}, "DENY"),
        # row5: §8 class rule B "beast => allow iff a matching signed authorization exists"
        (5, dict(auths=[auth("B")]), dict(cls="B"), {}, "ALLOW"),
        # row6: §8 class rule B needs a matching auth of class B (only A present)
        (6, dict(auths=[auth("A")]), dict(cls="B"), {}, "DENY"),
        # row7: §8 class rule C "calm => DENY (per-action operator authorization deferred)"
        (7, dict(auths=[auth("C")]), dict(mode="calm", cls="C"), {}, "DENY"),
        # row8: §8 class rule C "beast => allow iff manifest EXPLICITLY enumerates (C, target, active window)"
        (8, dict(auths=[auth("C")]), dict(cls="C"), {}, "ALLOW"),
        # row9: §8 class rule C: no explicit C entry => DENY
        (9, dict(auths=[auth("A"), auth("B")]), dict(cls="C"), {}, "DENY"),
        # row10: §8 binding clause + §4.2 per-auth _matches: auth for OTHER never authorizes TARGET
        (10, dict(auths=[auth("A", OTHER)]), dict(cls="A", target=TARGET), {}, "DENY"),
        # row11: §8 binding / §4.2 "wildcard rejected this increment"
        (11, dict(auths=[auth("A", "*.acme.example.com")]), dict(cls="A"), {}, "DENY"),
        # row12: §8 window clause "Future ... => deny" (valid_from > now)
        (12, dict(auths=[auth("A", vf=FUTURE, vu=FUTURE + timedelta(days=1))]), dict(), {}, "DENY"),
        # row13: §8 window clause "expired => deny" (valid_until < now)
        (13, dict(auths=[auth("A", vf=PAST - timedelta(days=1), vu=PAST)]), dict(), {}, "DENY"),
        # row14: §8 budget clause "request draw <= effective budget per dimension"
        (14, dict(), dict(draw=OVER), {}, "DENY"),
        # row16: §8 destructive clause: destructive_allowed AND auth.destructive both true
        (16, dict(auths=[auth("C", destructive=True)]), dict(cls="C", destructive=True), D_OK, "ALLOW"),
        # row17: §8 destructive clause: verified.destructive_allowed false => DENY
        (17, dict(auths=[auth("C", destructive=True)]), dict(cls="C", destructive=True), {}, "DENY"),
        # row18: §8 destructive clause: auth.destructive false => DENY (not inherited)
        (18, dict(auths=[auth("C", destructive=False)]), dict(cls="C", destructive=True), D_OK, "DENY"),
        # row29: §8 inconclusive clause: required input (budget_draw) unavailable => INCONCLUSIVE
        (29, dict(), dict(draw=None), {}, "INCONCLUSIVE"),
    ],
)
def test_B29_G_decision_table(load, row, a_kw, r_kw, ov, expected):
    v = load(autonomy=auto(**a_kw), engagement=ov)
    assert run(v, req(**r_kw)).verdict == expected, f"row {row}"


def replace(env, **changes):
    """Test-only: sets the module-private construction token (§8.1(1a)) so tests can
    build mismatched-provenance variants. This DOCUMENTS the non-cryptographic
    limitation (in-process code setting the token bypasses the guard); it does not
    defeat it. Direct/unsetted dataclasses.replace is asserted to raise below."""
    import kronos.autonomy as _a

    tok = _a._PRODUCING.set(True)
    try:
        return _plain_replace(env, **changes)
    finally:
        _a._PRODUCING.reset(tok)


# row15: §8 budget clause + 4.1 boundary: a None/missing dimension is never unlimited => DENY; conversion raises AutonomyError
def test_B29_G_row15_none_budget_dim_denies_not_unlimited(load):
    v = load(autonomy=auto())
    broken = v.autonomy.max_unattended_budget.model_construct(**{**BUDGET, "llm_tokens": None})
    env = v.autonomy.model_copy(update={"max_unattended_budget": broken})
    eff = replace(effective_envelope(env, None), provenance=v.manifest_id)  # provenance ok: isolates the None-dim deny
    assert authorize(eff, req(draw={**WITHIN, "llm_tokens": 10**12}), v, NOW).verdict == "DENY"
    assert authorize(eff, req(), v, NOW).verdict == "DENY"
    with pytest.raises(AutonomyError):
        to_budget_limits(broken)


# row19: §6/§8 absent autonomy block => fail-closed Calm with zero authority => DENY for every mode x class
def test_B29_G_row19_absent_autonomy_fail_closed_calm(load):
    v = load()
    assert v.autonomy is None
    eff = in_force_effective_envelope(v, None)
    assert eff.mode_max == "calm" and eff.authorizations == ()
    for mode, cls in itertools.product(("calm", "beast"), "ABC"):
        assert authorize(eff, req(mode=mode, cls=cls), v, NOW).verdict == "DENY"


# row20: §8 unusable signed input (non-AutonomyEnvelope) => fail-closed => DENY
def test_B29_G_row20_malformed_autonomy_fail_closed(load):
    v = load()
    for bad in ({"mode_max": "beast"}, "beast", 5, object()):
        eff = replace(effective_envelope(bad, None), provenance=v.manifest_id)
        assert authorize(eff, req(), v, NOW).verdict == "DENY"


# row21: §5 signature verification precedes any evaluation: tampered content => ManifestError
def test_B29_G_row21_invalid_signature_is_manifest_error(manifest_factory, signing_keypair):
    from kronos.manifest import ManifestError

    _, pub = signing_keypair
    y = manifest_factory(autonomy=auto())
    with pytest.raises(ManifestError):
        load_and_verify(y.replace("llm_tokens: 1000", "llm_tokens: 9999"), pub)


# row22: §8 effective = min(signed, runtime): runtime below signed is allowed, nothing beyond the min
def test_B29_G_row22_runtime_below_signed_allowed_effective_min(load):
    v = load(autonomy=auto())
    rt = RuntimeRestrictions(budget={"llm_tokens": 500}, max_unattended_duration_seconds=100)
    eff = in_force_effective_envelope(v, rt)
    assert eff.budget["llm_tokens"] == 500 and eff.budget["tool_invocations"] == 10
    assert eff.max_unattended_duration_seconds == 100
    assert authorize(eff, req(draw={**WITHIN, "llm_tokens": 400}), v, NOW).verdict == "ALLOW"
    assert authorize(eff, req(draw={**WITHIN, "llm_tokens": 501}), v, NOW).verdict == "DENY"  # nothing beyond S/R min


# row23: §8 runtime may only restrict: runtime above signed raises AutonomyError (never clamped up)
def test_B29_G_row23_runtime_above_signed_raises(load):
    v = load(autonomy=auto())
    with pytest.raises(AutonomyError, match="exceeds signed authority"):
        effective_envelope(v.autonomy, RuntimeRestrictions(budget={"llm_tokens": 1001}))


# ---------------------------------------------------------------- F: no silent widening
def test_B29_F_widening_all_axes_raise(load):
    v = load(
        autonomy=auto(
            mode="calm",
            auths=[auth("A", destructive=False)],
            exfil_simulation={"allowed": False, "byte_budget": 0},
        )
    )
    S = v.autonomy
    for rt in (
        RuntimeRestrictions(mode_max="beast"),  # mode
        RuntimeRestrictions(max_unattended_duration_seconds=601),  # duration
        RuntimeRestrictions(budget={d: BUDGET[d] + 1 for d in BUDGET_DIMENSIONS}),
        *[RuntimeRestrictions(budget={d: BUDGET[d] + 1}) for d in BUDGET_DIMENSIONS],
        RuntimeRestrictions(authorizations=(UnattendedAuthorization(**auth("B")),)),  # not covered
        RuntimeRestrictions(authorizations=(UnattendedAuthorization(**auth("A", OTHER)),)),
        RuntimeRestrictions(authorizations=(UnattendedAuthorization(**auth("A", vu=FUTURE + timedelta(days=9))),)),
        RuntimeRestrictions(authorizations=(UnattendedAuthorization(**auth("A", destructive=True)),)),
        RuntimeRestrictions(allow_destructive=True),  # signed-disabled
        RuntimeRestrictions(exfil_allowed=True),
        RuntimeRestrictions(exfil_byte_budget=1),
    ):
        with pytest.raises(AutonomyError):
            effective_envelope(S, rt)


def test_B29_F_narrowing_ok_and_never_clamps_up(load):
    v = load(autonomy=auto(auths=[auth("A"), auth("B")]))
    narrowed = (UnattendedAuthorization(**auth("A", vf=PAST + timedelta(hours=1))),)
    eff = in_force_effective_envelope(v, RuntimeRestrictions(mode_max="calm", authorizations=narrowed))
    assert eff.mode_max == "calm" and eff.authorizations == narrowed
    assert effective_envelope(v.autonomy, RuntimeRestrictions(authorizations=())).authorizations == ()
    # equal is not widening
    eff = in_force_effective_envelope(v, RuntimeRestrictions(budget=dict(BUDGET), max_unattended_duration_seconds=600))
    assert eff.budget == BUDGET


def test_B29_F_runtime_destructive_disable_strips_grant(load):
    v = load(autonomy=auto(auths=[auth("C", destructive=True)]), engagement=D_OK)
    eff = in_force_effective_envelope(v, RuntimeRestrictions(allow_destructive=False))
    assert authorize(eff, req(cls="C", destructive=True), v, NOW).verdict == "DENY"


# ---------------------------------------------------------------- budget conversion (§4.1)
def test_B29_budget_conversion(load):
    v = load(autonomy=auto())
    lim = to_budget_limits(v.autonomy.max_unattended_budget)
    assert isinstance(lim, BudgetLimits)
    assert all(getattr(lim, d) is not None for d in BUDGET_DIMENSIONS)
    assert lim.llm_tokens == 1000


# ---------------------------------------------------------------- tz / window / elapsed
def test_B29_window_inclusive_and_naive_now_denied(load):
    v = load(autonomy=auto(auths=[auth("A", vf=NOW - timedelta(hours=1), vu=NOW + timedelta(hours=1))]))
    eff = in_force_effective_envelope(v, None)
    assert authorize(eff, req(), v, NOW - timedelta(hours=1)).verdict == "ALLOW"  # §8 <= inclusive
    assert authorize(eff, req(), v, NOW + timedelta(hours=1)).verdict == "ALLOW"
    assert authorize(eff, req(), v, NOW + timedelta(hours=1, seconds=1)).verdict == "DENY"
    assert authorize(eff, req(), v, NOW - timedelta(hours=1, seconds=1)).verdict == "DENY"
    assert authorize(eff, req(), v, datetime(2030, 1, 1)).verdict == "DENY"  # naive


def test_B29_duration_elapsed(load):
    v = load(autonomy=auto())
    eff = in_force_effective_envelope(v, None)
    assert authorize(eff, req(elapsed=600), v, NOW).verdict == "ALLOW"  # <=
    assert authorize(eff, req(elapsed=600.5), v, NOW).verdict == "DENY"
    assert authorize(eff, req(elapsed=None), v, NOW).verdict == "INCONCLUSIVE"


def test_B29_inconclusive_when_now_or_partial_draw_missing(load):
    v = load(autonomy=auto())
    eff = in_force_effective_envelope(v, None)
    assert authorize(eff, req(), v, None).verdict == "INCONCLUSIVE"
    partial = {k: v_ for k, v_ in WITHIN.items() if k != "llm_cost_usd"}
    assert authorize(eff, req(draw=partial), v, NOW).verdict == "INCONCLUSIVE"


def test_B29_deny_beats_inconclusive(load):
    v = load(autonomy=auto())
    eff = in_force_effective_envelope(v, None)
    assert authorize(eff, req(draw=OVER, elapsed=None), v, NOW).verdict == "DENY"


# ---------------------------------------------------------------- mode as grant (#1)
def test_B29_request_mode_above_mode_max_denied(load):
    v = load(autonomy=auto(mode="calm", auths=[auth("A")]))
    eff = in_force_effective_envelope(v, None)
    assert authorize(eff, req(mode="beast"), v, NOW).verdict == "DENY"
    assert authorize(eff, req(mode="calm"), v, NOW).verdict == "ALLOW"


def test_B29_unknown_class_mode_denied(load):
    v = load(autonomy=auto())
    eff = in_force_effective_envelope(v, None)
    assert authorize(eff, req(cls="LOCAL"), v, NOW).verdict == "DENY"
    assert authorize(eff, req(cls="D"), v, NOW).verdict == "DENY"
    assert authorize(eff, req(mode="god"), v, NOW).verdict == "DENY"


# ---------------------------------------------------------------- #12 forged operator approval / L: no LOCAL
def test_B29_L_no_local_and_no_operator_field():
    fields = {f.name for f in dataclasses.fields(AuthorizationRequest)}
    assert not any("operator" in f or "local" in f or "approv" in f for f in fields)
    src = inspect.getsource(A)
    assert "LOCAL" not in src.replace("`LOCAL`", "")
    with pytest.raises(TypeError):
        AuthorizationRequest(mode="calm", action_class="B", target=TARGET, node_type="HOST", operator_triggered=True)
    with pytest.raises(Exception):
        UnattendedAuthorization(**auth("LOCAL"))


# ---------------------------------------------------------------- engagement scope necessary, not sufficient
def test_B29_scope_necessary(load):
    v = load(autonomy=auto(auths=[auth("A", "evil.example.org")]))
    eff = in_force_effective_envelope(v, None)
    assert authorize(eff, req(target="evil.example.org"), v, NOW).verdict == "DENY"  # auth, but out of scope
    v2 = load(autonomy=auto(auths=[auth("A", TARGET)]), scope={"excluded": [TARGET]})
    assert run(v2, req()).verdict == "DENY"  # excluded-first


def test_B29_node_type_must_match_and_family(load):
    v = load(autonomy=auto(auths=[auth("A", node="HOST")]))
    eff = in_force_effective_envelope(v, None)
    assert authorize(eff, req(node="SERVICE"), v, NOW).verdict == "DENY"  # auth for HOST only
    assert authorize(eff, req(node="NOPE"), v, NOW).verdict == "DENY"


# ---------------------------------------------------------------- #13 cross-identifier / adversarial target forms
@pytest.mark.parametrize(
    "t",
    [
        "10.0.0.0/8",  # CIDR pattern is not a concrete identifier
        "host.acme.example.com*",
        "host?.acme.example.com",
        "host[1].acme.example.com",
        " host.acme.example.com",
        "host.acme.example.com ",
        "",
    ],
)
def test_B29_nonconcrete_auth_target_never_authorizes(load, t):
    v = load(autonomy=auto(auths=[auth("A", t)]))
    eff = in_force_effective_envelope(v, None)
    assert authorize(eff, req(), v, NOW).verdict == "DENY"


@pytest.mark.parametrize("t", ["HOST.acme.example.com.evil.org", "host.acme.example.com:8443", "https://host.acme.example.com/x", "10.0.0.5"])
def test_B29_literal_auth_does_not_cross_identifier_boundary(load, t):
    v = load(autonomy=auto(auths=[auth("A", TARGET)]))
    eff = in_force_effective_envelope(v, None)
    assert authorize(eff, req(target=t), v, NOW).verdict == "DENY"


# ---------------------------------------------------------------- _matches regression pin (D3)
def test_B29_matches_pin():
    from kronos.scope_guard import _matches, classify_target

    sig = inspect.signature(_matches)
    assert list(sig.parameters) == ["pattern", "target", "is_exclusion", "shape"]
    assert sig.parameters["is_exclusion"].kind is inspect.Parameter.KEYWORD_ONLY

    def m(p, t):
        return _matches(p, t, is_exclusion=False, shape=classify_target(t))

    assert m("host.acme.example.com", "host.acme.example.com") is True  # exact literal
    assert m("host.acme.example.com", "other.acme.example.com") is False
    assert m("host.acme.example.com", "host.acme.example.com.evil.org") is False
    assert m("*.acme.example.com", "host.acme.example.com") is True  # wildcard still a pattern
    assert m("*.acme.example.com", "acme.example.com") is False
    assert m("10.0.0.5", "10.0.0.5") is True
    assert m("10.0.0.5", "10.0.0.6") is False


# ---------------------------------------------------------------- amendments (§7, §8.1)
def _forge(m, **update):
    """Test-only: bypass the §5 construction guard via the module-private token to build malformed amendments."""
    from kronos import manifest as _mf

    tok = _mf._CONSTRUCTING.set(True)
    try:
        return m.model_copy(update=update)
    finally:
        _mf._CONSTRUCTING.reset(tok)


def _chain(load, root_auto, amend_auto, root_ov=None, amd_ov=None, **am):
    root = load(autonomy=root_auto, **(root_ov or {}))
    ref = {"manifest_id": root.manifest_id, "reason": "r", "effective_at": NOW.isoformat(), **am}
    return root, load(autonomy=amend_auto, amends=ref, **(amd_ov or {}))


def run_in_force(root, amd, request, now, runtime=None):
    """The §8.1 pipeline: in_force_manifest -> in_force_effective_envelope -> authorize, ONE manifest for all inputs."""
    iv = in_force_manifest(root, amd, now)
    return authorize(in_force_effective_envelope(iv, runtime), request, iv, now)


def test_B29_M_verify_amendment_ok_and_failures(load):
    root, amd = _chain(load, auto(), auto())
    d = verify_amendment(amd, root)
    assert d.valid and d.direction == "none"  # §7: no-op amendment is valid
    # mismatched id
    bad = load(autonomy=auto(), amends={"manifest_id": "deadbeef", "reason": "r", "effective_at": NOW.isoformat()})
    assert not verify_amendment(bad, root).valid
    # not an amendment
    assert not verify_amendment(root, root).valid
    # predecessor itself an amendment (D1 single hop)
    amd2 = load(autonomy=auto(), amends={"manifest_id": amd.manifest_id, "reason": "r", "effective_at": NOW.isoformat()})
    assert not verify_amendment(amd2, amd).valid
    # bare parsed object not accepted
    from kronos.manifest import ScopeManifest

    bare = ScopeManifest(**dict(root))
    assert not verify_amendment(amd, bare).valid
    assert not verify_amendment(bare, root).valid


def test_B29_M_naive_or_missing_effective_at_fail_closed(load):
    root, amd = _chain(load, auto(), auto())
    naive_ref = AmendmentRef.model_construct(
        manifest_id=root.manifest_id, reason="r", effective_at=datetime(2030, 1, 1)
    )
    n = _forge(amd, amends=naive_ref)
    assert not verify_amendment(n, root).valid
    n2 = _forge(amd, amends=AmendmentRef.model_construct(manifest_id=root.manifest_id, reason="r", effective_at=None))
    assert not verify_amendment(n2, root).valid
    n3 = _forge(amd, amends=AmendmentRef.model_construct(manifest_id="", reason="r", effective_at=NOW))
    assert not verify_amendment(n3, root).valid
    n4 = _forge(amd, amends=AmendmentRef.model_construct(manifest_id=root.manifest_id, reason="", effective_at=NOW))
    assert not verify_amendment(n4, root).valid
    # row 28: naive effective_at => an increase never applies, even long after
    inc = _forge(n, autonomy=load(autonomy=auto(auths=[auth("A"), auth("B")])).autonomy)
    assert in_force_manifest(root, inc, NOW + timedelta(days=99)) is root
    assert run_in_force(root, inc, req(cls="B"), NOW + timedelta(days=1)).verdict == "DENY"


def test_B29_M_rows_24_25_30_increase_only_pending_window(load):
    eff_at = NOW + timedelta(hours=1)
    before = eff_at - timedelta(seconds=1)
    root, amd = _chain(
        load, auto(auths=[auth("A")]), auto(auths=[auth("A"), auth("B")]), effective_at=eff_at.isoformat()
    )
    assert verify_amendment(amd, root).direction == "increase"  # §7: only an added grant
    assert in_force_manifest(root, amd, before) is root  # §8.1(2): predecessor before effective_at
    assert in_force_manifest(root, amd, eff_at) is amd  # §8.1(2): now >= effective_at
    # row 25: increase only via the amendment, now < effective_at => DENY (increase not yet effective)
    assert run_in_force(root, amd, req(cls="B"), before).verdict == "DENY"
    # row 30: a request the PREDECESSOR already grants is ALLOWed during the pending window (no blanket deny)
    assert run_in_force(root, amd, req(cls="A"), before).verdict == "ALLOW"
    assert run_in_force(root, amd, req(cls="A"), NOW).verdict == "ALLOW"
    # row 24: at/after effective_at the increase is in force
    assert run_in_force(root, amd, req(cls="B"), eff_at).verdict == "ALLOW"
    assert run_in_force(root, amd, req(cls="A"), eff_at).verdict == "ALLOW"
    # fail-closed on an unusable clock for a pending increase: predecessor stays in force
    assert in_force_manifest(root, amd, None) is root
    assert in_force_manifest(root, amd, datetime(2099, 1, 1)) is root  # naive now


def test_B29_M_row26_27_broken_and_chained_amendment_keep_predecessor(load):
    root = load(autonomy=auto(auths=[auth("A")]))
    # row 26: id mismatch -> neither an upgrade nor a downgrade-by-invalidation
    bad_inc = load(
        autonomy=auto(auths=[auth("A"), auth("B")]),
        amends={"manifest_id": "wrong", "reason": "r", "effective_at": PAST.isoformat()},
    )
    bad_tight = load(autonomy=auto(auths=[]), amends={"manifest_id": "wrong", "reason": "r", "effective_at": PAST.isoformat()})
    for bad in (bad_inc, bad_tight):
        assert in_force_manifest(root, bad, NOW) is root
    assert run_in_force(root, bad_inc, req(cls="B"), NOW).verdict == "DENY"
    assert run_in_force(root, bad_tight, req(cls="A"), NOW).verdict == "ALLOW"  # predecessor's grant intact
    # row 27: predecessor is itself an amendment -> fails closed, amd1 stays in force
    amd1 = load(autonomy=auto(), amends={"manifest_id": root.manifest_id, "reason": "r", "effective_at": PAST.isoformat()})
    amd2 = load(
        autonomy=auto(auths=[auth("A"), auth("C")]),
        amends={"manifest_id": amd1.manifest_id, "reason": "r", "effective_at": PAST.isoformat()},
    )
    assert in_force_manifest(amd1, amd2, NOW) is amd1
    assert in_force_manifest(root, None, NOW) is root


def test_B29_M_tightening_only_applies_immediately(load):
    far = (NOW + timedelta(days=5)).isoformat()
    root, amd = _chain(
        load, auto(auths=[auth("A"), auth("B")]), auto(auths=[auth("A")]), effective_at=far
    )
    assert verify_amendment(amd, root).direction == "tightening"
    assert in_force_manifest(root, amd, NOW) is amd  # §7: immediate, no effective_at gate
    assert run_in_force(root, amd, req(cls="B"), NOW).verdict == "DENY"  # tightened away
    assert run_in_force(root, amd, req(cls="A"), NOW).verdict == "ALLOW"


def test_B29_M_row31_mixed_amendment_invalid_predecessor_stays(load):
    # increases the authorization set (adds B) AND tightens duration (600 -> 300): mixed (§7)
    for eff_at in (NOW - timedelta(hours=1), NOW + timedelta(hours=1)):
        root, amd = _chain(
            load,
            auto(auths=[auth("A")], duration=600),
            auto(auths=[auth("A"), auth("B")], duration=300),
            effective_at=eff_at.isoformat(),
        )
        d = verify_amendment(amd, root)
        assert not d.valid and d.direction == "mixed"
        for now in (NOW, NOW + timedelta(hours=5)):
            assert in_force_manifest(root, amd, now) is root  # §8.1(3): predecessor in force
            assert run_in_force(root, amd, req(cls="B"), now).verdict == "DENY"  # increase never applies
            # tightening did not apply either: predecessor's 600s duration governs (elapsed 500 > 300)
            assert run_in_force(root, amd, req(cls="A", elapsed=500), now).verdict == "ALLOW"


def test_B29_M_row31_mixed_manifest_level_axes(load):
    # destructive_allowed F->T (increase) + budget tightening (mixed); in_scope expansion + auth removal (mixed)
    root, amd = _chain(
        load,
        auto(auths=[auth("C", destructive=True)]),
        auto(auths=[auth("C", destructive=True)], budget={**BUDGET, "llm_tokens": 999}),
        amd_ov={"engagement": {"destructive_allowed": True}},
        effective_at=(NOW - timedelta(hours=1)).isoformat(),
    )
    d = verify_amendment(amd, root)
    assert not d.valid and d.direction == "mixed"
    assert run_in_force(root, amd, req(cls="C", destructive=True), NOW).verdict == "DENY"
    root, amd = _chain(
        load,
        auto(auths=[auth("A"), auth("B")]),
        auto(auths=[auth("A")]),
        amd_ov={"scope": {"in_scope": ["*.acme.example.com", "*.other.example.org"]}},
        effective_at=(NOW - timedelta(hours=1)).isoformat(),
    )
    assert verify_amendment(amd, root).direction == "mixed"
    assert in_force_manifest(root, amd, NOW) is root


def test_B29_M_row32_provenance_binding(load):
    # §8.1(1) / invariant 9: a request is ALLOWed only when effective.provenance == verified.manifest_id.
    v = load(autonomy=auto())
    good = in_force_effective_envelope(v, None)
    assert good.provenance == v.manifest_id
    assert authorize(good, req(), v, NOW).verdict == "ALLOW"  # positive control
    # a bare AutonomyEnvelope never authorizes: effective_envelope composes a NON-authorizing envelope
    bare = effective_envelope(v.autonomy, None)
    assert bare.provenance is None
    assert authorize(bare, req(), v, NOW).verdict == "DENY"
    assert authorize(bare, req(), v.autonomy, NOW).verdict == "DENY"  # bare envelope as 'verified'
    assert authorize(effective_envelope(None, None), req(), v, NOW).verdict == "DENY"
    # provenance absent / mismatched / pointing at another manifest
    assert authorize(replace(good, provenance=None), req(), v, NOW).verdict == "DENY"
    assert authorize(replace(good, provenance="sha256:" + "0" * 64), req(), v, NOW).verdict == "DENY"
    other = load(autonomy=auto(), engagement={"client": "Other"})
    assert other.manifest_id != v.manifest_id
    assert authorize(good, req(), other, NOW).verdict == "DENY"
    assert authorize(in_force_effective_envelope(other, None), req(), v, NOW).verdict == "DENY"
    # a non-VerifiedManifest never yields a provenance-bearing envelope
    assert in_force_effective_envelope(v.autonomy, None).provenance is None
    assert authorize(in_force_effective_envelope(v.autonomy, None), req(), v, NOW).verdict == "DENY"


def test_B29_M_rows_33_34_destructive_allowed_increase_pending_then_effective(load):
    eff_at = NOW + timedelta(hours=1)
    c = auth("C", destructive=True)
    root, amd = _chain(
        load,
        auto(auths=[c]),
        auto(auths=[c]),
        amd_ov={"engagement": {"destructive_allowed": True}},  # root keeps the factory default False
        effective_at=eff_at.isoformat(),
    )
    assert root.destructive_allowed is False and amd.destructive_allowed is True
    assert verify_amendment(amd, root).direction == "increase"
    r = req(cls="C", destructive=True)
    # row 33: pending => PREDECESSOR destructive_allowed=False governs (envelope + destructive_allowed same manifest)
    assert run_in_force(root, amd, r, eff_at - timedelta(seconds=1)).verdict == "DENY"
    # row 30 companion: a non-destructive request the predecessor grants still ALLOWs while pending
    assert run_in_force(root, amd, req(cls="C"), eff_at - timedelta(seconds=1)).verdict == "ALLOW"
    # row 34: now >= effective_at, auth.destructive=True => ALLOW
    assert run_in_force(root, amd, r, eff_at).verdict == "ALLOW"


def test_B29_M_in_scope_expansion_pending_then_effective(load):
    # §8.1(2): engagement scope also evaluated against the in-force manifest (F-C)
    eff_at = NOW + timedelta(hours=1)
    a_new = auth("A", OTHER_SCOPE_TARGET)
    root, amd = _chain(
        load,
        auto(auths=[auth("A"), a_new]),
        auto(auths=[auth("A"), a_new]),
        amd_ov={"scope": {"in_scope": ["*.acme.example.com", "*.other.example.org"]}},
        effective_at=eff_at.isoformat(),
    )
    assert verify_amendment(amd, root).direction == "increase"
    before = eff_at - timedelta(seconds=1)
    assert run_in_force(root, amd, req(target=OTHER_SCOPE_TARGET), before).verdict == "DENY"  # not yet in scope
    assert run_in_force(root, amd, req(), before).verdict == "ALLOW"  # predecessor scope still grants
    assert run_in_force(root, amd, req(target=OTHER_SCOPE_TARGET), eff_at).verdict == "ALLOW"


def test_B29_M_manifest_level_tightening_immediate(load):
    far = (NOW + timedelta(days=5)).isoformat()
    c = auth("C", destructive=True)
    root, amd = _chain(
        load,
        auto(auths=[c]),
        auto(auths=[c]),
        root_ov={"engagement": {"destructive_allowed": True}},
        effective_at=far,
    )  # amendment keeps factory default destructive_allowed=False => tightening
    assert verify_amendment(amd, root).direction == "tightening"
    assert in_force_manifest(root, amd, NOW) is amd
    assert run_in_force(root, amd, req(cls="C", destructive=True), NOW).verdict == "DENY"
    assert run_in_force(root, amd, req(cls="C"), NOW).verdict == "ALLOW"


def test_B29_M_noop_amendment_valid_and_immediate(load):
    root, amd = _chain(load, auto(), auto(), effective_at=(NOW + timedelta(days=5)).isoformat())
    assert verify_amendment(amd, root).direction == "none"
    assert in_force_manifest(root, amd, NOW) is amd  # §7: effective immediately
    assert run_in_force(root, amd, req(), NOW).verdict == "ALLOW"


# ---------------------------------------------------------------- amendment axis model (§7 full axis set)
OTHER_SCOPE_TARGET = "x.other.example.org"
EXCL_TARGET = "y.acme.example.com"


def _bdg(d, v):
    return {"a": {"budget": {d: v}}}


# axis -> (restrictive patch, permissive patch). Patch keys: a=autonomy kwargs, e=engagement, s=scope overrides.
AXES = {
    "mode": ({"a": {"mode": "calm"}}, {"a": {"mode": "beast"}}),
    "duration": ({"a": {"duration": 300}}, {"a": {"duration": 600}}),
    **{f"budget.{d}": (_bdg(d, BUDGET[d] - 1), _bdg(d, BUDGET[d])) for d in BUDGET_DIMENSIONS},
    "exfil": ({"a": {}}, {"a": {"exfil_simulation": {"allowed": True, "byte_budget": 5}}}),
    "auths": ({"a": {}}, {"a": {"extra": (auth("B"),)}}),
    "destructive_allowed": ({"e": {"destructive_allowed": False}}, {"e": {"destructive_allowed": True}}),
    "in_scope": (
        {"s": {"in_scope": ["*.acme.example.com"]}},
        {"s": {"in_scope": ["*.acme.example.com", "*.other.example.org"]}},
    ),
    "excluded": ({"s": {"excluded": [EXCL_TARGET]}}, {"s": {"excluded": []}}),
    # §7 O3: any watchdog change counts as a permission increase (never a tightening)
    "watchdog": ({"a": {}}, {"a": {"watchdog": {"may_auto_stop": True, "confirm_window_seconds": 30}}}),
}
TIGHTABLE = [n for n in AXES if n != "watchdog"]


def _mk(load, levels, amends=None):
    """Manifest whose every axis is 'hi' (permissive) unless levels[axis]=='lo'."""
    a, e, s, budget, extra = {}, {}, {}, dict(BUDGET), ()
    for name, (lo, hi) in AXES.items():
        p = lo if levels.get(name, "hi") == "lo" else hi
        pa = dict(p.get("a", {}))
        budget.update(pa.pop("budget", {}))
        extra += tuple(pa.pop("extra", ()))
        a.update(pa)
        e.update(p.get("e", {}))
        s.update(p.get("s", {}))
    ov = {}
    if e:
        ov["engagement"] = e
    if s:
        ov["scope"] = s
    auths = [auth("A", TARGET, destructive=True), auth("A", EXCL_TARGET), auth("A", OTHER_SCOPE_TARGET), *extra]
    return load(autonomy=auto(auths=auths, budget=budget, **a), amends=amends, **ov)


def _pair(load, root_lv, amd_lv, eff_at):
    root = _mk(load, root_lv)
    ref = {"manifest_id": root.manifest_id, "reason": "r", "effective_at": eff_at.isoformat()}
    return root, _mk(load, amd_lv, amends=ref)


_Z = {d: 0 for d in BUDGET_DIMENSIONS}
# (probe, request, predicate(levels) -> expected ALLOW). Each derives from the §8 clause named.
PROBES = [
    ("baseline", req(mode="calm", draw=_Z), lambda lv: True),  # §8 class A, calm, within limits
    ("mode", req(mode="beast", draw=_Z), lambda lv: lv.get("mode", "hi") == "hi"),  # §8 mode clause
    ("duration", req(mode="calm", draw=_Z, elapsed=500), lambda lv: lv.get("duration", "hi") == "hi"),  # §8 duration
    *[
        (f"budget.{d}", req(mode="calm", draw={**_Z, d: BUDGET[d]}), (lambda lv, d=d: lv.get(f"budget.{d}", "hi") == "hi"))
        for d in BUDGET_DIMENSIONS
    ],  # §8 budget clause
    (
        "auths",
        req(mode="beast", cls="B", draw=_Z),
        lambda lv: lv.get("auths", "hi") == "hi" and lv.get("mode", "hi") == "hi",
    ),  # §8 class rule B: beast + matching auth
    (
        "destructive",
        req(mode="calm", destructive=True, draw=_Z),
        lambda lv: lv.get("destructive_allowed", "hi") == "hi",
    ),  # §8 destructive clause (auth.destructive true in every state)
    ("in_scope", req(mode="calm", target=OTHER_SCOPE_TARGET, draw=_Z), lambda lv: lv.get("in_scope", "hi") == "hi"),
    ("excluded", req(mode="calm", target=EXCL_TARGET, draw=_Z), lambda lv: lv.get("excluded", "hi") == "hi"),
]


def _states():
    """(label, root_levels, amendment_levels, direction) with direction fixed BY CONSTRUCTION (§7 prose)."""
    yield "none", {}, {}, "none"
    for x in AXES:
        yield f"increase:{x}", {x: "lo"}, {}, "increase"
    for y in TIGHTABLE:
        yield f"tightening:{y}", {}, {y: "lo"}, "tightening"
    for x in AXES:
        for y in TIGHTABLE:
            if x != y:
                yield f"mixed:{x}+{y}", {x: "lo"}, {y: "lo"}, "mixed"


def _governs_amendment(direction, now, eff_at):
    """Does the amendment govern at `now`? (§7/§8.1(2) prose): no-op/tightening immediately; increase-only at/after
    effective_at; mixed never."""
    if direction in ("none", "tightening"):
        return True
    return direction == "increase" and now >= eff_at


def _invalid_states(load):
    """(label, predecessor, amendment, predecessor_levels): invalid amendments of both polarities (§7, row 26-28)."""
    eff_at = NOW - timedelta(hours=1)
    for pol, root_lv, amd_lv in (("increase", {"auths": "lo"}, {}), ("tightening", {}, {"auths": "lo"})):
        root, amd = _pair(load, root_lv, amd_lv, eff_at)
        wrong = _mk(load, amd_lv, amends={"manifest_id": "sha256:wrong", "reason": "r", "effective_at": eff_at.isoformat()})
        yield f"bad_id:{pol}", root, wrong, root_lv
        naive = _forge(amd, amends=AmendmentRef.model_construct(manifest_id=root.manifest_id, reason="r", effective_at=datetime(2030, 1, 1)))
        yield f"naive_effective_at:{pol}", root, naive, root_lv
        missing = _forge(amd, amends=AmendmentRef.model_construct(manifest_id=root.manifest_id, reason="r", effective_at=None))
        yield f"missing_effective_at:{pol}", root, missing, root_lv
        # single-hop violation: predecessor (amd) is itself an amendment of root
        ref2 = {"manifest_id": amd.manifest_id, "reason": "r", "effective_at": eff_at.isoformat()}
        amd2 = _mk(load, {"mode": "lo"}, amends=ref2)
        yield f"chained:{pol}", amd, amd2, None
        yield f"unrelated_root:{pol}", root, _mk(load, amd_lv), root_lv  # not an amendment at all


def test_B29_M_axis_direction_classification(load):
    # §7 per-axis: each single-axis change classifies as increased (or tightened); watchdog is increase-only.
    eff_at = NOW + timedelta(hours=1)
    for x in AXES:
        root, amd = _pair(load, {x: "lo"}, {}, eff_at)
        assert verify_amendment(amd, root).direction == "increase", x
    for y in TIGHTABLE:
        root, amd = _pair(load, {}, {y: "lo"}, eff_at)
        assert verify_amendment(amd, root).direction == "tightening", y


def test_B29_prop_7_amendment_direction_preserves_or_applies_authority(load):
    # §13 invariant 7 over amendment-direction state x {before, at, after effective_at} x window/budget/destructive probes
    eff_at = NOW + timedelta(hours=1)
    times = (eff_at - timedelta(seconds=1), eff_at, eff_at + timedelta(days=1))
    allows = {"before": 0, "after": 0}
    for label, root_lv, amd_lv, direction in _states():
        root, amd = _pair(load, root_lv, amd_lv, eff_at)
        assert verify_amendment(amd, root).direction == direction, label
        for now in times:
            expect_amd = _governs_amendment(direction, now, eff_at)
            gov_lv = amd_lv if expect_amd else root_lv
            iv = in_force_manifest(root, amd, now)
            assert iv is (amd if expect_amd else root), (label, now)
            env = in_force_effective_envelope(iv, None)
            for name, request, pred in PROBES:
                verdict = authorize(env, request, iv, now).verdict
                assert verdict == ("ALLOW" if pred(gov_lv) else "DENY"), (label, now, name)
                if verdict == "ALLOW":
                    allows["before" if now < eff_at else "after"] += 1
    assert allows["before"] > 0 and allows["after"] > 0  # not vacuous: ALLOW positive controls on both sides
    # invalid amendments (bad id, naive/missing effective_at, chained, non-amendment): predecessor, never the increase
    for label, pred_m, amd_m, pred_lv in _invalid_states(load):
        for now in times:
            assert in_force_manifest(pred_m, amd_m, now) is pred_m, (label, now)
            assert not verify_amendment(amd_m, pred_m).valid, label
            env = in_force_effective_envelope(pred_m, None)
            assert authorize(env, req(mode="calm", draw=_Z), pred_m, now).verdict == "ALLOW", label  # baseline kept
            if pred_lv is not None:  # predecessor's own B grant is neither upgraded nor downgraded-by-invalidation
                want = "ALLOW" if pred_lv.get("auths", "hi") == "hi" else "DENY"
                assert authorize(env, req(mode="beast", cls="B", draw=_Z), pred_m, now).verdict == want, label


def test_B29_prop_9_no_authorization_without_verified_provenance(load):
    # §13 invariant 9 over the same generated space: ALLOW only with provenance == in-force verified.manifest_id
    eff_at = NOW + timedelta(hours=1)
    times = (eff_at - timedelta(seconds=1), eff_at + timedelta(days=1))
    base = PROBES[0][1]
    allowed = denied_variants = 0
    for label, root_lv, amd_lv, _direction in _states():
        root, amd = _pair(load, root_lv, amd_lv, eff_at)
        for now in times:
            iv = in_force_manifest(root, amd, now)
            other = amd if iv is root else root
            env = in_force_effective_envelope(iv, None)
            assert env.provenance == iv.manifest_id
            assert authorize(env, base, iv, now).verdict == "ALLOW", (label, now)  # positive control (§8 class A)
            allowed += 1
            variants = (
                effective_envelope(iv.autonomy, None),  # bare, provenance-absent
                replace(env, provenance=None),
                replace(env, provenance="sha256:" + "0" * 64),
                replace(env, provenance=iv.manifest_id[len("sha256:"):]),  # missing the prefix
                in_force_effective_envelope(other, None),  # derived from the OTHER manifest
            )
            for var in variants:
                assert var.provenance != iv.manifest_id
                assert authorize(var, base, iv, now).verdict != "ALLOW", (label, now)
                denied_variants += 1
            # a bare AutonomyEnvelope / unverified object in the 'verified' slot never authorizes
            assert authorize(effective_envelope(iv.autonomy, None), base, iv.autonomy, now).verdict == "DENY"
    assert allowed > 0 and denied_variants > 0



# ---------------------------------------------------------------- property invariants (§13), deterministic space
def _space():
    """(request mode, request class, target) -- exhaustive, no randomness."""
    return itertools.product(("calm", "beast"), "ABC", (TARGET, OTHER))


def test_B29_prop_2_3_4_beast_nothing_target_class_isolation(load):
    # invariant 2: empty authorizations => no external ALLOW regardless of mode
    for mode_max in ("calm", "beast"):
        v_empty = load(autonomy=auto(mode=mode_max, auths=[]))
        e_empty = in_force_effective_envelope(v_empty, None)
        for rm, rc, tgt in _space():
            assert authorize(e_empty, req(mode=rm, cls=rc, target=tgt), v_empty, NOW).verdict == "DENY"
    # invariants 3, 4: an authorization for (B, TARGET) authorizes nothing else
    allowed = []
    for mode_max in ("calm", "beast"):
        vm = load(autonomy=auto(mode=mode_max, auths=[auth("B", TARGET)]))
        em = in_force_effective_envelope(vm, None)
        for rm, rc, tgt in _space():
            if authorize(em, req(mode=rm, cls=rc, target=tgt), vm, NOW).verdict == "ALLOW":
                allowed.append((rc, tgt, rm, mode_max))
    # exact allowed set (positive control: not vacuous): only B + TARGET + beast request + beast ceiling (§8 calm-B deny)
    assert allowed == [("B", TARGET, "beast", "beast")]


def test_B29_prop_5_expiry_monotonic_generated(load):
    rnd = random.Random(29)
    vf, vu = NOW - timedelta(hours=3), NOW + timedelta(hours=3)
    v = load(autonomy=auto(auths=[auth("A", vf=vf, vu=vu)]))
    eff = in_force_effective_envelope(v, None)
    inside = 0
    for _ in range(200):
        t = NOW + timedelta(seconds=rnd.randint(-40000, 40000))
        verdict = authorize(eff, req(), v, t).verdict
        if not (vf <= t <= vu):
            assert verdict != "ALLOW"
        else:
            assert verdict == "ALLOW"
            inside += 1
    assert inside > 0  # positive control


def test_B29_prop_1_runtime_never_expands(load):
    rnd = random.Random(1129)
    v = load(autonomy=auto())
    base = in_force_effective_envelope(v, None)
    allowed = 0
    for _ in range(200):
        dim = rnd.choice(BUDGET_DIMENSIONS)
        r = BUDGET[dim] * rnd.choice([0, 0.5, 1, 1.01, 2])
        if r > BUDGET[dim]:
            with pytest.raises(AutonomyError):
                effective_envelope(v.autonomy, RuntimeRestrictions(budget={dim: r}))
            with pytest.raises(AutonomyError):
                in_force_effective_envelope(v, RuntimeRestrictions(budget={dim: r}))
        else:
            eff = in_force_effective_envelope(v, RuntimeRestrictions(budget={dim: r}))
            assert eff.budget[dim] <= BUDGET[dim]
            # nothing allowed under effective that signed disallows
            d = {**WITHIN, dim: BUDGET[dim] + 1}
            assert authorize(base, req(draw=d), v, NOW).verdict == "DENY"
            assert authorize(eff, req(draw=d), v, NOW).verdict == "DENY"
            # positive control: a draw within the effective (restricted) limit is ALLOWed
            ok = {**WITHIN, dim: min(WITHIN[dim], r)}
            assert authorize(eff, req(draw=ok), v, NOW).verdict == "ALLOW"
            allowed += 1
    assert allowed > 0  # the ALLOW control actually ran


def test_B29_prop_6_destructive_needs_both(load):
    allowed = []
    for da, ad, cls, mode in itertools.product((True, False), (True, False), "ABC", ("calm", "beast")):
        v = load(autonomy=auto(auths=[auth(cls, destructive=ad)]), engagement={"destructive_allowed": da})
        r = run(v, req(mode=mode, cls=cls, destructive=True))
        if r.verdict == "ALLOW":
            assert da and ad  # never from mode or class C alone
            allowed.append((da, ad, cls, mode))
    # positive control (§8 class rules): with both flags, A allowed in calm/beast, B and C only in beast
    assert allowed == [(True, True, c, m) for c, m in (("A", "calm"), ("A", "beast"), ("B", "beast"), ("C", "beast"))]


def test_B29_prop_8_canonical_stable(manifest_factory, signing_keypair):
    # §13 invariant 8: logically-equal manifests => equal canonical bytes => equal manifest_id.
    import yaml

    from kronos.manifest import sign_manifest

    priv, pub = signing_keypair
    raw = yaml.safe_load(manifest_factory(autonomy=auto()))
    raw.pop("signature")
    reordered = {k: raw[k] for k in reversed(list(raw))}
    reordered["autonomy"] = {k: raw["autonomy"][k] for k in reversed(list(raw["autonomy"]))}
    reordered["engagement"] = {k: raw["engagement"][k] for k in reversed(list(raw["engagement"]))}
    a = load_and_verify(sign_manifest(raw, priv), pub)
    b = load_and_verify(sign_manifest(reordered, priv), pub)
    assert a.canonical_content == b.canonical_content
    assert a.manifest_id == b.manifest_id == compute_manifest_id(a)
    # positive control: a logically different manifest has a different id
    changed = copy.deepcopy(raw)
    changed["autonomy"]["max_unattended_duration_seconds"] += 1
    c = load_and_verify(sign_manifest(changed, priv), pub)
    assert c.manifest_id != a.manifest_id


# ---------------------------------------------------------------- O: purity / no side effects
def test_B29_O_pure_no_network_no_mutation(load, nonet):
    v = load(autonomy=auto(auths=[auth("A")]))
    snap = (v.model_dump(), v.canonical_content)
    s_env = copy.deepcopy(v.autonomy)
    eff = in_force_effective_envelope(v, RuntimeRestrictions(budget={"llm_tokens": 1}))
    authorize(eff, req(), v, NOW)
    in_force_manifest(v, None, NOW)
    root, amd = _chain(load, auto(), auto(auths=[auth("A"), auth("B")]), effective_at=(NOW + timedelta(hours=1)).isoformat())
    in_force_manifest(root, amd, NOW)
    assert (v.model_dump(), v.canonical_content) == snap and v.autonomy == s_env
    assert compute_manifest_id(v) == v.manifest_id


def test_B29_H_public_producers_exported():
    # F-H: the provenance-bearing producers are part of the public surface (§8, §8.1)
    for name in ("in_force_effective_envelope", "in_force_manifest", "effective_envelope", "authorize", "verify_amendment"):
        assert name in A.__all__ and callable(getattr(A, name)), name
    assert not hasattr(A, "active_envelope")  # superseded by in_force_manifest (§8.1(2))


def test_B29_O_not_wired():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "kronos"
    for p in root.rglob("*.py"):
        if p.name in ("autonomy.py",):
            continue
        assert "kronos.autonomy" not in p.read_text(), p  # §9 NOT wired


# ---------------------------------------------------------------- Q: scope audit (whole window)
B29_BASE = "55b4b7f"
B29_SECTION_10 = {
    "SPEC_BRIEF29.md",
    "src/kronos/manifest.py",
    "src/kronos/autonomy.py",
    "tests/test_autonomy.py",
    "tests/test_manifest.py",
    "tests/conftest.py",
    "tests/test_query.py",
}


def test_B29_Q_scope_audit():
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{B29_BASE}..HEAD"], capture_output=True, text=True, check=True
    ).stdout.split()
    assert set(out) <= B29_SECTION_10, set(out) - B29_SECTION_10


# §12 E2 / §13 adversarial / §8.1(1a): EffectiveEnvelope is unforgeable by construction
def test_B29_E2_envelope_construction_guard_rejects_forgery(load):
    v = load(autonomy=auto())
    good = in_force_effective_envelope(v, None)
    # direct public construction with a recomputed real manifest_id and elevated authority
    with pytest.raises(AutonomyError):
        EffectiveEnvelope(
            mode_max="beast",
            authorizations=good.authorizations,
            max_unattended_duration_seconds=10**9,
            budget={d: 10**12 for d in BUDGET_DIMENSIONS},
            exfil_allowed=True,
            exfil_byte_budget=10**12,
            provenance=v.manifest_id,
        )
    # dataclasses.replace on a legitimately produced envelope re-invokes the guard
    for legit in (good, effective_envelope(v.autonomy, None), effective_envelope(None, None)):
        with pytest.raises(AutonomyError):
            dataclasses.replace(legit, provenance=v.manifest_id)
        with pytest.raises(AutonomyError):
            dataclasses.replace(legit, mode_max="beast")
    # only in_force_effective_envelope authorizes; the others are provenance-absent
    assert effective_envelope(v.autonomy, None).provenance is None
    assert effective_envelope(None, None).provenance is None
    assert authorize(effective_envelope(v.autonomy, None), req(), v, NOW).verdict == "DENY"
    # positive control: legitimate producer path still ALLOWs a matching request
    assert good.provenance == v.manifest_id
    assert authorize(good, req(), v, NOW).verdict == "ALLOW"
