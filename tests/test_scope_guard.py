from datetime import datetime, timezone

import pytest

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


def test_cidr_excluded_still_blocks_ip_port_target():
    """Final review Important #3: a CIDR exclusion must still deny an
    'ip:port'-style target (e.g. a SERVICE node id like
    "10.0.5.10:443") — SPEC.md explicitly uses host:port-shaped ids for
    dedup, so scope_guard must not let the port suffix smuggle an
    excluded IP past the CIDR check and fall through to an unrelated,
    looser in-scope glob that happens to match the raw string."""
    m = _m(["10.0.*"], ["10.0.5.0/24"])
    assert scope_guard("10.0.5.10:443", m) is False
    assert scope_guard("10.0.1.10:443", m) is True


# ---------------------------------------------------------------------------
# SPEC_BRIEF10 (FORK-2) — the §5 acceptance matrix is the specification.
# Every row below is additive: nothing above this line was touched.
# ---------------------------------------------------------------------------


# §5.1 — exclusion survives every equivalent representation (F1/F2/F3 + more)


def test_5_1_f1_cidr32_exclusion_survives_url_representation():
    m = _m(["*"], ["10.0.0.5/32"])
    assert scope_guard("https://10.0.0.5/admin", m) is False


def test_5_1_f2_bare_ip_exclusion_survives_url_representation():
    m = _m(["*"], ["10.0.0.5"])
    assert scope_guard("https://10.0.0.5/admin", m) is False


def test_5_1_f3_ipv6_cidr_exclusion_survives_bracket_port_representation():
    m = _m(["*"], ["2001:db8::1/128"])
    assert scope_guard("[2001:db8::1]:443", m) is False


def test_5_1_bare_ip_exclusion_survives_ip_port_representation():
    m = _m(["*"], ["10.0.0.5"])
    assert scope_guard("10.0.0.5:443", m) is False


def test_5_1_cidr32_exclusion_survives_bare_ip_representation():
    m = _m(["*"], ["10.0.0.5/32"])
    assert scope_guard("10.0.0.5", m) is False


def test_5_1_host_exclusion_covers_nonstandard_port_deny_is_broad():
    m = _m(["*"], ["api.acme.com"])
    assert scope_guard("api.acme.com:8443", m) is False


def test_5_1_host_exclusion_covers_url_form():
    m = _m(["*"], ["api.acme.com"])
    assert scope_guard("https://api.acme.com/v1/x", m) is False


def test_5_1_host_exclusion_covers_url_form_at_nonstandard_port():
    m = _m(["*"], ["api.acme.com"])
    assert scope_guard("https://api.acme.com:8443/v1/x", m) is False


def test_5_1_bare_ipv6_exclusion_survives_bare_ipv6_representation():
    m = _m(["*"], ["2001:db8::1"])
    assert scope_guard("2001:db8::1", m) is False


# §5.2 — exclusion precedence beats a broader allow


def test_5_2_exact_host_exclusion_beats_subdomain_allow():
    m = _m(["*.acme.com"], ["secret.acme.com"])
    assert scope_guard("secret.acme.com", m) is False


def test_5_2_exact_host_exclusion_beats_subdomain_allow_url_form():
    m = _m(["*.acme.com"], ["secret.acme.com"])
    assert scope_guard("https://secret.acme.com/x", m) is False


def test_5_2_bare_ip_exclusion_beats_broader_cidr_allow():
    m = _m(["10.0.5.0/24"], ["10.0.5.10"])
    assert scope_guard("10.0.5.10:443", m) is False


def test_5_2_cidr32_exclusion_beats_broader_cidr_allow_url_form():
    m = _m(["10.0.5.0/24"], ["10.0.5.10/32"])
    assert scope_guard("https://10.0.5.10/x", m) is False


def test_5_2_exclusion_outranks_an_explicit_port_entry():
    m = _m(["api.acme.com:8443"], ["api.acme.com"])
    assert scope_guard("https://api.acme.com:8443/x", m) is False


# §5.3 — subdomain and apex (§1.1 rule 1) — (lock) rows confirmed un-regressed


def test_5_3_lock_subdomain_allowed():
    assert scope_guard("api.acme.com", _m(["*.acme.com"], [])) is True


def test_5_3_lock_subdomain_any_depth_allowed():
    assert scope_guard("a.b.acme.com", _m(["*.acme.com"], [])) is True


def test_5_3_lock_apex_not_authorized_by_subdomain_glob():
    assert scope_guard("acme.com", _m(["*.acme.com"], [])) is False


def test_5_3_explicit_apex_entry_allows_apex():
    assert scope_guard("acme.com", _m(["acme.com"], [])) is True


def test_5_3_explicit_apex_entry_is_not_a_wildcard():
    assert scope_guard("api.acme.com", _m(["acme.com"], [])) is False


# §5.4 — standard-port inheritance (§1.1 rules 2-3) — F6/F6b/F6c/F7'/F7''


def test_5_4_f6_https_standard_implicit_port_url_allowed():
    assert scope_guard("https://api.acme.com/v1/users", _m(["*.acme.com"], [])) is True


def test_5_4_f6b_http_standard_implicit_port_url_allowed():
    assert scope_guard("http://api.acme.com/v1/x", _m(["*.acme.com"], [])) is True


def test_5_4_f6c_https_standard_explicit_port_url_allowed():
    assert scope_guard("https://api.acme.com:443/v1/x", _m(["*.acme.com"], [])) is True


def test_5_4_http_standard_explicit_port_url_allowed():
    assert scope_guard("http://api.acme.com:80/x", _m(["*.acme.com"], [])) is True


def test_5_4_f7prime_bare_host_standard_https_port_allowed():
    assert scope_guard("api.acme.com:443", _m(["*.acme.com"], [])) is True


def test_5_4_f7doubleprime_bare_host_standard_http_port_allowed():
    assert scope_guard("api.acme.com:80", _m(["*.acme.com"], [])) is True


def test_5_4_path_query_fragment_irrelevant_to_authorization():
    assert scope_guard("https://api.acme.com/x?q=1#frag", _m(["*.acme.com"], [])) is True


# §5.5 — nonstandard ports require an explicit entry (§1.1 rule 4) + F8


def test_5_5_lock_subdomain_glob_denies_nonstandard_port_host():
    assert scope_guard("api.acme.com:8443", _m(["*.acme.com"], [])) is False


def test_5_5_lock_subdomain_glob_denies_nonstandard_port_url():
    assert scope_guard("https://api.acme.com:8443/x", _m(["*.acme.com"], [])) is False


def test_5_5_lock_explicit_port_entry_allows_bare_host_port():
    assert scope_guard("api.acme.com:8443", _m(["api.acme.com:8443"], [])) is True


def test_5_5_f8_explicit_port_entry_covers_its_url_form():
    assert scope_guard("https://api.acme.com:8443/x", _m(["api.acme.com:8443"], [])) is True


def test_5_5_explicit_port_entry_is_one_port_not_a_range():
    assert scope_guard("api.acme.com:9443", _m(["api.acme.com:8443"], [])) is False


def test_5_5_explicit_port_entry_does_not_authorize_bare_host():
    assert scope_guard("api.acme.com", _m(["api.acme.com:8443"], [])) is False


def test_5_5_nonstandard_http_port_denied():
    assert scope_guard("http://api.acme.com:8080/x", _m(["*.acme.com"], [])) is False


# §5.5b — CIDR/bare-IP entries authorize ALL ports (§1.1 rule 7) — port-blind allow


def test_5_5b_lock_cidr_allows_bare_ip():
    assert scope_guard("10.0.5.10", _m(["10.0.5.0/24"], [])) is True


def test_5_5b_lock_cidr_allows_standard_port():
    assert scope_guard("10.0.5.10:443", _m(["10.0.5.0/24"], [])) is True


def test_5_5b_cidr_allows_nonstandard_port_port_blind():
    assert scope_guard("10.0.5.10:8443", _m(["10.0.5.0/24"], [])) is True


def test_5_5b_cidr_allows_any_port():
    assert scope_guard("10.0.5.10:22", _m(["10.0.5.0/24"], [])) is True


def test_5_5b_cidr_allows_url_form():
    assert scope_guard("https://10.0.5.10/x", _m(["10.0.5.0/24"], [])) is True


def test_5_5b_cidr_allows_url_form_at_nonstandard_port():
    assert scope_guard("https://10.0.5.10:8443/x", _m(["10.0.5.0/24"], [])) is True


def test_5_5b_bare_ip_entry_is_also_port_blind():
    assert scope_guard("10.0.5.10:9999", _m(["10.0.5.10"], [])) is True


def test_5_5b_cidr_denies_outside_the_network():
    assert scope_guard("10.0.6.10:443", _m(["10.0.5.0/24"], [])) is False


def test_5_5b_ipv6_cidr_allows_nonstandard_port():
    assert scope_guard("[2001:db8::1]:8443", _m(["2001:db8::/32"], [])) is True


def test_5_5b_ipv6_cidr_denies_outside_the_network():
    assert scope_guard("[2001:db9::1]:443", _m(["2001:db8::/32"], [])) is False


def test_5_5b_cross_shape_asymmetry_pinned_in_one_call():
    """The specification, not an inconsistency: an address-shaped entry
    is port-blind on the allow side; the hostname-shaped equivalent, in
    the very same manifest, is not. A later "cleanup" that unifies the
    two must break this test."""
    m = _m(["10.0.5.0/24", "*.acme.com"], [])
    assert scope_guard("10.0.5.10:8443", m) is True
    assert scope_guard("api.acme.com:8443", m) is False


def test_5_5b_exclusions_stay_port_blind_for_address_shape_too():
    m = _m(["10.0.5.0/24"], ["10.0.5.10"])
    for target in (
        "10.0.5.10",
        "10.0.5.10:443",
        "10.0.5.10:8443",
        "10.0.5.10:22",
        "https://10.0.5.10/x",
        "https://10.0.5.10:8443/x",
    ):
        assert scope_guard(target, m) is False


# §5.6 — no authorization transfer via URL content (§1.1 rule 5 / FORK-S)


def test_5_6_f4_substring_glob_denies_via_query_string():
    assert scope_guard("https://evil.net/?next=acme.com/x", _m(["*acme.com*"], [])) is False


def test_5_6_no_transfer_via_redirect_query_parameter():
    assert scope_guard("https://evil.net/redirect?to=api.acme.com", _m(["*.acme.com"], [])) is False


def test_5_6_no_transfer_via_host_suffix_confusion():
    assert scope_guard("https://api.acme.com.attacker.net/x", _m(["*.acme.com"], [])) is False


def test_5_6_no_transfer_via_bare_host_suffix_confusion():
    assert scope_guard("x.acme.com.attacker.net", _m(["*.acme.com"], [])) is False


def test_5_6_no_transfer_via_fragment():
    assert scope_guard("https://evil.net/#api.acme.com", _m(["*.acme.com"], [])) is False


def test_5_6_no_transfer_via_userinfo_user_pass_form():
    assert scope_guard("https://user:pass@evil.net/x", _m(["*.acme.com"], [])) is False


def test_5_6_no_transfer_via_userinfo_host_confusion_form():
    """§8.6: the real host is evil.net; urlsplit().hostname agrees."""
    assert scope_guard("https://api.acme.com@evil.net/x", _m(["*.acme.com"], [])) is False


# §5.7 — bundle id vs hostname (FORK-T) — (lock) rows confirmed un-regressed


def test_5_7_lock_bundle_glob_allows_bundle_id():
    assert scope_guard("com.acme.mobile", _m(["com.acme.*"], [])) is True


def test_5_7_f5_bundle_glob_denies_multi_label_hostname_suffix():
    assert scope_guard("com.acme.evil.attacker.net", _m(["com.acme.*"], [])) is False


def test_5_7_lock_host_glob_does_not_catch_bundle_id():
    assert scope_guard("com.acme.mobile", _m(["*.acme.com"], [])) is False


# §5.8 — structural properties


def test_5_8_default_deny_on_empty_in_scope():
    assert scope_guard("api.acme.com", _m([], [])) is False
    assert scope_guard("acme.com", _m([], [])) is False
    assert scope_guard("api.acme.com:8443", _m([], [])) is False


@pytest.mark.parametrize(
    ("in_scope", "excluded", "target"),
    [
        (["*"], ["10.0.0.5/32"], "https://10.0.0.5/admin"),
        (["*"], ["10.0.0.5"], "https://10.0.0.5/admin"),
        (["*"], ["2001:db8::1/128"], "[2001:db8::1]:443"),
        (["*.acme.com"], ["secret.acme.com"], "secret.acme.com"),
        (["*.acme.com"], ["secret.acme.com"], "https://secret.acme.com/x"),
        (["10.0.5.0/24"], ["10.0.5.10"], "10.0.5.10:443"),
        (["10.0.5.0/24"], ["10.0.5.10/32"], "https://10.0.5.10/x"),
        (["api.acme.com:8443"], ["api.acme.com"], "https://api.acme.com:8443/x"),
    ],
)
def test_5_8_exclusion_ordering_is_structural_not_default_deny(in_scope, excluded, target):
    """§7.9's lesson: a DENY that would also happen by default-deny
    proves nothing about exclusion precedence. Assert the same target is
    ALLOW once its exclusion is removed, so the denial above is
    provably coming from the exclusion itself."""
    assert scope_guard(target, _m(in_scope, excluded)) is False
    assert scope_guard(target, _m(in_scope, [])) is True


def test_5_8_pure_and_idempotent():
    m = _m(["*.acme.com"], ["secret.acme.com"])
    first = scope_guard("api.acme.com", m)
    second = scope_guard("api.acme.com", m)
    assert first is second is True


@pytest.mark.parametrize(
    "target",
    [
        "",
        "   ",
        "://",
        "http://",
        "a" * 4096,
        "10.0.0.0/not-a-valid-cidr-but-has-a-slash",
    ],
)
def test_5_8_no_crash_on_junk_target(target):
    assert scope_guard(target, _m(["*.acme.com", "10.0.0.0/24"], ["evil.com"])) is False


def test_5_8_no_crash_on_junk_pattern():
    m = _m(["not/valid/cidr", "*"], [])
    assert scope_guard("anything", m) is True


# §8.4 — IPv6 forms not explicitly probed by the F1-F8 measurements, but
# flagged as open questions to verify, not leave quietly unresolved.


def test_8_4_ipv4_mapped_exclusion_is_not_a_bypass():
    m = _m(["*"], ["10.0.0.5"])
    assert scope_guard("::ffff:10.0.0.5", m) is False


def test_8_4_zone_index_does_not_bypass_exclusion():
    m = _m(["*"], ["fe80::1"])
    assert scope_guard("fe80::1%eth0", m) is False


def test_8_4_compressed_vs_expanded_ipv6_are_equivalent():
    m = _m(["*"], ["2001:db8::1"])
    assert scope_guard("2001:0db8:0000:0000:0000:0000:0000:0001", m) is False


# §9 criterion 1 — manifest.py is a zero-line diff; a manifest signed
# BEFORE this brief must still verify. This exact YAML (signature
# included) was generated and captured independently, against the
# unmodified `sign_manifest`, before any scope_guard.py edit in this
# brief landed -- it is not re-signed here. If manifest.py's wire format
# or signing had changed at all, `load_and_verify` below would reject
# this literal, pre-captured blob with ManifestError.

_PRE_BRIEF10_PUBKEY_B64 = "dcmpyXAt2CzzlUqtwFueAu1y6DVLlqSkwmvuenxmiqQ="

_PRE_BRIEF10_SIGNED_MANIFEST = """\
engagement:
  authorized_by: Acme CISO
  client: Acme Corp
  destructive_allowed: false
  id: pre-brief10-manifest
  window_end: '2126-01-01T00:00:00+00:00'
  window_start: '2026-01-01T00:00:00+00:00'
scope:
  excluded:
  - secret.acme.com
  in_scope:
  - '*.acme.com'
  - 10.0.5.0/24
signature: MtCzIa+pdlmt93c/wB022ScRRV/EwhT9AlPPzdqSjlxS2MLDdqn0gIhUgmBOzBQxVJDDKI9oE1VP2PFR7VFUCw==
"""


def test_9_1_a_manifest_signed_before_this_brief_still_verifies():
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from kronos.manifest import load_and_verify

    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(_PRE_BRIEF10_PUBKEY_B64))
    manifest = load_and_verify(_PRE_BRIEF10_SIGNED_MANIFEST, pub)

    assert manifest.engagement_id == "pre-brief10-manifest"
    # And the new matcher behaves exactly per §1.1 against it, unsurprising
    # since manifest.py (the thing being proven unchanged) never touches
    # matching at all -- this is scope_guard.py's own regression proof,
    # layered on top of the signature-verifies proof above.
    assert scope_guard("api.acme.com", manifest) is True  # subdomain, bare host
    assert scope_guard("acme.com", manifest) is False  # apex, not authorized
    assert scope_guard("secret.acme.com", manifest) is False  # excluded wins
    assert scope_guard("10.0.5.10:8443", manifest) is True  # CIDR, port-blind
    assert scope_guard("api.acme.com:8443", manifest) is False  # nonstandard port, no entry
