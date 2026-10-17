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


# =============================================================================
# SPEC_BRIEF10.1 (amends PR #12, pre-merge) — the trailing-glob boundary rule.
# Everything above this line (SPEC_BRIEF10's own §5.1-§9.1) is unmodified.
# These tests are prefixed test_b101_ to avoid colliding with SPEC_BRIEF10's
# own §-numbered names above, which number a different document.
# =============================================================================

from kronos.scope_guard import classify_target  # noqa: E402


# --- G1-G6 — measured against PR #12 @ fa6285f (RED before this brief's fix,
# GREEN after). See SPEC_BRIEF10.1.md §0/§5.1.


def test_b101_g1_trailing_glob_does_not_cross_a_dns_label():
    m = _m(["api.acme.com*"], [])
    assert scope_guard("api.acme.com.attacker.net", m) is False
    assert scope_guard("https://api.acme.com.attacker.net/x", m) is False


def test_b101_g2_trailing_glob_does_not_expand_mid_label():
    m = _m(["api.acme.com*"], [])
    assert scope_guard("api.acme.com-evil.net", m) is False
    assert scope_guard("api.acme.comevil.net", m) is False  # mid-label, no separator at all


def test_b101_g3_localhost_trailing_glob_does_not_cross_a_dns_label():
    m = _m(["localhost*"], [])
    assert scope_guard("localhost.attacker.net", m) is False
    assert scope_guard("localhosted.attacker.net", m) is False  # mid-label


def test_b101_g4_ip_trailing_glob_does_not_cross_a_dns_label():
    m = _m(["127.0.0.1*"], [])
    assert scope_guard("127.0.0.1.attacker.net", m) is False


def test_b101_g5_url_pattern_trailing_host_glob_does_not_cross_a_dns_label():
    m = _m(["http://localhost*"], [])
    assert scope_guard("http://localhost.attacker.net/x", m) is False


def test_b101_g6_bucket_glob_pattern_never_authorizes_a_hostname_shaped_target():
    m = _m(["kronos-cybergym-*"], [])
    assert scope_guard("kronos-cybergym-x.attacker.net", m) is False
    # and an ARN-shaped version of the same pattern/target pairing:
    assert scope_guard("kronos-cybergym-x.attacker.net", _m(["arn:aws:s3:::kronos-cybergym-*"], [])) is False


# --- §5.2 — trailing-glob port semantics (§1.2 Option A). Rows 3 and 6 are
# pinned together in one test per the brief: "the host* vs host distinction
# cannot be flattened later."


def test_b101_5_2_trailing_glob_locks():
    m = _m(["api.acme.com*"], [])
    assert scope_guard("api.acme.com", m) is True
    assert scope_guard("api.acme.com:443", m) is True
    assert scope_guard("https://api.acme.com:8443/x", m) is True


def test_b101_5_2_trailing_glob_grants_all_ports_bare_host_does_not():
    assert scope_guard("api.acme.com:8443", _m(["api.acme.com*"], [])) is True  # row 3
    assert scope_guard("api.acme.com:22", _m(["api.acme.com*"], [])) is True  # documented consequence
    assert scope_guard("api.acme.com:8443", _m(["api.acme.com"], [])) is False  # row 6
    assert scope_guard("api.acme.com:8443", _m(["*.acme.com"], [])) is False  # row 7


# --- §5.3 — CyberGym's real manifest, as a permanent regression test. The
# in_scope list below is a literal copy of cybergym/generate_scope_manifest.py's
# MANIFEST_DICT["scope"]["in_scope"] (not imported — that file stays
# untouched and off-limits). If that list is ever edited, this copy must be
# updated by hand so it keeps proving the real range, not a stale one.

_CYBERGYM_IN_SCOPE = [
    "com.kronos.cybergym.*",
    "localhost*",
    "127.0.0.1*",
    "http://localhost*",
    "http://127.0.0.1*",
    "kronos-cybergym-*",
    "arn:aws:s3:::kronos-cybergym-*",
]


@pytest.mark.parametrize(
    "target,expected",
    [
        ("http://localhost:8091/internal/v1/export", True),  # chain 1 — a DENY here means X-score 0/3
        ("http://localhost:8091/health", True),  # S1's abstention arm
        ("http://127.0.0.1:8091/internal/v1/export", True),
        ("localhost:4566", True),  # LocalStack
        ("127.0.0.1:4566", True),
        ("localhost", True),
        ("kronos-cybergym-general-secrets", True),  # bucket, mid-label expansion
        ("kronos-cybergym-admin-secrets", True),
        ("arn:aws:s3:::kronos-cybergym-admin-secrets", True),
        ("localhost.attacker.net", False),
        ("127.0.0.1.attacker.net", False),
        ("kronos-cybergym-x.attacker.net", False),
        ("http://localhost.attacker.net:8091/x", False),
    ],
)
def test_b101_5_3_cybergym_real_manifest_matrix(target, expected):
    assert scope_guard(target, _m(_CYBERGYM_IN_SCOPE, [])) is expected


def test_b101_5_3_cybergym_chain_1_target_explicitly():
    """Called out per the brief: this single row IS the live X-score."""
    assert scope_guard("http://localhost:8091/internal/v1/export", _m(_CYBERGYM_IN_SCOPE, [])) is True


# --- §5.4 — exclusion precedence across equivalent representations. Deny
# stays broad/port-blind/boundary-rule-free; the boundary rule is allow-only.
# Each row is checked twice: WITH the exclusion (must DENY) and with the
# exclusion removed (must ALLOW), proving the deny came from the exclusion.


@pytest.mark.parametrize(
    "in_scope,excluded,target",
    [
        (["api.acme.com*"], "api.acme.com", "api.acme.com:8443"),
        (["api.acme.com*"], "api.acme.com", "https://api.acme.com/x"),
        (["localhost*"], "localhost", "localhost:4566"),
        (["kronos-cybergym-*"], "kronos-cybergym-admin-secrets", "kronos-cybergym-admin-secrets"),
        (
            ["arn:aws:s3:::kronos-cybergym-*"],
            "arn:aws:s3:::kronos-cybergym-admin-secrets",
            "arn:aws:s3:::kronos-cybergym-admin-secrets",
        ),
    ],
)
def test_b101_5_4_exclusion_precedence_attributed_to_exclusion(in_scope, excluded, target):
    assert scope_guard(target, _m(in_scope, [excluded])) is False
    assert scope_guard(target, _m(in_scope, [])) is True  # same target, exclusion removed -> allow


def test_b101_5_4_f1_un_regressed():
    assert scope_guard("https://10.0.0.5/admin", _m(["*"], ["10.0.0.5/32"])) is False


def test_b101_5_4_f3_un_regressed():
    assert scope_guard("[2001:db8::1]:443", _m(["*"], ["2001:db8::1/128"])) is False


# --- §5.6 — every caller shape reaching ScopeGuard, as a permanent test.
# `graph.py:140` (`self.scope.is_in_scope(scope_key or id)`) is the only
# call site in the tree (grep-verified against this branch head). The
# target string it receives depends on node type:
#
#   HOST            — the hostname/IP text itself (canonical.py's own
#                      documented convention) -> "host" or "ip".
#   MOBILE_APP       — the bundle id (dotted) -> "host" (§8.2/FORK-T:
#                      indistinguishable from a hostname by design).
#   SECRET           — scope_key=bundle_id, always, in every real ingester
#                      path (ingest/__init__.py, ingest/mobile/parser.py) ->
#                      same as MOBILE_APP, "host". The SECRET's own id
#                      (a sha256-derived token) is never the scope target.
#   API_ENDPOINT     — id=found.url, a full URL (ingest/mobile/parser.py:276)
#                      -> "url".
#   WEB_ENDPOINT     — no production ingester yet; same URL convention as
#                      API_ENDPOINT (SPEC_BRIEF9 §4.1) -> "url".
#   SERVICE          — no production ingester yet; SPEC.md's host:port dedup
#                      convention -> "host_port" or "ip_port".
#   PARAMETER        — no production ingester yet; compound raw id
#                      (e.g. "param:<parent>:<name>:<type>") has multiple
#                      colons, no scheme, and typically embeds a dotted
#                      parent -> falls through to "host" (opaque, never
#                      meaningfully glob-targeted by a host pattern).
#   FINDING          — no production ingester yet; an opaque id with no
#                      dot (hash/uuid-shaped) -> "bucket_name" — accepted:
#                      this is exactly its pre-SPEC_BRIEF10.1 (and
#                      pre-SPEC_BRIEF10) free-glob behavior, unchanged,
#                      since no legitimate pattern is ever written to
#                      host-boundary-match a FINDING id.
#   CLOUD_RESOURCE   — a bucket name or an ARN (validate/candidates.py's
#                      `_all_cloud_resources`) -> "bucket_name" or "arn".
#
# No shape appears here outside classify_target's taxonomy.


@pytest.mark.parametrize(
    "target,expected_shape,in_scope_pattern,expected_verdict",
    [
        ("api.acme.com", "host", "*.acme.com", True),  # HOST, dotted
        ("10.0.0.5", "ip", "10.0.0.0/24", True),  # HOST, bare IP
        ("com.kronos.demo", "host", "com.kronos.*", True),  # MOBILE_APP / SECRET scope_key
        ("https://api.acme.com/v1/x", "url", "api.acme.com*", True),  # API_ENDPOINT / WEB_ENDPOINT
        ("api.acme.com:8443", "host_port", "api.acme.com*", True),  # SERVICE, host:port
        ("10.0.5.10:443", "ip_port", "10.0.5.0/24", True),  # SERVICE, ip:port
        ("param:api.acme.com:id:query", "host", "api.acme.com*", False),  # PARAMETER, opaque compound
        ("finding:9f1c2b3a4d5e6f70", "bucket_name", "finding:*", True),  # FINDING, opaque dot-free
        ("kronos-cybergym-admin-secrets", "bucket_name", "kronos-cybergym-*", True),  # CLOUD_RESOURCE
        ("arn:aws:s3:::kronos-cybergym-admin-secrets", "arn", "arn:aws:s3:::kronos-cybergym-*", True),
    ],
)
def test_b101_5_6_caller_shape_enumeration(target, expected_shape, in_scope_pattern, expected_verdict):
    assert classify_target(target) == expected_shape
    assert scope_guard(target, _m([in_scope_pattern], [])) is expected_verdict


# --- FORK-U — a pattern with wildcards at both ends. DEFAULT: (1), PR #12's
# current verdict unchanged — such a pattern is NOT treated as a host
# pattern for trailing-glob purposes, so it keeps denying a nonstandard port
# rather than being harmonized with §1.2's "any port" rule.


def test_b101_fork_u_both_ends_wildcard_is_not_a_host_pattern():
    assert scope_guard("api.acme.com:8443", _m(["*.acme.com*"], [])) is False


# --- §5.7 structural/robustness — carried forward from SPEC_BRIEF10 §5.8
# unchanged (see test_5_8_* above); re-run as part of the full suite, not
# duplicated here.


# =============================================================================
# SPEC_BRIEF10.2 (amends PR #12) — explicit-port URL patterns must obey the
# structural host/port comparison, not raw-string prefix. Prefixed
# test_b102_ to avoid colliding with SPEC_BRIEF10/10.1's own §-numbered names
# above, which number different documents.
# =============================================================================


# --- H1a-H1d — measured against d0e5232 (RED before this brief's fix, GREEN
# after). in_scope = ['http://localhost:8091*'] for every H1 case.


def test_b102_h1a_userinfo_resolves_to_the_real_host():
    m = _m(["http://localhost:8091*"], [])
    assert scope_guard("http://localhost:8091@evil.net/x", m) is False


def test_b102_h1b_lookalike_suffix_on_the_port_is_not_a_port():
    m = _m(["http://localhost:8091*"], [])
    assert scope_guard("http://localhost:8091.attacker.net/x", m) is False


def test_b102_h1c_different_numeric_port_sharing_a_prefix_is_not_the_same_port():
    m = _m(["http://localhost:8091*"], [])
    assert scope_guard("http://localhost:80915/x", m) is False


def test_b102_h1d_trailing_garbage_on_the_port_is_not_a_port():
    m = _m(["http://localhost:8091*"], [])
    assert scope_guard("http://localhost:8091evil.net/x", m) is False


# --- §2 — the whole specification, both tables, as parametrized matrices.


@pytest.mark.parametrize(
    "target,expected",
    [
        ("http://localhost:8091/internal/v1/export", True),  # lock — chain 1
        ("http://localhost:8091/health", True),  # lock
        ("http://localhost:8091/x?q=1#f", True),  # path/query/fragment unrestricted
        ("http://localhost:8091", True),  # bare, port matches
        ("http://localhost:8091@evil.net/x", False),  # H1a
        ("http://localhost:8091.attacker.net/x", False),  # H1b
        ("http://localhost:80915/x", False),  # H1c
        ("http://localhost:8091evil.net/x", False),  # H1d
        ("http://localhost:9091/x", False),  # different port
        ("http://localhost/x", False),  # a port entry does not authorize the portless form
        ("https://localhost:8091/x", False),  # scheme must match
        ("http://127.0.0.1:8091/x", False),  # different host
    ],
)
def test_b102_section2_allow_table(target, expected):
    assert scope_guard(target, _m(["http://localhost:8091*"], [])) is expected


@pytest.mark.parametrize(
    "target",
    [
        "http://localhost:8091/x",
        "http://localhost:9091/x",  # exclusions are port-blind (rule 6)
        "http://localhost/x",  # exclusions are representation-blind
    ],
)
def test_b102_section2_exclusion_table(target):
    assert scope_guard(target, _m(["*"], ["http://localhost:8091*"])) is False


# --- The nine pre-existing tests using http://localhost:8091* (listed in the
# brief: tests/test_negative_controls.py (2), tests/test_validate_candidates.py
# (1), tests/test_validate_runner.py (6)) are NOT duplicated or modified here
# — this brief's acceptance criteria require them to pass completely
# unmodified, verified by running the full suite (see report).


# --- G1-G6 re-run (SPEC_BRIEF10.1) — must still all DENY.


def test_b102_g1_still_denies():
    m = _m(["api.acme.com*"], [])
    assert scope_guard("api.acme.com.attacker.net", m) is False
    assert scope_guard("https://api.acme.com.attacker.net/x", m) is False


def test_b102_g2_still_denies():
    m = _m(["api.acme.com*"], [])
    assert scope_guard("api.acme.com-evil.net", m) is False
    assert scope_guard("api.acme.comevil.net", m) is False


def test_b102_g3_still_denies():
    m = _m(["localhost*"], [])
    assert scope_guard("localhost.attacker.net", m) is False
    assert scope_guard("localhosted.attacker.net", m) is False


def test_b102_g4_still_denies():
    assert scope_guard("127.0.0.1.attacker.net", _m(["127.0.0.1*"], [])) is False


def test_b102_g5_still_denies():
    assert scope_guard("http://localhost.attacker.net/x", _m(["http://localhost*"], [])) is False


def test_b102_g6_still_denies():
    m = _m(["kronos-cybergym-*"], [])
    assert scope_guard("kronos-cybergym-x.attacker.net", m) is False
    assert scope_guard("kronos-cybergym-x.attacker.net", _m(["arn:aws:s3:::kronos-cybergym-*"], [])) is False


# --- Robustness: a malformed explicit-port-glob pattern must stay a boolean,
# never raise, and never ALLOW a target whose real host differs from the
# pattern's.


@pytest.mark.parametrize(
    "pattern",
    [
        "http://localhost:*",
        "http://:8091*",
        "http://localhost:abc*",
        "http://localhost:8091:9091*",
    ],
)
def test_b102_robustness_malformed_explicit_port_glob_pattern(pattern):
    m = _m([pattern], [])
    assert scope_guard("http://localhost:8091/x", m) in (True, False)
    assert scope_guard("http://evil.net:8091/x", m) is False
    assert scope_guard("http://localhost:9091/x", m) in (True, False)
