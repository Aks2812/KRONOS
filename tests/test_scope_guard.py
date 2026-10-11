from datetime import datetime, timezone

from kronos.manifest import ScopeManifest
from kronos.scope_guard import scope_guard

_NOW = datetime.now(timezone.utc)


def _m(in_scope, excluded):
    return ScopeManifest(
        engagement_id="e",
        client="c",
        authorized_by="a",
        window_start=_NOW,
        window_end=_NOW,
        in_scope=in_scope,
        excluded=excluded,
    )


def test_fqdn_glob_allows_match():
    assert scope_guard("api.acme.example.com", _m(["*.acme.example.com"], [])) is True


def test_default_deny_when_no_match():
    assert scope_guard("evil.com", _m(["*.acme.example.com"], [])) is False


def test_excluded_wins_over_in_scope_overlap():
    m = _m(["*.acme.example.com"], ["internal.acme.example.com"])
    assert scope_guard("internal.acme.example.com", m) is False
    assert scope_guard("api.acme.example.com", m) is True


def test_cidr_in_scope():
    m = _m(["10.0.0.0/24"], [])
    assert scope_guard("10.0.0.5", m) is True
    assert scope_guard("10.0.1.5", m) is False


def test_cidr_excluded_overrides():
    m = _m(["10.0.0.0/16"], ["10.0.5.0/24"])
    assert scope_guard("10.0.5.10", m) is False
    assert scope_guard("10.0.1.10", m) is True


def test_url_pattern_glob():
    m = _m(["https://api.acme.example.com/v1/*"], [])
    assert scope_guard("https://api.acme.example.com/v1/users", m) is True
    assert scope_guard("https://api.acme.example.com/v2/users", m) is False


def test_mobile_bundle_id_glob():
    m = _m(["com.acme.*"], [])
    assert scope_guard("com.acme.mobileapp", m) is True
    assert scope_guard("com.evil.app", m) is False
