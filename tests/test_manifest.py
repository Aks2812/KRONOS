from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kronos.manifest import ManifestError, load_and_verify


def test_valid_manifest_loads(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    yaml_text = manifest_factory()
    m = load_and_verify(yaml_text, pub)
    assert m.engagement_id == "acme-2026"
    assert m.in_scope == ["*.acme.example.com"]


def test_unsigned_manifest_rejected(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    yaml_text = manifest_factory().replace("signature:", "signature: # tampered\nsignature_x:")
    with pytest.raises(ManifestError):
        load_and_verify(yaml_text, pub)


def test_tampered_content_rejected(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    yaml_text = manifest_factory().replace("Acme Corp", "Evil Corp")
    with pytest.raises(ManifestError):
        load_and_verify(yaml_text, pub)


def test_expired_window_rejected(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    now = datetime.now(timezone.utc)
    yaml_text = manifest_factory(engagement={
        "window_start": (now - timedelta(days=10)).isoformat(),
        "window_end": (now - timedelta(days=1)).isoformat(),
    })
    with pytest.raises(ManifestError):
        load_and_verify(yaml_text, pub)


def test_malformed_yaml_rejected(signing_keypair):
    _, pub = signing_keypair
    with pytest.raises(ManifestError):
        load_and_verify("not: valid: yaml: [", pub)


def test_wrong_public_key_rejected(manifest_factory):
    yaml_text = manifest_factory()
    wrong_pub = Ed25519PrivateKey.generate().public_key()
    with pytest.raises(ManifestError):
        load_and_verify(yaml_text, wrong_pub)


def test_naive_window_timestamp_rejected_as_manifest_error_not_typeerror(manifest_factory, signing_keypair):
    """Final review Important #5: a window timestamp with no UTC offset
    used to reach the aware/naive datetime comparison in load_and_verify
    and raise a bare TypeError. A caller catching only ManifestError (as
    this module's whole contract promises) would crash instead of
    getting a clean rejection."""
    _, pub = signing_keypair
    naive = manifest_factory(engagement={
        "window_start": "2026-01-01T00:00:00",  # no offset
        "window_end": "2026-12-31T23:59:59",
    })
    with pytest.raises(ManifestError):
        load_and_verify(naive, pub)


# ---- SPEC_BRIEF29 (hermetic): signed autonomy schema, identity, boundary ----

import copy  # noqa: E402
import socket  # noqa: E402

import yaml  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from kronos.manifest import (  # noqa: E402
    WATCHDOG_CONFIRM_WINDOW_MAX,
    AmendmentRef,
    AutonomyEnvelope,
    ScopeManifest,
    UnattendedAuthorization,
    UnattendedBudget,
    VerifiedManifest,
    WatchdogPolicy,
    canonicalize,
    compute_manifest_id,
)


@pytest.fixture(autouse=False)
def b29_nonet(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = datetime(2036, 1, 1, tzinfo=timezone.utc)

BUDGET = {
    "validation_attempts": 5,
    "tool_invocations": 10,
    "wall_clock_seconds": 60.0,
    "llm_tokens": 1000,
    "llm_cost_usd": 1.5,
}


def _auth(**kw):
    d = {
        "action_class": "A",
        "target": "host.acme.example.com",
        "target_node_type": "HOST",
        "valid_from": T0.isoformat(),
        "valid_until": T1.isoformat(),
    }
    d.update(kw)
    return d


def _auto(**kw):
    d = {
        "mode_max": "beast",
        "unattended_authorizations": [_auth()],
        "max_unattended_duration_seconds": 600,
        "max_unattended_budget": dict(BUDGET),
    }
    d.update(kw)
    return d


# A / §6: back-compat
def test_B29_A_old_manifest_loads_without_blocks(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    m = load_and_verify(manifest_factory(), pub)
    assert m.autonomy is None and m.amends is None
    assert isinstance(m, VerifiedManifest) and isinstance(m, ScopeManifest)


# B / §4: round trip into typed submodels
def test_B29_B_schema_round_trip(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    a = _auto(
        exfil_simulation={"allowed": True, "byte_budget": 10, "dataset_marker": "label-1"},
        watchdog={"may_auto_stop": True, "confirm_window_seconds": 30},
    )
    m = load_and_verify(manifest_factory(autonomy=a), pub)
    assert isinstance(m.autonomy, AutonomyEnvelope)
    assert m.autonomy.mode_max == "beast"
    assert isinstance(m.autonomy.unattended_authorizations[0], UnattendedAuthorization)
    assert isinstance(m.autonomy.max_unattended_budget, UnattendedBudget)
    assert m.autonomy.max_unattended_budget.llm_cost_usd == 1.5
    assert m.autonomy.exfil_simulation.dataset_marker == "label-1"
    assert m.autonomy.watchdog.confirm_window_seconds == 30
    assert m.autonomy.unattended_authorizations[0].destructive is False  # §4 default


def test_B29_B_defaults_mode_max_calm_exfil_watchdog_none(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    a = _auto()
    del a["mode_max"]
    m = load_and_verify(manifest_factory(autonomy=a), pub)
    assert m.autonomy.mode_max == "calm"
    assert m.autonomy.exfil_simulation is None and m.autonomy.watchdog is None


def test_B29_B_amends_round_trip(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    am = {"manifest_id": "abc", "reason": "r", "effective_at": T1.isoformat()}
    m = load_and_verify(manifest_factory(amends=am), pub)
    assert isinstance(m.amends, AmendmentRef) and m.amends.manifest_id == "abc"


# §4 validators (each cell: the clause in the comment)
@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.update(mode_max="god"),  # §4 Literal calm|beast
        lambda a: a["unattended_authorizations"][0].update(action_class="LOCAL"),  # O2 A|B|C only
        lambda a: a["unattended_authorizations"][0].update(action_class="D"),  # §4 A|B|C
        lambda a: a["unattended_authorizations"][0].update(valid_from="2026-01-01T00:00:00"),  # tz-aware
        lambda a: a["unattended_authorizations"][0].update(valid_until="2026-01-01T00:00:00"),  # tz-aware
        lambda a: a["unattended_authorizations"][0].update(valid_until=T0.isoformat()),  # until > from
        lambda a: a["unattended_authorizations"][0].update(valid_until=(T0 - timedelta(days=1)).isoformat()),
        lambda a: a.update(max_unattended_duration_seconds=0),  # finite > 0
        lambda a: a.update(max_unattended_duration_seconds=-5),
        lambda a: a.update(max_unattended_duration_seconds=None),  # REQUIRED, no None
        lambda a: a.pop("max_unattended_duration_seconds"),  # REQUIRED
        lambda a: a.pop("max_unattended_budget"),  # REQUIRED
        lambda a: a.pop("unattended_authorizations"),  # REQUIRED field in §4
        lambda a: a["max_unattended_budget"].update(llm_tokens=None),  # §4.1 no None
        lambda a: a["max_unattended_budget"].pop("llm_cost_usd"),  # every dim explicit
        lambda a: a["max_unattended_budget"].update(tool_invocations=-1),  # >= 0
        lambda a: a["max_unattended_budget"].update(wall_clock_seconds=-0.5),  # >= 0
        lambda a: a["max_unattended_budget"].update(wall_clock_seconds=float("inf")),  # finite
        lambda a: a["max_unattended_budget"].update(wall_clock_seconds=float("nan")),  # finite
        lambda a: a["max_unattended_budget"].update(llm_tokens=True),  # no bool-as-int
        lambda a: a["max_unattended_budget"].update(llm_tokens="5"),  # no str coercion
        lambda a: a.update(exfil_simulation={"allowed": True, "byte_budget": -1}),  # >= 0
        lambda a: a.update(watchdog={"may_auto_stop": True, "confirm_window_seconds": 0}),  # 1..300
        lambda a: a.update(watchdog={"may_auto_stop": True}),  # default 0 invalid when true
        lambda a: a.update(watchdog={"may_auto_stop": True, "confirm_window_seconds": 301}),  # O1 max 300
        lambda a: a.update(api_key="sk-raw"),  # P: no raw credential field accepted
        lambda a: a["unattended_authorizations"][0].update(password="x"),  # P
    ],
)
def test_B29_B_invalid_autonomy_rejected(manifest_factory, signing_keypair, mutate):
    _, pub = signing_keypair
    a = copy.deepcopy(_auto())
    mutate(a)
    with pytest.raises(ManifestError):
        load_and_verify(manifest_factory(autonomy=a), pub)


def test_B29_B_unattended_budget_all_zero_ok():
    b = UnattendedBudget(**{k: 0 for k in BUDGET})  # §4 ">= 0" inclusive
    assert b.llm_tokens == 0


# N / §4.4 / O1
def test_B29_N_watchdog_rules():
    assert WATCHDOG_CONFIRM_WINDOW_MAX == 300
    w = WatchdogPolicy()
    assert w.may_auto_stop is False and w.confirm_window_seconds == 0
    assert WatchdogPolicy(may_auto_stop=False, confirm_window_seconds=999).may_auto_stop is False  # rule only when true
    for ok in (1, 30, 300):
        assert WatchdogPolicy(may_auto_stop=True, confirm_window_seconds=ok).confirm_window_seconds == ok
    for bad in (0, 301, -1):
        with pytest.raises(ValidationError):
            WatchdogPolicy(may_auto_stop=True, confirm_window_seconds=bad)


# §7 P1 amendment structure
@pytest.mark.parametrize(
    "am",
    [
        {"manifest_id": "", "reason": "r", "effective_at": T1.isoformat()},  # non-empty id
        {"manifest_id": None, "reason": "r", "effective_at": T1.isoformat()},
        {"reason": "r", "effective_at": T1.isoformat()},  # missing id
        {"manifest_id": "x", "reason": "", "effective_at": T1.isoformat()},  # non-empty reason
        {"manifest_id": "x", "effective_at": T1.isoformat()},  # missing reason
        {"manifest_id": "x", "reason": "r"},  # missing effective_at
        {"manifest_id": "x", "reason": "r", "effective_at": "2030-01-01T00:00:00"},  # naive
        {"manifest_id": "x", "reason": "r", "effective_at": "garbage"},  # malformed
        {"manifest_id": "x", "reason": "r", "effective_at": T1.isoformat(), "extra": 1},
    ],
)
def test_B29_M_amendment_structure_rejected(manifest_factory, signing_keypair, am):
    _, pub = signing_keypair
    with pytest.raises(ManifestError):
        load_and_verify(manifest_factory(amends=am), pub)


# C / §5: manifest_id
def test_B29_C_manifest_id_stable_and_order_independent(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    y = manifest_factory(autonomy=_auto())
    m1 = load_and_verify(y, pub)
    m2 = load_and_verify(y, pub)
    assert compute_manifest_id(m1) == compute_manifest_id(m2) == m1.manifest_id
    # Re-sign the same logical content with reversed key insertion order: identical id (§13 prop 8).
    raw = yaml.safe_load(y)
    sig = raw.pop("signature")
    reordered = {k: raw[k] for k in reversed(list(raw))}
    assert canonicalize(reordered) == canonicalize(raw)
    assert canonicalize(raw) == m1.canonical_content
    assert sig  # signature itself is not part of identity


def test_B29_C_any_content_change_changes_id(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    base = compute_manifest_id(load_and_verify(manifest_factory(autonomy=_auto()), pub))
    variants = [
        manifest_factory(autonomy=_auto(mode_max="calm")),
        manifest_factory(autonomy=_auto(max_unattended_duration_seconds=601)),
        manifest_factory(autonomy=_auto(), engagement={"client": "Other"}),
        manifest_factory(),
    ]
    ids = {compute_manifest_id(load_and_verify(v, pub)) for v in variants}
    assert base not in ids and len(ids) == len(variants)


# D: canonical-bytes regression
def test_B29_D_pre_autonomy_canonical_bytes_unchanged(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    y = manifest_factory()
    raw = yaml.safe_load(y)
    sig = raw.pop("signature")
    assert set(raw) == {"engagement", "scope"}  # optional keys absent => nothing added
    m = load_and_verify(y, pub)
    expected = yaml.safe_dump(raw, sort_keys=True, default_flow_style=False).encode("utf-8")
    assert m.canonical_content == expected  # byte-identical to pre-change canonicalization
    import base64

    pub.verify(base64.b64decode(sig), expected)  # signature verifies over those exact bytes


# E: verified-manifest boundary
def test_B29_E_boundary(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    m = load_and_verify(manifest_factory(), pub)
    assert isinstance(m, VerifiedManifest)
    bare = ScopeManifest(**dict(m))  # parsed object, not verified
    assert not isinstance(bare, VerifiedManifest)
    with pytest.raises(TypeError):
        compute_manifest_id(bare)
    # id covers signature-stripped, pre-_flatten content: no injected default keys
    content = yaml.safe_load(m.canonical_content)
    assert "destructive_allowed" in content["engagement"]  # factory supplies it explicitly
    assert "signature" not in content
    y2 = manifest_factory(engagement={})
    raw = yaml.safe_load(y2)
    raw["engagement"].pop("destructive_allowed")  # absent => _flatten would inject False
    raw.pop("signature")
    # id of a manifest lacking the key must not equal one with the defaulted key
    assert "destructive_allowed" not in yaml.safe_load(canonicalize(raw))["engagement"]


def test_B29_E_signature_tamper_of_autonomy_rejected(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    y = manifest_factory(autonomy=_auto(mode_max="calm"))
    with pytest.raises(ManifestError):
        load_and_verify(y.replace("mode_max: calm", "mode_max: beast"), pub)


def test_B29_O_parse_path_hermetic(manifest_factory, signing_keypair, b29_nonet):
    _, pub = signing_keypair
    m = load_and_verify(manifest_factory(autonomy=_auto()), pub)
    compute_manifest_id(m)


# P: secret safety
def test_B29_P_no_credential_fields():
    for model in (AutonomyEnvelope, UnattendedAuthorization, UnattendedBudget, WatchdogPolicy, AmendmentRef):
        for name in model.model_fields:
            assert not any(s in name.lower() for s in ("secret", "password", "token_value", "api_key", "credential"))
    from kronos.manifest import ExfilSimulation

    assert ExfilSimulation.model_fields["dataset_marker"].annotation == (str | None)
