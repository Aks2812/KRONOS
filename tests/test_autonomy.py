"""SPEC_BRIEF29 (hermetic): signed autonomy envelope, pure evaluation.

Every expected verdict derives from the brief prose (section noted per cell),
never from observed behaviour. No `hypothesis` (D5): generators are
deterministic itertools/random(seed) enumerations."""

from __future__ import annotations

import copy
import dataclasses
from dataclasses import replace
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
    AutonomyError,
    RuntimeRestrictions,
    active_envelope,
    in_force_effective_envelope,
    authorize,
    effective_envelope,
    to_budget_limits,
    verify_amendment,
)
from kronos.budget.limits import BUDGET_DIMENSIONS, BudgetLimits
from kronos.manifest import (
    AmendmentRef,
    AutonomyEnvelope,
    UnattendedAuthorization,
    UnattendedBudget,
    VerifiedManifest,
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
    eff = effective_envelope(verified.autonomy, runtime)
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


# row15: §8 budget clause + 4.1 boundary: a None/missing dimension is never unlimited => DENY; conversion raises AutonomyError
def test_B29_G_row15_none_budget_dim_denies_not_unlimited(load):
    v = load(autonomy=auto())
    broken = v.autonomy.max_unattended_budget.model_construct(**{**BUDGET, "llm_tokens": None})
    env = v.autonomy.model_copy(update={"max_unattended_budget": broken})
    eff = effective_envelope(env, None)
    assert authorize(eff, req(draw={**WITHIN, "llm_tokens": 10**12}), v, NOW).verdict == "DENY"
    assert authorize(eff, req(), v, NOW).verdict == "DENY"
    with pytest.raises(AutonomyError):
        to_budget_limits(broken)


# row19: §6/§8 absent autonomy block => fail-closed Calm with zero authority => DENY for every mode x class
def test_B29_G_row19_absent_autonomy_fail_closed_calm(load):
    v = load()
    assert v.autonomy is None
    eff = effective_envelope(None, None)
    assert eff.mode_max == "calm" and eff.authorizations == ()
    for mode, cls in itertools.product(("calm", "beast"), "ABC"):
        assert authorize(eff, req(mode=mode, cls=cls), v, NOW).verdict == "DENY"


# row20: §8 unusable signed input (non-AutonomyEnvelope) => fail-closed => DENY
def test_B29_G_row20_malformed_autonomy_fail_closed(load):
    v = load()
    for bad in ({"mode_max": "beast"}, "beast", 5, object()):
        eff = effective_envelope(bad, None)
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
    eff = effective_envelope(v.autonomy, rt)
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
    eff = effective_envelope(v.autonomy, RuntimeRestrictions(mode_max="calm", authorizations=narrowed))
    assert eff.mode_max == "calm" and eff.authorizations == narrowed
    assert effective_envelope(v.autonomy, RuntimeRestrictions(authorizations=())).authorizations == ()
    # equal is not widening
    eff = effective_envelope(v.autonomy, RuntimeRestrictions(budget=dict(BUDGET), max_unattended_duration_seconds=600))
    assert eff.budget == BUDGET


def test_B29_F_runtime_destructive_disable_strips_grant(load):
    v = load(autonomy=auto(auths=[auth("C", destructive=True)]), engagement=D_OK)
    eff = effective_envelope(v.autonomy, RuntimeRestrictions(allow_destructive=False))
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
    eff = effective_envelope(v.autonomy, None)
    assert authorize(eff, req(), v, NOW - timedelta(hours=1)).verdict == "ALLOW"  # §8 <= inclusive
    assert authorize(eff, req(), v, NOW + timedelta(hours=1)).verdict == "ALLOW"
    assert authorize(eff, req(), v, NOW + timedelta(hours=1, seconds=1)).verdict == "DENY"
    assert authorize(eff, req(), v, NOW - timedelta(hours=1, seconds=1)).verdict == "DENY"
    assert authorize(eff, req(), v, datetime(2030, 1, 1)).verdict == "DENY"  # naive


def test_B29_duration_elapsed(load):
    v = load(autonomy=auto())
    eff = effective_envelope(v.autonomy, None)
    assert authorize(eff, req(elapsed=600), v, NOW).verdict == "ALLOW"  # <=
    assert authorize(eff, req(elapsed=600.5), v, NOW).verdict == "DENY"
    assert authorize(eff, req(elapsed=None), v, NOW).verdict == "INCONCLUSIVE"


def test_B29_inconclusive_when_now_or_partial_draw_missing(load):
    v = load(autonomy=auto())
    eff = effective_envelope(v.autonomy, None)
    assert authorize(eff, req(), v, None).verdict == "INCONCLUSIVE"
    partial = {k: v_ for k, v_ in WITHIN.items() if k != "llm_cost_usd"}
    assert authorize(eff, req(draw=partial), v, NOW).verdict == "INCONCLUSIVE"


def test_B29_deny_beats_inconclusive(load):
    v = load(autonomy=auto())
    eff = effective_envelope(v.autonomy, None)
    assert authorize(eff, req(draw=OVER, elapsed=None), v, NOW).verdict == "DENY"


# ---------------------------------------------------------------- mode as grant (#1)
def test_B29_request_mode_above_mode_max_denied(load):
    v = load(autonomy=auto(mode="calm", auths=[auth("A")]))
    eff = effective_envelope(v.autonomy, None)
    assert authorize(eff, req(mode="beast"), v, NOW).verdict == "DENY"
    assert authorize(eff, req(mode="calm"), v, NOW).verdict == "ALLOW"


def test_B29_unknown_class_mode_denied(load):
    v = load(autonomy=auto())
    eff = effective_envelope(v.autonomy, None)
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
    eff = effective_envelope(v.autonomy, None)
    assert authorize(eff, req(target="evil.example.org"), v, NOW).verdict == "DENY"  # auth, but out of scope
    v2 = load(autonomy=auto(auths=[auth("A", TARGET)]), scope={"excluded": [TARGET]})
    assert run(v2, req()).verdict == "DENY"  # excluded-first


def test_B29_node_type_must_match_and_family(load):
    v = load(autonomy=auto(auths=[auth("A", node="HOST")]))
    eff = effective_envelope(v.autonomy, None)
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
    eff = effective_envelope(v.autonomy, None)
    assert authorize(eff, req(), v, NOW).verdict == "DENY"


@pytest.mark.parametrize("t", ["HOST.acme.example.com.evil.org", "host.acme.example.com:8443", "https://host.acme.example.com/x", "10.0.0.5"])
def test_B29_literal_auth_does_not_cross_identifier_boundary(load, t):
    v = load(autonomy=auto(auths=[auth("A", TARGET)]))
    eff = effective_envelope(v.autonomy, None)
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


# ---------------------------------------------------------------- amendments (§7)
def _forge(m, **update):
    """Test-only: bypass the §5 gate via the module-private token to build malformed amendments."""
    from kronos import manifest as _mf

    tok = _mf._CONSTRUCTING.set(True)
    try:
        return m.model_copy(update=update)
    finally:
        _mf._CONSTRUCTING.reset(tok)


def _chain(load, root_auto, amend_auto, **am):
    root = load(autonomy=root_auto)
    ref = {"manifest_id": root.manifest_id, "reason": "r", "effective_at": NOW.isoformat(), **am}
    return root, load(autonomy=amend_auto, amends=ref)


def test_B29_M_verify_amendment_ok_and_failures(load):
    root, amd = _chain(load, auto(), auto())
    assert verify_amendment(amd, root).valid
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
    n2 = _forge(amd, **{"amends": AmendmentRef.model_construct(manifest_id=root.manifest_id, reason="r", effective_at=None)})
    assert not verify_amendment(n2, root).valid
    n3 = _forge(amd, **{"amends": AmendmentRef.model_construct(manifest_id="", reason="r", effective_at=NOW)})
    assert not verify_amendment(n3, root).valid
    n4 = _forge(amd, **{"amends": AmendmentRef.model_construct(manifest_id=root.manifest_id, reason="", effective_at=NOW)})
    assert not verify_amendment(n4, root).valid
    # naive effective_at: increase never applies (row 28)
    inc = _forge(n, autonomy=load(autonomy=auto(auths=[auth("A"), auth("B")])).autonomy)
    assert active_envelope(root, inc, NOW + timedelta(days=99)) == root.autonomy


def test_B29_M_row24_25_increase_gated_by_effective_at(load):
    root_a = auto(auths=[auth("A")])
    amd_a = auto(auths=[auth("A"), auth("B")])  # increase: adds B
    eff_at = NOW + timedelta(hours=1)
    root, amd = _chain(load, root_a, amd_a, effective_at=eff_at.isoformat())
    env_before = active_envelope(root, amd, eff_at - timedelta(seconds=1))
    env_after = active_envelope(root, amd, eff_at)
    assert env_before == root.autonomy  # row 25: inert before effective_at
    assert env_after == amd.autonomy  # row 24: applies at/after
    b = req(cls="B")
    assert authorize(effective_envelope(env_before, None), b, root, NOW).verdict == "DENY"
    assert authorize(effective_envelope(env_after, None), b, root, NOW).verdict == "ALLOW"


def test_B29_M_tightening_applies_immediately(load):
    root, amd = _chain(load, auto(auths=[auth("A"), auth("B")]), auto(auths=[auth("A")]), effective_at=(NOW + timedelta(days=5)).isoformat())
    assert active_envelope(root, amd, NOW) == amd.autonomy  # §7 tightening not delayed


@pytest.mark.parametrize(
    "amd_kw",
    [
        dict(duration=601),
        dict(budget={**BUDGET, "tool_invocations": 11}),
        dict(budget={**BUDGET, "llm_cost_usd": 1.6}),
        dict(mode="beast", exfil_simulation={"allowed": True, "byte_budget": 5}),
        # §7: watchdog changes count as permission increases (not before effective_at)
        dict(mode="beast", watchdog={"may_auto_stop": True, "confirm_window_seconds": 30}),
    ],
)
def test_B29_M_other_increases_gated(load, amd_kw):
    root, amd = _chain(load, auto(mode="beast"), auto(**amd_kw), effective_at=(NOW + timedelta(days=5)).isoformat())
    assert active_envelope(root, amd, NOW) == root.autonomy


def test_B29_M_watchdog_only_amendment_gated_then_applies(load):
    far = (NOW + timedelta(days=30)).isoformat()
    wd = {"watchdog": {"may_auto_stop": True, "confirm_window_seconds": 30}}
    root, amd = _chain(load, auto(), auto(**wd), effective_at=far)
    assert active_envelope(root, amd, NOW) == root.autonomy  # inert before effective_at
    assert active_envelope(root, amd, NOW + timedelta(days=31)) == amd.autonomy  # positive control


def test_B29_M_authorize_enforces_pending_increase_until(load):
    # F1d: gate reads only the in-force envelope's provenance (§8), never `verified`.
    eff_at = NOW + timedelta(hours=1)
    root, amd = _chain(load, auto(auths=[auth("A")]), auto(auths=[auth("A"), auth("B")]), effective_at=eff_at.isoformat())
    b = req(cls="B")
    # amendment-derived effective paired with the ROOT verified (the F1d bypass pairing)
    env = replace(effective_envelope(amd.autonomy, None), pending_increase_until=eff_at)
    assert authorize(env, b, root, NOW).verdict == "DENY"
    assert authorize(env, b, amd, NOW).verdict == "DENY"
    assert authorize(env, b, root, eff_at - timedelta(seconds=1)).verdict == "DENY"
    assert authorize(env, b, root, eff_at).verdict == "ALLOW"  # positive control
    assert authorize(env, b, root, eff_at + timedelta(seconds=1)).verdict == "ALLOW"
    # naive pending bound fails closed
    naive = replace(env, pending_increase_until=datetime(2030, 1, 1))
    assert authorize(naive, b, root, NOW).verdict == "DENY"


def test_B29_M_in_force_envelope_sets_provenance_only_for_pending_increase(load):
    eff_at = NOW + timedelta(hours=1)
    # increase, not yet effective => gated (§7 increase waits for effective_at)
    root, amd = _chain(load, auto(auths=[auth("A")]), auto(auths=[auth("A"), auth("B")]), effective_at=eff_at.isoformat())
    assert in_force_effective_envelope(root, amd, NOW).pending_increase_until == eff_at
    # increase, at/after effective => applied, no gate; B now allowed
    after = in_force_effective_envelope(root, amd, eff_at)
    assert after.pending_increase_until is None
    assert authorize(after, req(cls="B"), amd, eff_at).verdict == "ALLOW"
    # tightening => applies immediately, never gated (§7), even with a far-future effective_at
    far = (NOW + timedelta(days=5)).isoformat()
    root, amd = _chain(load, auto(auths=[auth("A"), auth("B")]), auto(auths=[auth("A")]), effective_at=far)
    tight = in_force_effective_envelope(root, amd, NOW)
    assert tight.pending_increase_until is None
    assert authorize(tight, req(cls="A"), amd, NOW).verdict == "ALLOW"
    assert authorize(tight, req(cls="B"), amd, NOW).verdict == "DENY"  # tightened away, not gate-denied
    # no amendment / invalid amendment => no gate
    assert in_force_effective_envelope(root, None, NOW).pending_increase_until is None
    bad = load(autonomy=auto(auths=[auth("A"), auth("C")]), amends={"manifest_id": "wrong", "reason": "r", "effective_at": far})
    assert in_force_effective_envelope(root, bad, NOW).pending_increase_until is None


def test_B29_M_mode_increase_gated(load):
    root, amd = _chain(load, auto(mode="calm"), auto(mode="beast"), effective_at=(NOW + timedelta(days=5)).isoformat())
    assert active_envelope(root, amd, NOW) == root.autonomy


def test_B29_M_invalid_amendment_preserves_predecessor(load):
    root = load(autonomy=auto(auths=[auth("A")]))
    bad = load(
        autonomy=auto(auths=[auth("A"), auth("B")]),
        amends={"manifest_id": "wrong", "reason": "r", "effective_at": PAST.isoformat()},
    )
    assert active_envelope(root, bad, NOW) == root.autonomy  # row 26: no upgrade
    tight = load(autonomy=auto(auths=[]), amends={"manifest_id": "wrong", "reason": "r", "effective_at": PAST.isoformat()})
    assert active_envelope(root, tight, NOW) == root.autonomy  # no downgrade-by-invalidation either
    # row 27
    amd1 = load(autonomy=auto(), amends={"manifest_id": root.manifest_id, "reason": "r", "effective_at": PAST.isoformat()})
    amd2 = load(autonomy=auto(auths=[auth("A"), auth("C")]), amends={"manifest_id": amd1.manifest_id, "reason": "r", "effective_at": PAST.isoformat()})
    assert active_envelope(amd1, amd2, NOW) == amd1.autonomy
    assert active_envelope(root, None, NOW) == root.autonomy


# ---------------------------------------------------------------- property invariants (§13), deterministic space
def _space():
    modes = ("calm", "beast")
    classes = "ABC"
    for rm, rc, am, ac, tgt in itertools.product(modes, classes, modes, classes, (TARGET, OTHER)):
        yield rm, rc, am, ac, tgt


def test_B29_prop_2_3_4_beast_nothing_target_class_isolation(load):
    v_empty = load(autonomy=auto(auths=[]))
    e_empty = effective_envelope(v_empty.autonomy, None)
    v = load(autonomy=auto(auths=[auth("A")]))
    allowed = []
    for rm, rc, am, ac, tgt in _space():
        assert authorize(e_empty, req(mode=rm, cls=rc, target=tgt), v_empty, NOW).verdict == "DENY"  # P2
    for mode_max in ("calm", "beast"):
        vm = load(autonomy=auto(mode=mode_max, auths=[auth("B", TARGET)]))
        em = effective_envelope(vm.autonomy, None)
        for rm, rc, tgt in itertools.product(("calm", "beast"), "ABC", (TARGET, OTHER)):
            r = authorize(em, req(mode=rm, cls=rc, target=tgt), vm, NOW)
            if r.verdict == "ALLOW":  # only B + TARGET + beast + beast ceiling can allow
                allowed.append((rc, tgt, rm, mode_max))
    # exact allowed set (positive control: the property is not vacuous)
    assert allowed == [("B", TARGET, "beast", "beast")]  # P3, P4, §8 calm-B deny




def test_B29_prop_5_expiry_monotonic_generated(load):
    rnd = random.Random(29)
    vf, vu = NOW - timedelta(hours=3), NOW + timedelta(hours=3)
    v = load(autonomy=auto(auths=[auth("A", vf=vf, vu=vu)]))
    eff = effective_envelope(v.autonomy, None)
    for _ in range(200):
        t = NOW + timedelta(seconds=rnd.randint(-40000, 40000))
        verdict = authorize(eff, req(), v, t).verdict
        if not (vf <= t <= vu):
            assert verdict != "ALLOW"
        else:
            assert verdict == "ALLOW"


def test_B29_prop_1_runtime_never_expands(load):
    rnd = random.Random(1129)
    v = load(autonomy=auto())
    S = v.autonomy
    for _ in range(200):
        dim = rnd.choice(BUDGET_DIMENSIONS)
        r = BUDGET[dim] * rnd.choice([0, 0.5, 1, 1.01, 2])
        if r > BUDGET[dim]:
            with pytest.raises(AutonomyError):
                effective_envelope(S, RuntimeRestrictions(budget={dim: r}))
        else:
            eff = effective_envelope(S, RuntimeRestrictions(budget={dim: r}))
            assert eff.budget[dim] <= BUDGET[dim]
            base = effective_envelope(S, None)
            # nothing allowed under effective that signed disallows
            d = {**WITHIN, dim: BUDGET[dim] + 1}
            assert authorize(base, req(draw=d), v, NOW).verdict == "DENY"
            assert authorize(eff, req(draw=d), v, NOW).verdict == "DENY"
            # positive control: a draw within the effective (restricted) limit is ALLOWed
            ok = {**WITHIN, dim: min(WITHIN[dim], r)}
            assert authorize(eff, req(draw=ok), v, NOW).verdict == "ALLOW"


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
    eff = effective_envelope(v.autonomy, RuntimeRestrictions(budget={"llm_tokens": 1}))
    authorize(eff, req(), v, NOW)
    active_envelope(v, None, NOW)
    assert (v.model_dump(), v.canonical_content) == snap and v.autonomy == s_env
    assert compute_manifest_id(v) == v.manifest_id


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
