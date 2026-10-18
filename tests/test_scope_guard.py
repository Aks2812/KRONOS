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


def _sg(target, manifest, node_type="HOST", target_kind="id"):
    """SPEC_BRIEF10.3 made `node_type` a required kwarg on the real
    `scope_guard`/`is_in_scope` -- correctly, per §1.1's fail-closed
    rule -- but every test above this brief's own section was written
    testing hostname/IP/CIDR matching semantics before `node_type`
    existed at all, with no node-type concept in mind. This file-local
    wrapper (not a production path, so not subject to §1.1's
    no-permissive-default rule) defaults to `"HOST"`, the correct type
    for the overwhelming majority of those pre-existing call sites, and
    every call this brief's edits route through a different node type
    (CLOUD_RESOURCE, MOBILE_APP, API_ENDPOINT, SERVICE, ...) passes it
    explicitly rather than relying on the default.

    SPEC_BRIEF10.4 §1.1 adds a second required kwarg, `target_kind`.
    Every test above this brief's own §5.1-§5.4 section was written
    testing the id-shape family filter (`_effective_shape`,
    node-type-gated) before the id/scope_key distinction existed at
    all -- the string each of those tests passes in IS the target's
    id, never an operator-supplied scope_key -- so this wrapper
    defaults `target_kind` to `"id"`, preserving every one of those
    tests' meaning exactly. This brief's own §5.2 scope_key cases pass
    `target_kind="scope_key"` explicitly."""
    return scope_guard(target, manifest, node_type=node_type, target_kind=target_kind)


def test_fqdn_glob_allows_match():
    assert _sg("api.acme.example.com", _m(["*.acme.example.com"], [])) is True


def test_default_deny_when_no_match():
    assert _sg("evil.com", _m(["*.acme.example.com"], [])) is False


def test_excluded_wins_over_in_scope_overlap():
    m = _m(["*.acme.example.com"], ["internal.acme.example.com"])
    assert _sg("internal.acme.example.com", m) is False
    assert _sg("api.acme.example.com", m) is True


def test_cidr_in_scope():
    m = _m(["10.0.0.0/24"], [])
    assert _sg("10.0.0.5", m) is True
    assert _sg("10.0.1.5", m) is False


def test_cidr_excluded_overrides():
    m = _m(["10.0.0.0/16"], ["10.0.5.0/24"])
    assert _sg("10.0.5.10", m) is False
    assert _sg("10.0.1.10", m) is True


def test_url_pattern_glob():
    m = _m(["https://api.acme.example.com/v1/*"], [])
    assert _sg("https://api.acme.example.com/v1/users", m, "API_ENDPOINT") is True
    assert _sg("https://api.acme.example.com/v2/users", m, "API_ENDPOINT") is False


def test_mobile_bundle_id_glob():
    m = _m(["com.acme.*"], [])
    assert _sg("com.acme.mobileapp", m) is True
    assert _sg("com.evil.app", m) is False


def test_cidr_excluded_still_blocks_ip_port_target():
    """Final review Important #3: a CIDR exclusion must still deny an
    'ip:port'-style target (e.g. a SERVICE node id like
    "10.0.5.10:443") — SPEC.md explicitly uses host:port-shaped ids for
    dedup, so scope_guard must not let the port suffix smuggle an
    excluded IP past the CIDR check and fall through to an unrelated,
    looser in-scope glob that happens to match the raw string."""
    m = _m(["10.0.*"], ["10.0.5.0/24"])
    assert _sg("10.0.5.10:443", m) is False
    assert _sg("10.0.1.10:443", m) is True


# ---------------------------------------------------------------------------
# SPEC_BRIEF10 (FORK-2) — the §5 acceptance matrix is the specification.
# Every row below is additive: nothing above this line was touched.
# ---------------------------------------------------------------------------


# §5.1 — exclusion survives every equivalent representation (F1/F2/F3 + more)


def test_5_1_f1_cidr32_exclusion_survives_url_representation():
    m = _m(["*"], ["10.0.0.5/32"])
    assert _sg("https://10.0.0.5/admin", m, "API_ENDPOINT") is False


def test_5_1_f2_bare_ip_exclusion_survives_url_representation():
    m = _m(["*"], ["10.0.0.5"])
    assert _sg("https://10.0.0.5/admin", m, "API_ENDPOINT") is False


def test_5_1_f3_ipv6_cidr_exclusion_survives_bracket_port_representation():
    m = _m(["*"], ["2001:db8::1/128"])
    assert _sg("[2001:db8::1]:443", m) is False


def test_5_1_bare_ip_exclusion_survives_ip_port_representation():
    m = _m(["*"], ["10.0.0.5"])
    assert _sg("10.0.0.5:443", m) is False


def test_5_1_cidr32_exclusion_survives_bare_ip_representation():
    m = _m(["*"], ["10.0.0.5/32"])
    assert _sg("10.0.0.5", m) is False


def test_5_1_host_exclusion_covers_nonstandard_port_deny_is_broad():
    m = _m(["*"], ["api.acme.com"])
    assert _sg("api.acme.com:8443", m) is False


def test_5_1_host_exclusion_covers_url_form():
    m = _m(["*"], ["api.acme.com"])
    assert _sg("https://api.acme.com/v1/x", m, "API_ENDPOINT") is False


def test_5_1_host_exclusion_covers_url_form_at_nonstandard_port():
    m = _m(["*"], ["api.acme.com"])
    assert _sg("https://api.acme.com:8443/v1/x", m, "API_ENDPOINT") is False


def test_5_1_bare_ipv6_exclusion_survives_bare_ipv6_representation():
    m = _m(["*"], ["2001:db8::1"])
    assert _sg("2001:db8::1", m) is False


# §5.2 — exclusion precedence beats a broader allow


def test_5_2_exact_host_exclusion_beats_subdomain_allow():
    m = _m(["*.acme.com"], ["secret.acme.com"])
    assert _sg("secret.acme.com", m) is False


def test_5_2_exact_host_exclusion_beats_subdomain_allow_url_form():
    m = _m(["*.acme.com"], ["secret.acme.com"])
    assert _sg("https://secret.acme.com/x", m, "API_ENDPOINT") is False


def test_5_2_bare_ip_exclusion_beats_broader_cidr_allow():
    m = _m(["10.0.5.0/24"], ["10.0.5.10"])
    assert _sg("10.0.5.10:443", m) is False


def test_5_2_cidr32_exclusion_beats_broader_cidr_allow_url_form():
    m = _m(["10.0.5.0/24"], ["10.0.5.10/32"])
    assert _sg("https://10.0.5.10/x", m, "API_ENDPOINT") is False


def test_5_2_exclusion_outranks_an_explicit_port_entry():
    m = _m(["api.acme.com:8443"], ["api.acme.com"])
    assert _sg("https://api.acme.com:8443/x", m, "API_ENDPOINT") is False


# §5.3 — subdomain and apex (§1.1 rule 1) — (lock) rows confirmed un-regressed


def test_5_3_lock_subdomain_allowed():
    assert _sg("api.acme.com", _m(["*.acme.com"], [])) is True


def test_5_3_lock_subdomain_any_depth_allowed():
    assert _sg("a.b.acme.com", _m(["*.acme.com"], [])) is True


def test_5_3_lock_apex_not_authorized_by_subdomain_glob():
    assert _sg("acme.com", _m(["*.acme.com"], [])) is False


def test_5_3_explicit_apex_entry_allows_apex():
    assert _sg("acme.com", _m(["acme.com"], [])) is True


def test_5_3_explicit_apex_entry_is_not_a_wildcard():
    assert _sg("api.acme.com", _m(["acme.com"], [])) is False


# §5.4 — standard-port inheritance (§1.1 rules 2-3) — F6/F6b/F6c/F7'/F7''


def test_5_4_f6_https_standard_implicit_port_url_allowed():
    assert _sg("https://api.acme.com/v1/users", _m(["*.acme.com"], []), "API_ENDPOINT") is True


def test_5_4_f6b_http_standard_implicit_port_url_allowed():
    assert _sg("http://api.acme.com/v1/x", _m(["*.acme.com"], []), "API_ENDPOINT") is True


def test_5_4_f6c_https_standard_explicit_port_url_allowed():
    assert _sg("https://api.acme.com:443/v1/x", _m(["*.acme.com"], []), "API_ENDPOINT") is True


def test_5_4_http_standard_explicit_port_url_allowed():
    assert _sg("http://api.acme.com:80/x", _m(["*.acme.com"], []), "API_ENDPOINT") is True


def test_5_4_f7prime_bare_host_standard_https_port_allowed():
    assert _sg("api.acme.com:443", _m(["*.acme.com"], [])) is True


def test_5_4_f7doubleprime_bare_host_standard_http_port_allowed():
    assert _sg("api.acme.com:80", _m(["*.acme.com"], [])) is True


def test_5_4_path_query_fragment_irrelevant_to_authorization():
    assert _sg("https://api.acme.com/x?q=1#frag", _m(["*.acme.com"], []), "API_ENDPOINT") is True


# §5.5 — nonstandard ports require an explicit entry (§1.1 rule 4) + F8


def test_5_5_lock_subdomain_glob_denies_nonstandard_port_host():
    assert _sg("api.acme.com:8443", _m(["*.acme.com"], [])) is False


def test_5_5_lock_subdomain_glob_denies_nonstandard_port_url():
    assert _sg("https://api.acme.com:8443/x", _m(["*.acme.com"], []), "API_ENDPOINT") is False


def test_5_5_lock_explicit_port_entry_allows_bare_host_port():
    assert _sg("api.acme.com:8443", _m(["api.acme.com:8443"], [])) is True


def test_5_5_f8_explicit_port_entry_covers_its_url_form():
    assert _sg("https://api.acme.com:8443/x", _m(["api.acme.com:8443"], []), "API_ENDPOINT") is True


def test_5_5_explicit_port_entry_is_one_port_not_a_range():
    assert _sg("api.acme.com:9443", _m(["api.acme.com:8443"], [])) is False


def test_5_5_explicit_port_entry_does_not_authorize_bare_host():
    assert _sg("api.acme.com", _m(["api.acme.com:8443"], [])) is False


def test_5_5_nonstandard_http_port_denied():
    assert _sg("http://api.acme.com:8080/x", _m(["*.acme.com"], []), "API_ENDPOINT") is False


# §5.5b — CIDR/bare-IP entries authorize ALL ports (§1.1 rule 7) — port-blind allow


def test_5_5b_lock_cidr_allows_bare_ip():
    assert _sg("10.0.5.10", _m(["10.0.5.0/24"], [])) is True


def test_5_5b_lock_cidr_allows_standard_port():
    assert _sg("10.0.5.10:443", _m(["10.0.5.0/24"], [])) is True


def test_5_5b_cidr_allows_nonstandard_port_port_blind():
    assert _sg("10.0.5.10:8443", _m(["10.0.5.0/24"], [])) is True


def test_5_5b_cidr_allows_any_port():
    assert _sg("10.0.5.10:22", _m(["10.0.5.0/24"], [])) is True


def test_5_5b_cidr_allows_url_form():
    assert _sg("https://10.0.5.10/x", _m(["10.0.5.0/24"], []), "API_ENDPOINT") is True


def test_5_5b_cidr_allows_url_form_at_nonstandard_port():
    assert _sg("https://10.0.5.10:8443/x", _m(["10.0.5.0/24"], []), "API_ENDPOINT") is True


def test_5_5b_bare_ip_entry_is_also_port_blind():
    assert _sg("10.0.5.10:9999", _m(["10.0.5.10"], [])) is True


def test_5_5b_cidr_denies_outside_the_network():
    assert _sg("10.0.6.10:443", _m(["10.0.5.0/24"], [])) is False


def test_5_5b_ipv6_cidr_allows_nonstandard_port():
    assert _sg("[2001:db8::1]:8443", _m(["2001:db8::/32"], [])) is True


def test_5_5b_ipv6_cidr_denies_outside_the_network():
    assert _sg("[2001:db9::1]:443", _m(["2001:db8::/32"], [])) is False


def test_5_5b_cross_shape_asymmetry_pinned_in_one_call():
    """The specification, not an inconsistency: an address-shaped entry
    is port-blind on the allow side; the hostname-shaped equivalent, in
    the very same manifest, is not. A later "cleanup" that unifies the
    two must break this test."""
    m = _m(["10.0.5.0/24", "*.acme.com"], [])
    assert _sg("10.0.5.10:8443", m) is True
    assert _sg("api.acme.com:8443", m) is False


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
        assert _sg(target, m) is False


# §5.6 — no authorization transfer via URL content (§1.1 rule 5 / FORK-S)


def test_5_6_f4_substring_glob_denies_via_query_string():
    assert _sg("https://evil.net/?next=acme.com/x", _m(["*acme.com*"], []), "API_ENDPOINT") is False


def test_5_6_no_transfer_via_redirect_query_parameter():
    assert _sg("https://evil.net/redirect?to=api.acme.com", _m(["*.acme.com"], []), "API_ENDPOINT") is False


def test_5_6_no_transfer_via_host_suffix_confusion():
    assert _sg("https://api.acme.com.attacker.net/x", _m(["*.acme.com"], []), "API_ENDPOINT") is False


def test_5_6_no_transfer_via_bare_host_suffix_confusion():
    assert _sg("x.acme.com.attacker.net", _m(["*.acme.com"], [])) is False


def test_5_6_no_transfer_via_fragment():
    assert _sg("https://evil.net/#api.acme.com", _m(["*.acme.com"], []), "API_ENDPOINT") is False


def test_5_6_no_transfer_via_userinfo_user_pass_form():
    assert _sg("https://user:pass@evil.net/x", _m(["*.acme.com"], []), "API_ENDPOINT") is False


def test_5_6_no_transfer_via_userinfo_host_confusion_form():
    """§8.6: the real host is evil.net; urlsplit().hostname agrees."""
    assert _sg("https://api.acme.com@evil.net/x", _m(["*.acme.com"], []), "API_ENDPOINT") is False


# §5.7 — bundle id vs hostname (FORK-T) — (lock) rows confirmed un-regressed


def test_5_7_lock_bundle_glob_allows_bundle_id():
    assert _sg("com.acme.mobile", _m(["com.acme.*"], [])) is True


def test_5_7_f5_bundle_glob_denies_multi_label_hostname_suffix():
    assert _sg("com.acme.evil.attacker.net", _m(["com.acme.*"], [])) is False


def test_5_7_lock_host_glob_does_not_catch_bundle_id():
    assert _sg("com.acme.mobile", _m(["*.acme.com"], [])) is False


# §5.8 — structural properties


def test_5_8_default_deny_on_empty_in_scope():
    assert _sg("api.acme.com", _m([], [])) is False
    assert _sg("acme.com", _m([], [])) is False
    assert _sg("api.acme.com:8443", _m([], [])) is False


@pytest.mark.parametrize(
    ("in_scope", "excluded", "target", "node_type"),
    [
        (["*"], ["10.0.0.5/32"], "https://10.0.0.5/admin", "API_ENDPOINT"),
        (["*"], ["10.0.0.5"], "https://10.0.0.5/admin", "API_ENDPOINT"),
        (["*"], ["2001:db8::1/128"], "[2001:db8::1]:443", "HOST"),
        (["*.acme.com"], ["secret.acme.com"], "secret.acme.com", "HOST"),
        (["*.acme.com"], ["secret.acme.com"], "https://secret.acme.com/x", "API_ENDPOINT"),
        (["10.0.5.0/24"], ["10.0.5.10"], "10.0.5.10:443", "HOST"),
        (["10.0.5.0/24"], ["10.0.5.10/32"], "https://10.0.5.10/x", "API_ENDPOINT"),
        (["api.acme.com:8443"], ["api.acme.com"], "https://api.acme.com:8443/x", "API_ENDPOINT"),
    ],
)
def test_5_8_exclusion_ordering_is_structural_not_default_deny(in_scope, excluded, target, node_type):
    """§7.9's lesson: a DENY that would also happen by default-deny
    proves nothing about exclusion precedence. Assert the same target is
    ALLOW once its exclusion is removed, so the denial above is
    provably coming from the exclusion itself."""
    assert _sg(target, _m(in_scope, excluded), node_type) is False
    assert _sg(target, _m(in_scope, []), node_type) is True


def test_5_8_pure_and_idempotent():
    m = _m(["*.acme.com"], ["secret.acme.com"])
    first = _sg("api.acme.com", m)
    second = _sg("api.acme.com", m)
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
    assert _sg(target, _m(["*.acme.com", "10.0.0.0/24"], ["evil.com"])) is False


def test_5_8_no_crash_on_junk_pattern():
    m = _m(["not/valid/cidr", "*"], [])
    assert _sg("anything", m) is True


# §8.4 — IPv6 forms not explicitly probed by the F1-F8 measurements, but
# flagged as open questions to verify, not leave quietly unresolved.


def test_8_4_ipv4_mapped_exclusion_is_not_a_bypass():
    m = _m(["*"], ["10.0.0.5"])
    assert _sg("::ffff:10.0.0.5", m) is False


def test_8_4_zone_index_does_not_bypass_exclusion():
    m = _m(["*"], ["fe80::1"])
    assert _sg("fe80::1%eth0", m) is False


def test_8_4_compressed_vs_expanded_ipv6_are_equivalent():
    m = _m(["*"], ["2001:db8::1"])
    assert _sg("2001:0db8:0000:0000:0000:0000:0000:0001", m) is False


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
    assert _sg("api.acme.com", manifest) is True  # subdomain, bare host
    assert _sg("acme.com", manifest) is False  # apex, not authorized
    assert _sg("secret.acme.com", manifest) is False  # excluded wins
    assert _sg("10.0.5.10:8443", manifest) is True  # CIDR, port-blind
    assert _sg("api.acme.com:8443", manifest) is False  # nonstandard port, no entry


# =============================================================================
# SPEC_BRIEF10.1 (amends PR #12, pre-merge) — the trailing-glob boundary rule.
# Everything above this line (SPEC_BRIEF10's own §5.1-§9.1) is unmodified.
# These tests are prefixed test_b101_ to avoid colliding with SPEC_BRIEF10's
# own §-numbered names above, which number a different document.
# =============================================================================

from kronos.scope_guard import _effective_shape, classify_target  # noqa: E402


# --- G1-G6 — measured against PR #12 @ fa6285f (RED before this brief's fix,
# GREEN after). See SPEC_BRIEF10.1.md §0/§5.1.


def test_b101_g1_trailing_glob_does_not_cross_a_dns_label():
    m = _m(["api.acme.com*"], [])
    assert _sg("api.acme.com.attacker.net", m) is False
    assert _sg("https://api.acme.com.attacker.net/x", m, "API_ENDPOINT") is False


def test_b101_g2_trailing_glob_does_not_expand_mid_label():
    m = _m(["api.acme.com*"], [])
    assert _sg("api.acme.com-evil.net", m) is False
    assert _sg("api.acme.comevil.net", m) is False  # mid-label, no separator at all


def test_b101_g3_localhost_trailing_glob_does_not_cross_a_dns_label():
    m = _m(["localhost*"], [])
    assert _sg("localhost.attacker.net", m) is False
    assert _sg("localhosted.attacker.net", m) is False  # mid-label


def test_b101_g4_ip_trailing_glob_does_not_cross_a_dns_label():
    m = _m(["127.0.0.1*"], [])
    assert _sg("127.0.0.1.attacker.net", m) is False


def test_b101_g5_url_pattern_trailing_host_glob_does_not_cross_a_dns_label():
    m = _m(["http://localhost*"], [])
    assert _sg("http://localhost.attacker.net/x", m, "API_ENDPOINT") is False


def test_b101_g6_bucket_glob_pattern_never_authorizes_a_hostname_shaped_target():
    m = _m(["kronos-cybergym-*"], [])
    assert _sg("kronos-cybergym-x.attacker.net", m) is False
    # and an ARN-shaped version of the same pattern/target pairing:
    assert _sg("kronos-cybergym-x.attacker.net", _m(["arn:aws:s3:::kronos-cybergym-*"], [])) is False


# --- §5.2 — trailing-glob port semantics (§1.2 Option A). Rows 3 and 6 are
# pinned together in one test per the brief: "the host* vs host distinction
# cannot be flattened later."


def test_b101_5_2_trailing_glob_locks():
    m = _m(["api.acme.com*"], [])
    assert _sg("api.acme.com", m) is True
    assert _sg("api.acme.com:443", m) is True
    assert _sg("https://api.acme.com:8443/x", m, "API_ENDPOINT") is True


def test_b101_5_2_trailing_glob_grants_all_ports_bare_host_does_not():
    assert _sg("api.acme.com:8443", _m(["api.acme.com*"], [])) is True  # row 3
    assert _sg("api.acme.com:22", _m(["api.acme.com*"], [])) is True  # documented consequence
    assert _sg("api.acme.com:8443", _m(["api.acme.com"], [])) is False  # row 6
    assert _sg("api.acme.com:8443", _m(["*.acme.com"], [])) is False  # row 7


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


# SPEC_BRIEF10.3: each row now also carries the node type that target
# would actually be upserted as in the real range (API_ENDPOINT for
# every http(s) chain-1 target, SERVICE for the bare LocalStack
# host:port form, HOST for the bare localhost/lookalike forms,
# CLOUD_RESOURCE for the bucket/ARN forms) -- the type the real range
# attaches, not an arbitrary choice per row.
@pytest.mark.parametrize(
    "target,node_type,expected",
    [
        ("http://localhost:8091/internal/v1/export", "API_ENDPOINT", True),  # chain 1 — DENY = X-score 0/3
        ("http://localhost:8091/health", "API_ENDPOINT", True),  # S1's abstention arm
        ("http://127.0.0.1:8091/internal/v1/export", "API_ENDPOINT", True),
        ("localhost:4566", "SERVICE", True),  # LocalStack
        ("127.0.0.1:4566", "SERVICE", True),
        ("localhost", "HOST", True),
        ("kronos-cybergym-general-secrets", "CLOUD_RESOURCE", True),  # bucket, mid-label expansion
        ("kronos-cybergym-admin-secrets", "CLOUD_RESOURCE", True),
        ("arn:aws:s3:::kronos-cybergym-admin-secrets", "CLOUD_RESOURCE", True),
        ("localhost.attacker.net", "HOST", False),
        ("127.0.0.1.attacker.net", "HOST", False),
        ("kronos-cybergym-x.attacker.net", "CLOUD_RESOURCE", False),
        ("http://localhost.attacker.net:8091/x", "API_ENDPOINT", False),
    ],
)
def test_b101_5_3_cybergym_real_manifest_matrix(target, node_type, expected):
    assert _sg(target, _m(_CYBERGYM_IN_SCOPE, []), node_type) is expected


def test_b101_5_3_cybergym_chain_1_target_explicitly():
    """Called out per the brief: this single row IS the live X-score."""
    assert (
        _sg("http://localhost:8091/internal/v1/export", _m(_CYBERGYM_IN_SCOPE, []), "API_ENDPOINT") is True
    )


# --- §5.4 — exclusion precedence across equivalent representations. Deny
# stays broad/port-blind/boundary-rule-free; the boundary rule is allow-only.
# Each row is checked twice: WITH the exclusion (must DENY) and with the
# exclusion removed (must ALLOW), proving the deny came from the exclusion.


@pytest.mark.parametrize(
    "in_scope,excluded,target,node_type",
    [
        (["api.acme.com*"], "api.acme.com", "api.acme.com:8443", "HOST"),
        (["api.acme.com*"], "api.acme.com", "https://api.acme.com/x", "API_ENDPOINT"),
        (["localhost*"], "localhost", "localhost:4566", "SERVICE"),
        (
            ["kronos-cybergym-*"],
            "kronos-cybergym-admin-secrets",
            "kronos-cybergym-admin-secrets",
            "CLOUD_RESOURCE",
        ),
        (
            ["arn:aws:s3:::kronos-cybergym-*"],
            "arn:aws:s3:::kronos-cybergym-admin-secrets",
            "arn:aws:s3:::kronos-cybergym-admin-secrets",
            "CLOUD_RESOURCE",
        ),
    ],
)
def test_b101_5_4_exclusion_precedence_attributed_to_exclusion(in_scope, excluded, target, node_type):
    assert _sg(target, _m(in_scope, [excluded]), node_type) is False
    assert _sg(target, _m(in_scope, []), node_type) is True  # same target, exclusion removed -> allow


def test_b101_5_4_f1_un_regressed():
    assert _sg("https://10.0.0.5/admin", _m(["*"], ["10.0.0.5/32"]), "API_ENDPOINT") is False


def test_b101_5_4_f3_un_regressed():
    assert _sg("[2001:db8::1]:443", _m(["*"], ["2001:db8::1/128"])) is False


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
#                      same as MOBILE_APP, "host" -- but since SPEC_BRIEF10.4
#                      §1.1, that string reaches ScopeGuard as a scope_key
#                      (target_kind="scope_key"), gated on its own shape via
#                      `_scope_key_shape`, never through this id-shape table
#                      at all. SECRET's row here is now `frozenset()` (§1.2 /
#                      FORK-Y): its own id (sha256-derived) matches no shape
#                      family, and nothing in production ever reaches it via
#                      the id path.
#   API_ENDPOINT     — id=found.url, a full URL (ingest/mobile/parser.py:276)
#                      -> "url".
#   WEB_ENDPOINT     — SPEC_BRIEF10.4 §1.2/FORK-W: no production ingester at
#                      all, and its only documented key
#                      (`canonical_key_for_web_endpoint`) is a merge key, not
#                      a node id, and classifies as "unknown" anyway -- so
#                      this row is `frozenset()`, denying unconditionally on
#                      the id path (a WEB_ENDPOINT only reaches "in scope" by
#                      carrying an authorized scope_key, §1.1).
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
    "target,node_type,expected_shape,in_scope_pattern,expected_verdict",
    [
        ("api.acme.com", "HOST", "host", "*.acme.com", True),
        ("10.0.0.5", "HOST", "ip", "10.0.0.0/24", True),
        # also the shape SECRET's scope_key carries in production, but
        # SPEC_BRIEF10.4 §1.1 means that reaches ScopeGuard via
        # target_kind="scope_key", never through this id-shape table --
        # see test_b104_5_2_* below for that path exercised directly.
        ("com.kronos.demo", "MOBILE_APP", "host", "com.kronos.*", True),
        ("https://api.acme.com/v1/x", "API_ENDPOINT", "url", "api.acme.com*", True),
        ("api.acme.com:8443", "SERVICE", "host_port", "api.acme.com*", True),
        ("10.0.5.10:443", "SERVICE", "ip_port", "10.0.5.0/24", True),
        # PARAMETER, SPEC_BRIEF10.3 §1.4: empty permitted-shape family,
        # never allow-authorized by any pattern regardless of shape.
        ("param:api.acme.com:id:query", "PARAMETER", "host", "api.acme.com*", False),
        # FINDING, SPEC_BRIEF10.3 FORK-W(2): no production ingester, no
        # established id convention -> empty family, denies even
        # though a bucket-style pattern would otherwise freely match
        # this dot-free string.
        ("finding:9f1c2b3a4d5e6f70", "FINDING", "host", "finding:*", False),
        ("kronos-cybergym-admin-secrets", "CLOUD_RESOURCE", "bucket_name", "kronos-cybergym-*", True),
        (
            "arn:aws:s3:::kronos-cybergym-admin-secrets",
            "CLOUD_RESOURCE",
            "arn",
            "arn:aws:s3:::kronos-cybergym-*",
            True,
        ),
        # H2 lock: the same dot-free bucket-style pattern must NEVER
        # authorize a HOST-typed target carrying that exact string --
        # classify_target alone can't tell them apart; node_type does.
        ("kronos-cybergym-admin-secrets", "HOST", "host", "kronos-cybergym-*", False),
    ],
)
def test_b101_5_6_caller_shape_enumeration(target, node_type, expected_shape, in_scope_pattern, expected_verdict):
    assert _effective_shape(target, node_type) == expected_shape
    assert _sg(target, _m([in_scope_pattern], []), node_type) is expected_verdict


# --- FORK-U — a pattern with wildcards at both ends. DEFAULT: (1), PR #12's
# current verdict unchanged — such a pattern is NOT treated as a host
# pattern for trailing-glob purposes, so it keeps denying a nonstandard port
# rather than being harmonized with §1.2's "any port" rule.


def test_b101_fork_u_both_ends_wildcard_is_not_a_host_pattern():
    assert _sg("api.acme.com:8443", _m(["*.acme.com*"], [])) is False


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
    assert _sg("http://localhost:8091@evil.net/x", m, "API_ENDPOINT") is False


def test_b102_h1b_lookalike_suffix_on_the_port_is_not_a_port():
    m = _m(["http://localhost:8091*"], [])
    assert _sg("http://localhost:8091.attacker.net/x", m, "API_ENDPOINT") is False


def test_b102_h1c_different_numeric_port_sharing_a_prefix_is_not_the_same_port():
    m = _m(["http://localhost:8091*"], [])
    assert _sg("http://localhost:80915/x", m, "API_ENDPOINT") is False


def test_b102_h1d_trailing_garbage_on_the_port_is_not_a_port():
    m = _m(["http://localhost:8091*"], [])
    assert _sg("http://localhost:8091evil.net/x", m, "API_ENDPOINT") is False


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
    assert _sg(target, _m(["http://localhost:8091*"], []), "API_ENDPOINT") is expected


@pytest.mark.parametrize(
    "target",
    [
        "http://localhost:8091/x",
        "http://localhost:9091/x",  # exclusions are port-blind (rule 6)
        "http://localhost/x",  # exclusions are representation-blind
    ],
)
def test_b102_section2_exclusion_table(target):
    assert _sg(target, _m(["*"], ["http://localhost:8091*"]), "API_ENDPOINT") is False


# --- The nine pre-existing tests using http://localhost:8091* (listed in the
# brief: tests/test_negative_controls.py (2), tests/test_validate_candidates.py
# (1), tests/test_validate_runner.py (6)) are NOT duplicated or modified here
# — this brief's acceptance criteria require them to pass completely
# unmodified, verified by running the full suite (see report).


# --- G1-G6 re-run (SPEC_BRIEF10.1) — must still all DENY.


def test_b102_g1_still_denies():
    m = _m(["api.acme.com*"], [])
    assert _sg("api.acme.com.attacker.net", m) is False
    assert _sg("https://api.acme.com.attacker.net/x", m, "API_ENDPOINT") is False


def test_b102_g2_still_denies():
    m = _m(["api.acme.com*"], [])
    assert _sg("api.acme.com-evil.net", m) is False
    assert _sg("api.acme.comevil.net", m) is False


def test_b102_g3_still_denies():
    m = _m(["localhost*"], [])
    assert _sg("localhost.attacker.net", m) is False
    assert _sg("localhosted.attacker.net", m) is False


def test_b102_g4_still_denies():
    assert _sg("127.0.0.1.attacker.net", _m(["127.0.0.1*"], [])) is False


def test_b102_g5_still_denies():
    assert _sg("http://localhost.attacker.net/x", _m(["http://localhost*"], []), "API_ENDPOINT") is False


def test_b102_g6_still_denies():
    m = _m(["kronos-cybergym-*"], [])
    assert _sg("kronos-cybergym-x.attacker.net", m) is False
    assert _sg("kronos-cybergym-x.attacker.net", _m(["arn:aws:s3:::kronos-cybergym-*"], [])) is False


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
    # node_type="API_ENDPOINT" (not the default "HOST"): these targets
    # are URL-shaped, and the point of this test is to exercise the
    # pattern-parsing path itself -- under "HOST" the type gate would
    # deny every row before any pattern is even consulted, making the
    # assertions vacuously true rather than a real robustness check.
    m = _m([pattern], [])
    assert _sg("http://localhost:8091/x", m, "API_ENDPOINT") in (True, False)
    assert _sg("http://evil.net:8091/x", m, "API_ENDPOINT") is False
    assert _sg("http://localhost:9091/x", m, "API_ENDPOINT") in (True, False)


# =============================================================================
# SPEC_BRIEF10.3 (FORK-2's final piece) — node-type-aware dispatch,
# cross-shape exclusions, generated matrix. Prefixed test_b103_.
# =============================================================================

from kronos.scope_guard import NODE_TYPE_SHAPES, ScopeGuard, _matches  # noqa: E402


# --- H2 (RED first against the pre-this-brief `is_in_scope(target)`,
# one-argument signature -- see SPEC_BRIEF10.3.md §5.1).


@pytest.mark.parametrize(
    "node_type,in_scope_pattern,target,expected",
    [
        ("HOST", "localhost*", "localhostevil", False),
        ("HOST", "localhost*", "localhost-evil", False),
        ("HOST", "localhost*", "localhost", True),
        ("HOST", "localhost*", "localhost:8091", True),
        ("HOST", "jenkins*", "jenkins-prod", False),
        ("HOST", "jenkins*", "jenkins", True),
        ("CLOUD_RESOURCE", "kronos-cybergym-*", "kronos-cybergym-general-secrets", True),  # lock
        ("CLOUD_RESOURCE", "kronos-cybergym-*", "kronos-cybergym-x.attacker.net", False),  # G6 lock
        ("HOST", "kronos-cybergym-*", "kronos-cybergym-general-secrets", False),  # bucket glob, host type
    ],
)
def test_b103_h2(node_type, in_scope_pattern, target, expected):
    assert _sg(target, _m([in_scope_pattern], []), node_type) is expected


# --- H3 (RED first) — excluded = ['http://localhost:8091*'], in_scope = ['*']


@pytest.mark.parametrize(
    "node_type,target",
    [
        ("WEB_ENDPOINT", "http://localhost:8091/x"),
        ("WEB_ENDPOINT", "http://localhost:9091/x"),  # lock, #10.2
        ("SERVICE", "localhost:8091"),
        ("HOST", "localhost"),
        ("SERVICE", "localhost:4566"),  # port-blind
    ],
)
def test_b103_h3(node_type, target):
    assert _sg(target, _m(["*"], ["http://localhost:8091*"]), node_type) is False


def test_b103_h3_exclusion_ignores_an_unrecognised_node_type():
    assert _sg("localhost", _m(["*"], ["http://localhost:8091*"]), None) is False
    assert _sg("localhost", _m(["*"], ["http://localhost:8091*"]), "") is False
    assert _sg("localhost", _m(["*"], ["http://localhost:8091*"]), "NOT_A_TYPE") is False


def test_b103_h3_reverse_direction():
    """excluded = ['localhost'] must also deny the URL form of the same
    host for a WEB_ENDPOINT target -- this direction already worked
    pre-this-brief (`_matches_hostname_pattern` already accepted "url"
    shape), carried forward as a regression lock."""
    assert _sg("http://localhost:8091/x", _m(["*"], ["localhost"]), "WEB_ENDPOINT") is False


# --- §5.3 fail-closed: an unrecognised, empty, or None node_type denies
# every §5.1 ALLOW row, and exclusions still deny regardless.


@pytest.mark.parametrize("bad_node_type", [None, "", "NOT_A_TYPE", "WEB_SERVICE"])
@pytest.mark.parametrize(
    "in_scope_pattern,target",
    [
        ("localhost*", "localhost"),
        ("localhost*", "localhost:8091"),
        ("jenkins*", "jenkins"),
        ("kronos-cybergym-*", "kronos-cybergym-general-secrets"),
    ],
)
def test_b103_5_3_fail_closed_denies_every_allow_row(bad_node_type, in_scope_pattern, target):
    assert _sg(target, _m([in_scope_pattern], []), bad_node_type) is False


@pytest.mark.parametrize("bad_node_type", [None, "", "NOT_A_TYPE", "WEB_SERVICE"])
def test_b103_5_3_fail_closed_deny_comes_from_type_gate_not_a_failed_allow(bad_node_type):
    """Same manifest that DOES authorize this target under the correct
    node_type (proving the deny below is the type gate, not a pattern
    that would have failed anyway)."""
    m = _m(["localhost*"], [])
    assert _sg("localhost", m, "HOST") is True
    assert _sg("localhost", m, bad_node_type) is False


@pytest.mark.parametrize("bad_node_type", [None, "", "NOT_A_TYPE"])
def test_b103_5_3_fail_closed_still_denies_excluded_targets(bad_node_type):
    """Exclusions ignore node_type entirely (§1.3) -- a garbage type
    must not somehow let an excluded target slip through either."""
    assert _sg("localhost", _m(["*"], ["localhost"]), bad_node_type) is False


def test_b103_module_level_scope_guard_requires_node_type_kwarg():
    """FORK-V DEFAULT (1): no positional/default fallback exists at all."""
    with pytest.raises(TypeError):
        scope_guard("localhost", _m(["localhost*"], []))  # type: ignore[call-arg]


def test_b103_is_in_scope_requires_node_type_kwarg():
    with pytest.raises(TypeError):
        ScopeGuard(_m(["localhost*"], [])).is_in_scope("localhost")  # type: ignore[call-arg]


def test_b103_parameter_never_glob_authorized():
    """§1.4: PARAMETER's permitted-shape family is empty -- no pattern,
    of any shape, ever allow-authorizes it."""
    assert NODE_TYPE_SHAPES["PARAMETER"] == frozenset()
    for pattern in ["*", "param:*", "api.acme.com*", "arn:aws:s3:::*"]:
        assert _sg("param:api.acme.com:id:query", _m([pattern], []), "PARAMETER") is False


def test_b103_identity_technology_finding_have_no_evidence_based_family():
    """FORK-W(2): no production ingester ever creates these three node
    types (grep-verified against this branch head), so no family is
    assigned by analogy -- each denies unconditionally."""
    for node_type in ("IDENTITY", "TECHNOLOGY", "FINDING"):
        assert NODE_TYPE_SHAPES[node_type] == frozenset()
        assert _sg("anything", _m(["*"], []), node_type) is False


# --- §5.4 — the generated cross-product (replaces hand-picked matrices).
# Declared as data (not computed from scope_guard.py): 13 pattern shapes
# x 14 target shapes, run once for the allow side under node_type="HOST"
# and once for the exclusion side (type-independent, via `_matches`
# directly -- is_in_scope's own type gate would otherwise confound an
# "excluded" True with a "denied by type mismatch" True for the
# url/arn/bucket_name target columns, which a HOST-typed allow check
# can never distinguish). CLOUD_RESOURCE's bucket/ARN pattern families
# are exercised by the dedicated H2/G6 lock tests above rather than a
# second full generated grid.

_P1_BARE_HOST = "api.acme.com"
_P2_LEADING_GLOB = "*.acme.com"
_P3_TRAILING_GLOB = "api.acme.com*"
_P4_BOTH_ENDS_GLOB = "*.acme.com*"
_P5_BARE_IP = "10.0.0.5"
_P6_CIDR = "10.0.0.0/24"
_P7_HOST_PORT = "api.acme.com:8443"
_P8_URL_NO_PORT = "https://api.acme.com/v1/*"
_P9_URL_WITH_PORT = "https://api.acme.com:8443/v1/*"
_P10_URL_TRAILING_GLOB = "https://api.acme.com*"
_P11_BUCKET_GLOB = "kronos-cybergym-*"
_P12_ARN_GLOB = "arn:aws:s3:::kronos-cybergym-*"
_P13_BUNDLE_GLOB = "com.acme.*"

_PATTERNS = [
    _P1_BARE_HOST, _P2_LEADING_GLOB, _P3_TRAILING_GLOB, _P4_BOTH_ENDS_GLOB,
    _P5_BARE_IP, _P6_CIDR, _P7_HOST_PORT, _P8_URL_NO_PORT, _P9_URL_WITH_PORT,
    _P10_URL_TRAILING_GLOB, _P11_BUCKET_GLOB, _P12_ARN_GLOB, _P13_BUNDLE_GLOB,
]

_T1_HOST = "api.acme.com"
_T2_HOST_PORT = "api.acme.com:8443"
_T3_IP = "10.0.0.5"
_T4_IP_PORT = "10.0.0.5:8443"
_T5_BRACKETED_IPV6_PORT = "[2001:db8::1]:443"
_T6_URL_STD_PORT = "https://api.acme.com/x"
_T7_URL_NONSTD_PORT = "https://api.acme.com:8443/x"
_T8_URL_USERINFO = "https://user@api.acme.com/x"
_T9_DOT_FREE_HOST = "jenkins"
_T10_LOOKALIKE = "api.acme.com.attacker.net"
_T11_MID_LABEL = "api.acme.com-evil.net"
_T12_BUCKET_NAME = "kronos-cybergym-admin-secrets"
_T13_ARN = "arn:aws:s3:::kronos-cybergym-admin-secrets"
_T14_BUNDLE_ID = "com.acme.mobile"

_TARGETS = [
    _T1_HOST, _T2_HOST_PORT, _T3_IP, _T4_IP_PORT, _T5_BRACKETED_IPV6_PORT,
    _T6_URL_STD_PORT, _T7_URL_NONSTD_PORT, _T8_URL_USERINFO, _T9_DOT_FREE_HOST,
    _T10_LOOKALIKE, _T11_MID_LABEL, _T12_BUCKET_NAME, _T13_ARN, _T14_BUNDLE_ID,
]

_F, _T = False, True

# Declared expectations, allow side, node_type="HOST". Row order matches
# _PATTERNS; column order matches _TARGETS.
_ALLOW_HOST_EXPECTATIONS: dict[str, dict[str, bool]] = {
    _P1_BARE_HOST: dict(zip(_TARGETS, [_T, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F])),
    _P2_LEADING_GLOB: dict(zip(_TARGETS, [_T, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F])),
    _P3_TRAILING_GLOB: dict(zip(_TARGETS, [_T, _T, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F])),
    _P4_BOTH_ENDS_GLOB: dict(zip(_TARGETS, [_F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F])),
    _P5_BARE_IP: dict(zip(_TARGETS, [_F, _F, _T, _T, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F])),
    _P6_CIDR: dict(zip(_TARGETS, [_F, _F, _T, _T, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F])),
    _P7_HOST_PORT: dict(zip(_TARGETS, [_F, _T, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F])),
    _P8_URL_NO_PORT: dict(zip(_TARGETS, [_F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F])),
    _P9_URL_WITH_PORT: dict(zip(_TARGETS, [_F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F])),
    _P10_URL_TRAILING_GLOB: dict(zip(_TARGETS, [_F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F])),
    _P11_BUCKET_GLOB: dict(zip(_TARGETS, [_F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F])),
    _P12_ARN_GLOB: dict(zip(_TARGETS, [_F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F])),
    _P13_BUNDLE_GLOB: dict(zip(_TARGETS, [_F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _T])),
}

# Declared expectations, exclusion side (type-independent): does this
# pattern, used as an exclusion, deny this target? Computed directly
# via `_matches(..., is_exclusion=True)` -- `is_in_scope`'s type gate
# never runs on the exclusion path at all (§1.3), so this is the true,
# node-type-independent exclusion semantics.
_EXCLUSION_EXPECTATIONS: dict[str, dict[str, bool]] = {
    _P1_BARE_HOST: dict(zip(_TARGETS, [_T, _T, _F, _F, _F, _T, _T, _T, _F, _F, _F, _F, _F, _F])),
    _P2_LEADING_GLOB: dict(zip(_TARGETS, [_T, _T, _F, _F, _F, _T, _T, _T, _F, _F, _F, _F, _F, _F])),
    _P3_TRAILING_GLOB: dict(zip(_TARGETS, [_T, _T, _F, _F, _F, _T, _T, _T, _F, _T, _T, _F, _F, _F])),
    # SPEC_BRIEF10.5 §1.3 (PD-5): deny-broad. _EXCL_HOSTISH positions
    # (T1, T2, T6, T7, T8, T10, T11) now deny; the rest are unchanged.
    _P4_BOTH_ENDS_GLOB: dict(zip(_TARGETS, [_T, _T, _F, _F, _F, _T, _T, _T, _F, _T, _T, _F, _F, _F])),
    _P5_BARE_IP: dict(zip(_TARGETS, [_F, _F, _T, _T, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F])),
    _P6_CIDR: dict(zip(_TARGETS, [_F, _F, _T, _T, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F])),
    _P7_HOST_PORT: dict(zip(_TARGETS, [_T, _T, _F, _F, _F, _T, _T, _T, _F, _F, _F, _F, _F, _F])),
    # SPEC_BRIEF10.4 §1.3 (Finding A): these two rows were [_F]*14
    # under 10.3 -- a path-bearing URL *exclusion* pattern fell through
    # to the literal, path-aware `_matches_url_pattern`, so it denied
    # almost nothing. §1.3 requires an exclusion to discard the
    # pattern's path (and, per rule 6, its port and scheme too) and
    # compare host identity only -- exactly the same host-only
    # comparison _P1/_P2/_P7 above already use, so these two rows must
    # now match them on every host-ish target
    # (_T1/_T2/_T6/_T7/_T8), regardless of the pattern's own port
    # (_P9 carries :8443, discarded same as _P1 has none).
    _P8_URL_NO_PORT: dict(zip(_TARGETS, [_T, _T, _F, _F, _F, _T, _T, _T, _F, _F, _F, _F, _F, _F])),
    _P9_URL_WITH_PORT: dict(zip(_TARGETS, [_T, _T, _F, _F, _F, _T, _T, _T, _F, _F, _F, _F, _F, _F])),
    _P10_URL_TRAILING_GLOB: dict(zip(_TARGETS, [_T, _T, _F, _F, _F, _T, _T, _T, _F, _F, _F, _F, _F, _F])),
    _P11_BUCKET_GLOB: dict(zip(_TARGETS, [_F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _T, _F, _F])),
    _P12_ARN_GLOB: dict(zip(_TARGETS, [_F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _T, _F])),
    _P13_BUNDLE_GLOB: dict(zip(_TARGETS, [_F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _F, _T])),
}


def test_b103_5_4_cell_count_and_completeness():
    """The generated-matrix property itself: every one of the 13 x 14
    cells is declared in both grids -- a KeyError (undeclared cell)
    fails this test, not a silent default."""
    assert len(_PATTERNS) == 13
    assert len(_TARGETS) == 14
    cells = 0
    for pattern in _PATTERNS:
        for target in _TARGETS:
            _ALLOW_HOST_EXPECTATIONS[pattern][target]  # KeyError if undeclared
            _EXCLUSION_EXPECTATIONS[pattern][target]  # KeyError if undeclared
            cells += 2
    assert cells == 13 * 14 * 2 == 364


@pytest.mark.parametrize("pattern", _PATTERNS)
@pytest.mark.parametrize("target", _TARGETS)
def test_b103_5_4_generated_allow_matrix_host(pattern, target):
    expected = _ALLOW_HOST_EXPECTATIONS[pattern][target]
    assert _sg(target, _m([pattern], []), "HOST") is expected


@pytest.mark.parametrize("pattern", _PATTERNS)
@pytest.mark.parametrize("target", _TARGETS)
def test_b103_5_4_generated_exclusion_matrix(pattern, target):
    expected = _EXCLUSION_EXPECTATIONS[pattern][target]
    assert _matches(pattern, target, is_exclusion=True) is expected


# --- §5.5 regression: every Brief #10/#10.1/#10.2 case is re-run above
# with node types threaded through (test_b101_*, test_b102_*); G1-G6
# confirmed still DENY via test_b102_g1_still_denies..test_b102_g6_still_denies.


# =============================================================================
# SPEC_BRIEF10.4 (FORK-2's closing piece) -- scope_key dispatch (§1.1),
# evidence-only shape families (§1.2), path-blind exclusions (§1.3).
# Prefixed test_b104_. Every call below goes through the public API
# (`scope_guard`, matching §5.4 point 4) and passes `target_kind`
# explicitly -- there is no default at this layer, unlike `_sg`'s
# file-local convenience default above.
# =============================================================================


# --- §5.1 Finding A (RED first) -- a path-bearing URL exclusion pattern
# must deny shape-blind, port-blind, scheme-blind AND path-blind, exactly
# as broadly as the path-free form already does (§1.3, §0's measured
# table). Two independent hosts, so the rule is proven not fitted to one.


@pytest.mark.parametrize(
    "target",
    [
        "http://localhost:8091/internal/x",  # already passed under 10.3 -- keep green
        "localhost:8091",  # shape-blind
        "http://localhost:8091/other",  # path-blind
        "localhost",  # port-blind
        "http://localhost:8091/",  # path-blind
    ],
)
def test_b104_5_1_finding_a_path_bearing_exclusion_denies_localhost(target):
    m = _m(["*"], ["http://localhost:8091/internal/*"])
    assert scope_guard(target, m, node_type="SERVICE", target_kind="id") is False


@pytest.mark.parametrize(
    "target",
    [
        "https://api.acme.example.com/v1/x",
        "api.acme.example.com:443",
        "https://api.acme.example.com/other",
        "api.acme.example.com",
        "https://api.acme.example.com/",
    ],
)
def test_b104_5_1_finding_a_path_bearing_exclusion_denies_second_host(target):
    """Same rule, a second, non-localhost host -- proves §1.3's fix is
    the pattern's structural host identity, not something fitted to
    one hostname."""
    m = _m(["*"], ["https://api.acme.example.com/v1/*"])
    assert scope_guard(target, m, node_type="API_ENDPOINT", target_kind="id") is False


@pytest.mark.parametrize(
    "excluded_pattern,allowed_target,denied_target",
    [
        (
            "http://localhost:8091/internal/*",
            "http://localhost:8091/internal/x",
            "http://localhost:8091/other",
        ),
        (
            "https://api.acme.example.com/v1/*",
            "https://api.acme.example.com/v1/x",
            "https://api.acme.example.com/other",
        ),
    ],
)
def test_b104_5_1_allow_side_control_keeps_narrow_path_aware_behaviour(
    excluded_pattern, allowed_target, denied_target
):
    """§1.3's fix is deny-side only (guardrail §9: the allow side is not
    widened anywhere). The identical pattern text, used as an ALLOW
    entry, keeps its current narrow, path-aware, literal `fnmatch`
    behaviour: only the exact path it spells out is authorized, and a
    different path on the same host still denies. This is the control
    that proves §1.3's exclusion fix did not leak into the allow path."""
    m = _m([excluded_pattern], [])
    assert scope_guard(allowed_target, m, node_type="API_ENDPOINT", target_kind="id") is True
    assert scope_guard(denied_target, m, node_type="API_ENDPOINT", target_kind="id") is False


# --- §5.2 -- scope_key is gated on its own shape, independent of
# node_type (§1.1, RED first against the pre-this-brief single-kwarg
# `is_in_scope(target, node_type=...)`, which has no way to receive a
# scope_key/id distinction at all).


def test_b104_5_2_1_scope_key_shape_authorizes_regardless_of_id_shape_family():
    """A CLOUD_RESOURCE's scope_key is a hostname; the CLOUD_RESOURCE
    id-shape family ({"bucket_name", "arn"}) does not even contain
    "host" -- yet §1.1 says the family filter never applies to a
    scope_key at all, so this must still be in scope purely off the
    scope_key's own shape. Denies today (pre-fix): the single-kwarg
    `is_in_scope` has no way to know this string is a scope_key, so it
    was always run through the id-shape table, which "host" fails."""
    m = _m(["*.acme.example.com"], [])
    assert scope_guard("api.acme.example.com", m, node_type="CLOUD_RESOURCE", target_kind="scope_key") is True


def test_b104_5_2_2_same_node_no_scope_key_falls_through_to_id_shape_family():
    """The same CLOUD_RESOURCE, with no scope_key: `graph.py`'s
    `scope_key or id` (§1.5, unchanged) falls through to the id,
    `cr:acme-bucket`, dot-free and colon-containing -> "bucket_name"
    (CLOUD_RESOURCE is the one type that keeps free glob expansion,
    §0.2) -- permitted by its family, and matched freely."""
    m = _m(["cr:acme-*"], [])
    assert scope_guard("cr:acme-bucket", m, node_type="CLOUD_RESOURCE", target_kind="id") is True


def test_b104_5_2_3_scope_key_not_authorized_by_any_pattern_denies():
    """A scope_key is not a bypass -- its own shape must still match
    some in_scope pattern, exactly like an id does."""
    m = _m(["*.acme.example.com"], [])
    assert scope_guard("unrelated.example.net", m, node_type="CLOUD_RESOURCE", target_kind="scope_key") is False


def test_b104_5_2_4_excluded_first_still_applies_to_a_scope_key():
    """§2.5: excluded-first, default-DENY is absolute -- an excluded
    scope_key denies even though the same string also matches a
    maximally permissive in_scope entry."""
    m = _m(["*"], ["evil.example.com"])
    assert scope_guard("evil.example.com", m, node_type="CLOUD_RESOURCE", target_kind="scope_key") is False


@pytest.mark.parametrize("bad_node_type", [None, "", "NOT_A_TYPE"])
def test_b104_5_2_5_fail_closed_on_node_type_unaffected_by_a_valid_scope_key(bad_node_type):
    """§2.4/§8.3: fail-closed is unaffected by §1.1 -- an unrecognised,
    empty, or None `node_type` still denies before any pattern is
    consulted, scope_key or not. Same manifest/scope_key that DOES
    authorize under a real node_type (proving this is the type gate,
    not a pattern that would have failed anyway)."""
    m = _m(["*.acme.example.com"], [])
    assert scope_guard("api.acme.example.com", m, node_type="CLOUD_RESOURCE", target_kind="scope_key") is True
    assert scope_guard("api.acme.example.com", m, node_type=bad_node_type, target_kind="scope_key") is False


def test_b104_5_2_6_arn_form_scope_key_cybergym_uses_stays_in_scope():
    """CyberGym's real validation run sets CLOUD_RESOURCE scope_keys in
    ARN form (§0.4) -- an ARN is unambiguous (`classify_target` never
    confuses it with a dot-free bucket name), so it passes through
    `_scope_key_shape` unaffected and keeps its free glob expansion,
    exactly as the id path already does for the same string."""
    m = _m(["arn:aws:s3:::kronos-cybergym-*"], [])
    assert (
        scope_guard(
            "arn:aws:s3:::kronos-cybergym-general-secrets",
            m,
            node_type="CLOUD_RESOURCE",
            target_kind="scope_key",
        )
        is True
    )


def test_b104_5_2_7_localhost_scope_key_governed_by_host_boundary_not_bucket_glob():
    """§1.1's own worked example, directly: a CLOUD_RESOURCE whose
    scope_key is the dot-free `localhost` becomes governed by the host
    boundary rule -- narrower than the bucket-glob treatment the exact
    same dot-free string gets on the id path, never looser (guardrail
    §9). `localhost*` still covers bare `localhost` (boundary rule
    §1.1/trailing-`*` rule, unaffected), but must NOT mid-label-expand
    into `localhost-evil` the way CLOUD_RESOURCE's free bucket
    expansion would for an id carrying the identical text."""
    m = _m(["localhost*"], [])
    assert scope_guard("localhost", m, node_type="CLOUD_RESOURCE", target_kind="scope_key") is True
    assert scope_guard("localhost-evil", m, node_type="CLOUD_RESOURCE", target_kind="id") is True
    assert scope_guard("localhost-evil", m, node_type="CLOUD_RESOURCE", target_kind="scope_key") is False


# --- §5.3 -- NODE_TYPE_SHAPES is evidence-only (§1.2); WEB_ENDPOINT and
# SECRET are re-derived, and no `schema.py` node type is silently absent.


def test_b104_5_3_1_web_endpoint_id_denies_unconditionally():
    """§1.2/FORK-W: no production WEB_ENDPOINT ingester, and its only
    documented key is a merge key, not an id, classifying as
    "unknown" -- `frozenset()`, denying every shape, even a URL, even
    its own `web:1` canonical-key form, even under a maximally
    permissive manifest."""
    m = _m(["*"], [])
    assert NODE_TYPE_SHAPES["WEB_ENDPOINT"] == frozenset()
    for target in ("https://api.acme.example.com/x", "web:1", "web:GET:https://api.acme.example.com/x"):
        assert scope_guard(target, m, node_type="WEB_ENDPOINT", target_kind="id") is False


def test_b104_5_3_2_web_endpoint_reaches_in_scope_only_via_an_authorized_scope_key():
    """§1.1 is what makes the §1.4/§5.6(b) WEB_ENDPOINT reconcile
    correction work at all: a WEB_ENDPOINT with no id convention still
    reaches "in scope" when upserted with a real scope_key, because the
    scope_key path never consults WEB_ENDPOINT's (empty) id-shape
    family."""
    m = _m(["*.acme.example.com"], [])
    assert scope_guard("api.acme.example.com", m, node_type="WEB_ENDPOINT", target_kind="scope_key") is True


@pytest.mark.parametrize("node_type", ["IDENTITY", "TECHNOLOGY", "FINDING", "PARAMETER"])
def test_b104_5_3_3_identity_technology_finding_parameter_continue_to_deny_unconditionally(node_type):
    """Unchanged by this brief -- still no production evidence, still
    `frozenset()`, still denied on the id path regardless of pattern."""
    assert NODE_TYPE_SHAPES[node_type] == frozenset()
    assert scope_guard("anything", _m(["*"], []), node_type=node_type, target_kind="id") is False


def test_b104_5_3_4_secret_re_derived_denies_on_id_path_but_works_via_scope_key():
    """SECRET, re-derived (§1.1/§1.2/FORK-Y): its own id is sha256-
    derived and matches no shape family this module has, so its row is
    `frozenset()` -- denied on the id path even under a maximally
    permissive manifest. But every real SECRET call site sets
    `scope_key=bundle_id` unconditionally (§0.2 D1), so the scope_key
    path -- gated on the bundle id's own "host" shape, independent of
    this empty row -- is exactly how a real SECRET reaches "in scope"
    in production; this denies nothing real."""
    assert NODE_TYPE_SHAPES["SECRET"] == frozenset()
    sha256_id = "a" * 64
    assert scope_guard(sha256_id, _m(["*"], []), node_type="SECRET", target_kind="id") is False
    m = _m(["com.kronos.*"], [])
    assert scope_guard("com.kronos.demo", m, node_type="SECRET", target_kind="scope_key") is True


def test_b104_5_3_5_every_schema_node_type_is_in_table_or_demonstrably_bypassed():
    """No `schema.py` node type may be silently absent from this
    accounting: every one of `ALL_NODE_TABLES` is either a key in
    `NODE_TYPE_SHAPES` (even with an empty family) or one of the two
    types `graph.py` bypasses `is_in_scope` for entirely
    (`_ALWAYS_IN_SCOPE_TYPES`/`_NO_IN_SCOPE_COLUMN_TYPES`)."""
    from kronos import graph
    from kronos.schema import ALL_NODE_TABLES

    bypassed = graph._ALWAYS_IN_SCOPE_TYPES | graph._NO_IN_SCOPE_COLUMN_TYPES
    for node_type in ALL_NODE_TABLES:
        assert node_type in NODE_TYPE_SHAPES or node_type in bypassed, node_type


# --- §5.4's third axis -- id/scope_key (§1.1), run per node type (not
# just one), through the public API only. Declared as data: one
# representative (pattern, target) pair per node type reachable via a
# scope_key in real production evidence (the NODE_TYPE_SHAPES comment
# block above cites each), run once with target_kind="id" and once
# with target_kind="scope_key". Every cell's citation is the row
# comment next to it; no cell here is computed from running the code --
# each was derived by hand from `_effective_shape`/`_scope_key_shape`'s
# documented rules, then verified.
_B104_ID_SCOPE_KEY_AXIS = [
    # (node_type, pattern, target, expected_id, expected_scope_key, why)
    ("HOST", "*.acme.example.com", "api.acme.example.com", True, True,
     "unambiguous host shape -- id and scope_key paths agree (§1.1: no node_type signal needed either way)"),
    ("SERVICE", "api.acme.example.com*", "api.acme.example.com:8443", True, True,
     "host_port shape, unambiguous -- both paths agree"),
    ("API_ENDPOINT", "api.acme.example.com*", "https://api.acme.example.com/x", True, True,
     "url shape, unambiguous -- both paths agree (API_ENDPOINT's {'url'} family is directly evidenced, §0.2)"),
    ("WEB_ENDPOINT", "api.acme.example.com*", "https://api.acme.example.com/x", False, True,
     "WEB_ENDPOINT's id family is frozenset() (§1.2) -- id denies; scope_key never consults that table (§1.1)"),
    ("MOBILE_APP", "com.kronos.*", "com.kronos.demo", True, True,
     "dotted bundle id, 'host' shape either way -- both paths agree"),
    ("MOBILE_COMPONENT", "com.kronos.*", "com.kronos.democomponent", True, True,
     "same 'host' family as MOBILE_APP (§0.2 evidence) -- both paths agree"),
    ("SECRET", "com.kronos.*", "com.kronos.demo", False, True,
     "SECRET's id family is frozenset() (§1.1/§1.2/FORK-Y) -- id denies; "
     "scope_key (bundle_id in every real call site) is gated on its own 'host' shape instead"),
    ("CLOUD_RESOURCE", "kronos-cybergym-*", "kronos-cybergym-general-secrets", True, False,
     "dot-free ambiguous string: id path keeps CLOUD_RESOURCE's free bucket-glob expansion (§0.2, the only "
     "type that does); scope_key path has no node_type signal to grant that, so it is forced to the "
     "narrower host-boundary reading (§1.1's own worked example) and the mid-label pattern fails it"),
    ("FINDING", "*", "finding-demo", False, True,
     "FINDING's id family is frozenset() (FORK-W(2)) -- id denies unconditionally; §1.1's scope_key gate "
     "is type-blind by design, so a maximally permissive pattern still authorizes a scope_key here even "
     "though no production ingester ever sets one for FINDING -- a direct, intended consequence of §1.1, "
     "not a new production reachability (no FINDING call site sets scope_key)"),
]


def test_b105_8_2_every_row_records_a_citation_and_a_rule_number():
    """SPEC_BRIEF10.5 §8.2 / §5.2 item 6: the per-row citation and rule
    number are ENFORCED, not merely written in a comment. Every
    NODE_TYPE_SHAPES row must appear in NODE_TYPE_SHAPE_EVIDENCE with a
    rule of 1 or 5 and a non-empty citation, and no citation may rest on
    a docstring, a convention, or another node type (§1.2 rules 3/4)."""
    from kronos.scope_guard import NODE_TYPE_SHAPE_EVIDENCE as EV

    assert set(EV) == set(NODE_TYPE_SHAPES), (
        "every row needs evidence: missing=%s extra=%s"
        % (sorted(set(NODE_TYPE_SHAPES) - set(EV)), sorted(set(EV) - set(NODE_TYPE_SHAPES))))
    for node_type, (rule, citation) in EV.items():
        assert rule in (1, 5), (node_type, rule)
        assert citation.strip(), node_type
        low = citation.lower()
        assert "docstring" not in low, (node_type, "cites a docstring -- §1.2 rule 3 forbids it")
        assert "convention" not in low, (node_type, "cites a convention -- §1.2 rule 3 forbids it")
        # rule 1 must name a producer call site or a ratified brief;
        # rule 5 must name a schema.py line.
        if rule == 5:
            assert "schema.py:" in citation, (node_type, "rule 5 must cite a schema.py line")
        else:
            assert ("NodeUpsert" in citation) or ("SPEC_BRIEF" in citation), (
                node_type, "rule 1 must name a producer call site or a ratified brief decision")


def test_b104_5_4_id_scope_key_axis_cell_count():
    assert len(_B104_ID_SCOPE_KEY_AXIS) == 9


@pytest.mark.parametrize("node_type,pattern,target,expected_id,expected_scope_key,why", _B104_ID_SCOPE_KEY_AXIS)
def test_b104_5_4_id_scope_key_axis(node_type, pattern, target, expected_id, expected_scope_key, why):
    m = _m([pattern], [])
    assert scope_guard(target, m, node_type=node_type, target_kind="id") is expected_id, why
    assert scope_guard(target, m, node_type=node_type, target_kind="scope_key") is expected_scope_key, why


# =============================================================================
# SPEC_BRIEF10.5 -- address-shaped exclusions (§1.2, §5.1) and rule 5 (§1.1,
# §5.2). Prefixed test_b105_. Every expected value below is derived from the
# brief's prose (cited per case), never from running the code. Exclusion
# cases go through the PUBLIC API: in_scope=['*'] + target_kind='scope_key'
# yields unconfounded exclusion semantics (§1.3) -- the scope_key path
# consults no node-type id-shape table, so a False can only be the exclusion.
# =============================================================================

_B105_ADDR_EXCLUSION_CASES = [
    # (excluded, target, prose authority)
    ("http://10.0.0.5/admin/*", "10.0.0.5", "§1.2 shape-blind"),
    ("http://10.0.0.5/admin/*", "10.0.0.5:8443", "§1.2 shape-blind + port-blind"),
    ("http://10.0.0.5*", "10.0.0.5", "§1.2 path-free, H3 itself required"),
    ("http://10.0.0.5:8443/x/*", "10.0.0.5", "§1.2 port-blind"),
    ("http://[2001:db8::1]:443/x/*", "[2001:db8::1]:443", "§1.2 bracketed IPv6"),
    ("http://[2001:db8::1]/x/*", "[2001:db8::1]", "§1.2 bracketed IPv6, no port"),
    ("http://[::ffff:10.0.0.5]/x/*", "[::ffff:10.0.0.5]", "§5.1 IPv4-mapped form"),
    ("http://[fe80::1%eth0]/x/*", "[fe80::1%eth0]", "§5.1 zone-indexed form"),
]


@pytest.mark.parametrize("excluded,target,why", _B105_ADDR_EXCLUSION_CASES)
def test_b105_5_1_address_shaped_exclusion_denies(excluded, target, why):
    m = _m(["*"], [excluded])
    assert scope_guard(target, m, node_type="HOST", target_kind="scope_key") is False, why


def test_b105_5_1_allow_side_controls_unchanged():
    """§5.1: CIDR and bare-IP allow patterns keep current behaviour
    exactly (proves §1.2 did not leak into the allow path)."""
    assert _sg("10.0.0.5", _m(["10.0.0.0/24"], []), "HOST") is True
    assert _sg("10.0.0.5:8443", _m(["10.0.0.0/24"], []), "SERVICE") is True
    assert _sg("10.0.0.9", _m(["10.0.0.0/24"], []), "HOST") is True
    assert _sg("10.0.1.9", _m(["10.0.0.0/24"], []), "HOST") is False
    assert _sg("10.0.0.5", _m(["10.0.0.5"], []), "HOST") is True
    assert _sg("10.0.0.6", _m(["10.0.0.5"], []), "HOST") is False
    assert _sg("[2001:db8::1]:443", _m(["2001:db8::/32"], []), "SERVICE") is True


# --- §5.2 -- rule 5 and the re-derived table.

_B105_ALL_SHAPES = {
    "host": "web-01.acme.example.com",
    "ip": "10.0.0.5",
    "host_port": "web-01:8080",
    "ip_port": "10.0.0.5:8080",
}


def test_b105_5_2_1_host_port_shaped_host_id_is_allowed_rule_1():
    """§1.1 as amended (FORK-AB rejected): HOST's family is settled by
    rule 1 -- Brief #10.3 §1.2's ratified prose table assigns
    `host, ip, host_port, ip_port`, locked by test_b103_h2. Rule 5 is
    never reached for this row, so a port-bearing HOST id IS in family.
    The expectation here is derived from that prose, not from the
    matcher's behaviour."""
    assert NODE_TYPE_SHAPES["HOST"] == frozenset({"host", "ip", "host_port", "ip_port"})
    assert _sg("web-01:8080", _m(["*"], []), "HOST", "id") is True
    assert _sg("10.0.0.5:8080", _m(["*"], []), "HOST", "id") is True


def test_b105_5_2_2_host_host_and_ip_ids_follow_family():
    m = _m(["*"], [])
    assert _sg(_B105_ALL_SHAPES["host"], m, "HOST", "id") is True
    assert _sg(_B105_ALL_SHAPES["ip"], m, "HOST", "id") is True


def test_b105_5_2_3_service_all_four_shapes_follow_family():
    assert NODE_TYPE_SHAPES["SERVICE"] == frozenset({"host", "ip", "host_port", "ip_port"})
    m = _m(["*"], [])
    for shape, target in _B105_ALL_SHAPES.items():
        assert _sg(target, m, "SERVICE", "id") is True, shape


@pytest.mark.parametrize("node_type", ["WEB_ENDPOINT", "PARAMETER"])
def test_b105_5_2_4_web_endpoint_and_parameter_deny_on_id(node_type):
    """§1.1 rule 5: identity lives in a url/name column, id not required
    to carry it -> frozenset()."""
    assert NODE_TYPE_SHAPES[node_type] == frozenset()
    for target in list(_B105_ALL_SHAPES.values()) + ["https://api.acme.example.com/x"]:
        assert _sg(target, _m(["*"], []), node_type, "id") is False


def test_b105_5_2_5_api_endpoint_keeps_url_under_rule_1():
    """§1.1: API_ENDPOINT carries url/method columns too, yet keeps
    {url}: a producer exists (parser.py:276), rule 1 outranks rule 5."""
    assert NODE_TYPE_SHAPES["API_ENDPOINT"] == frozenset({"url"})
    assert _sg("https://api.acme.example.com/x", _m(["*"], []), "API_ENDPOINT", "id") is True
    assert _sg("api.acme.example.com", _m(["*"], []), "API_ENDPOINT", "id") is False


# =============================================================================
# SPEC_BRIEF10.5 §1.3 / §5.3 -- THE REBUILT §5.4 GRID.
#
# Differences from the 10.3 grid above (which is kept, untouched, as a legacy
# regression lock -- guardrail 11):
#   (1) EVERY cell is a (value, clause) pair: `value` is True/False/_PAUSE and
#       `clause` names the prose clause that determines it (registry _CL).
#       Values are derived from the briefs' PROSE, never from running the
#       code. A cell no prose determines is _PAUSE: it is reported, NOT
#       filled, and NOT asserted.
#   (2) The allow side runs for EVERY node type in the table (12 types), not
#       HOST alone.
#   (3) Both sides assert through the PUBLIC API (`scope_guard`). Exclusions:
#       in_scope=['*'] + target_kind='scope_key' -- the scope_key path
#       consults no node-type id-shape table, so a False can only come from
#       the exclusion (unconfounded).
# =============================================================================

_PAUSE = "PAUSE-DECISION"

_CL = {
    "10.r1": "SPEC_BRIEF10 §1.1 r1: *.acme.com = subdomains, not apex",
    "10.r2": "SPEC_BRIEF10 §1.1 r2: host entry authorizes bare host + std ports 80/443 + http/https URLs on them",
    "10.r4": "SPEC_BRIEF10 §1.1 r4: nonstandard port needs an explicit entry; a port entry covers host:port and its URL forms (F8)",
    "10.r5": "SPEC_BRIEF10 §1.1 r5: only the URL host component is consulted (userinfo/path/query never authorize)",
    "10.r6": "SPEC_BRIEF10 §1.1 r6: allow narrow, exclusion broad (every port/scheme/path/representation); when in doubt, deny",
    "10.r7": "SPEC_BRIEF10 §1.1 r7: CIDR / bare-IP entry authorizes all ports on a matching address",
    "10.5.7": "SPEC_BRIEF10 §5.7: a hostname pattern never authorizes a bundle id / other-shaped target",
    "10.1.1.1": "SPEC_BRIEF10.1 §1.1: trailing * expands only at ':' '/' end-of-string, never across '.' or mid-label",
    "10.1.1.2": "SPEC_BRIEF10.1 §1.2 Option A: trailing * after a complete host = that host, any port, any path",
    "10.1.1.3": "SPEC_BRIEF10.1 §1.3: bucket/ARN pattern never authorizes a hostname-shaped target; free expansion only for bucket/ARN targets",
    "10.1.2.2": "SPEC_BRIEF10.1 §2.2: the boundary rule is allow-side only and must not narrow any exclusion",
    "10.1.U": "SPEC_BRIEF10.1 FORK-U: a both-ends wildcard is not a host pattern; PR12 verdict (denies api.acme.com:8443) pinned",
    "10.2.1": "SPEC_BRIEF10.2 §1: scheme://host:port* = that scheme, host and exact port, structural compare",
    "10.3.1.2": "SPEC_BRIEF10.3 §1.2 / 10.5 §1.1: node-type shape family gate (type-blind classify_target, family = NODE_TYPE_SHAPES prose table)",
    "10.3.1.2c": "SPEC_BRIEF10.3 §1.2: free mid-token glob expansion is CLOUD_RESOURCE-only (dot-free = hostname elsewhere, H2)",
    "10.3.1.3": "SPEC_BRIEF10.3 §1.3: exclusions are representation-blind across shapes and independent of node_type",
    "10.4.1.3": "SPEC_BRIEF10.4 §1.3: exclusion discards a URL pattern's path/port/scheme and compares host identity; allow side stays literal and path-aware",
    "10.5.1.2": "SPEC_BRIEF10.5 §1.2: address-shaped targets yield their address as exclusion identity (port/scheme/path ignored)",
    "10.5.pd5a": "SPEC_BRIEF10.5 §1.3 (PD-5): both-ends glob ALLOW side denies -- allow-narrow, and SPEC_BRIEF10.1 FORK-U already holds that a both-ends wildcard is not a host pattern",
    "10.5.pd5e": "SPEC_BRIEF10.5 §1.3 (PD-5): both-ends glob EXCLUSION side is DENY-BROAD -- host-identity glob match, per §1.3 'strictly broader than the allow side and that asymmetry is the specification'",
}

_T_ALL = _TARGETS  # alias for readability
(_t1, _t2, _t3, _t4, _t5, _t6, _t7, _t8, _t9, _t10, _t11, _t12, _t13, _t14) = _TARGETS
_H_SAME = [_t1, _t2, _t6, _t7, _t8]  # every representation of host api.acme.com


def _row(default, overrides=None):
    """-> {target: (value, clause_key)}; default is (value, clause)."""
    out = {t: default for t in _TARGETS}
    for t, cell in (overrides or {}).items():
        out[t] = cell
    return out


# ---- CORE ALLOW SEMANTICS: pattern x target, assuming the node-type gate
# ADMITS the target. Prose-derived; "native" reading (a dot-free ambiguous
# string reads as a hostname -- SPEC_BRIEF10.3 H2).
_CORE_ALLOW = {
    _P1_BARE_HOST: _row((_F, "10.r4"), {
        _t1: (_T, "10.r2"), _t6: (_T, "10.r2"), _t8: (_T, "10.r5"),
        _t7: (_F, "10.r4"), _t2: (_F, "10.r4"),
        _t10: (_F, "10.1.1.1"), _t11: (_F, "10.1.1.1"),
    }),
    _P2_LEADING_GLOB: _row((_F, "10.r1"), {
        _t1: (_T, "10.r2"), _t6: (_T, "10.r2"), _t8: (_T, "10.r5"),
        _t7: (_F, "10.r4"), _t2: (_F, "10.r4"),
        _t10: (_F, "10.1.1.1"), _t11: (_F, "10.1.1.1"),
    }),
    _P3_TRAILING_GLOB: _row((_F, "10.1.1.1"), {
        _t1: (_T, "10.1.1.2"), _t2: (_T, "10.1.1.2"), _t6: (_T, "10.1.1.2"),
        _t7: (_T, "10.1.1.2"), _t8: (_T, "10.r5"),
        _t10: (_F, "10.1.1.1"), _t11: (_F, "10.1.1.1"),
    }),
    _P4_BOTH_ENDS_GLOB: _row((_F, "10.1.U"), {
        _t1: (_F, "10.5.pd5a"),
        _t2: (_F, "10.1.U"),
    }),
    _P5_BARE_IP: _row((_F, "10.r7"), {_t3: (_T, "10.r7"), _t4: (_T, "10.r7")}),
    _P6_CIDR: _row((_F, "10.r7"), {_t3: (_T, "10.r7"), _t4: (_T, "10.r7")}),
    _P7_HOST_PORT: _row((_F, "10.r4"), {_t2: (_T, "10.r4"), _t7: (_T, "10.r4")}),
    _P8_URL_NO_PORT: _row((_F, "10.4.1.3")),
    _P9_URL_WITH_PORT: _row((_F, "10.4.1.3")),
    _P10_URL_TRAILING_GLOB: _row((_F, "10.2.1"), {
        _t6: (_T, "10.1.1.2"), _t7: (_T, "10.1.1.2"), _t8: (_T, "10.r5"),
        _t10: (_F, "10.1.1.1"), _t11: (_F, "10.1.1.1"),
    }),
    _P11_BUCKET_GLOB: _row((_F, "10.1.1.3")),
    _P12_ARN_GLOB: _row((_F, "10.1.1.3"), {_t13: (_T, "10.1.1.3")}),
    _P13_BUNDLE_GLOB: _row((_F, "10.5.7"), {_t14: (_T, "10.5.7")}),
}

# CLOUD_RESOURCE reads a dot-free string as a bucket: free mid-token expansion
# (SPEC_BRIEF10.3 §1.2 -- the ONLY type that gets it; SPEC_BRIEF10.1 §1.3).
_CORE_ALLOW_CLOUD_OVERRIDE = {(_P11_BUCKET_GLOB, _t12): (_T, "10.3.1.2c")}

# Effective shape of each target per node-type reading (prose: SPEC_BRIEF10.3
# §1.2 + §4/H2 -- dot-free is a hostname except under CLOUD_RESOURCE).
_SHAPE_NATIVE = {
    _t1: "host", _t2: "host_port", _t3: "ip", _t4: "ip_port", _t5: "ip_port",
    _t6: "url", _t7: "url", _t8: "url", _t9: "host", _t10: "host", _t11: "host",
    _t12: "host", _t13: "arn", _t14: "host",
}
_SHAPE_CLOUD = dict(_SHAPE_NATIVE, **{_t9: "bucket_name", _t12: "bucket_name"})

# The family table as the PROSE states it (SPEC_BRIEF10.5 §1.1 / 8.3 and
# SPEC_BRIEF10.3 §1.2); declared here independently of scope_guard.py and
# cross-checked against NODE_TYPE_SHAPES by test_b105_5_3_family_prose_matches_table.
_FAMILY_PROSE = {
    "HOST": {"host", "ip", "host_port", "ip_port"},
    "SERVICE": {"host", "ip", "host_port", "ip_port"},
    "WEB_ENDPOINT": set(),
    "API_ENDPOINT": {"url"},
    "CLOUD_RESOURCE": {"bucket_name", "arn"},
    "MOBILE_APP": {"host"},
    "MOBILE_COMPONENT": {"host"},
    "SECRET": set(),
    "PARAMETER": set(),
    "IDENTITY": set(),
    "TECHNOLOGY": set(),
    "FINDING": set(),
}
_GRID_NODE_TYPES = list(_FAMILY_PROSE)


def _allow_cell(node_type, pattern, target):
    shapes = _SHAPE_CLOUD if node_type == "CLOUD_RESOURCE" else _SHAPE_NATIVE
    if shapes[target] not in _FAMILY_PROSE[node_type]:
        return (_F, "10.3.1.2")
    if node_type == "CLOUD_RESOURCE" and (pattern, target) in _CORE_ALLOW_CLOUD_OVERRIDE:
        return _CORE_ALLOW_CLOUD_OVERRIDE[(pattern, target)]
    return _CORE_ALLOW[pattern][target]


_ALLOW_GRID = {
    (nt, p, t): _allow_cell(nt, p, t)
    for nt in _GRID_NODE_TYPES for p in _PATTERNS for t in _TARGETS
}

# ---- EXCLUSION GRID (node-type independent: SPEC_BRIEF10.3 §1.3).
_EXCL_HOSTISH = [_t1, _t2, _t6, _t7, _t8, _t10, _t11]
_EXCLUSION_GRID = {
    _P1_BARE_HOST: _row((_F, "10.r6"), {t: (_T, "10.r6") for t in _H_SAME}),
    _P2_LEADING_GLOB: _row((_F, "10.r1"), {t: (_T, "10.r6") for t in _H_SAME}),
    _P3_TRAILING_GLOB: _row((_F, "10.r6"), dict(
        {t: (_T, "10.r6") for t in _H_SAME},
        **{_t10: (_T, "10.1.2.2"), _t11: (_T, "10.1.2.2")})),
    _P4_BOTH_ENDS_GLOB: _row((_F, "10.1.U"), {t: (_T, "10.5.pd5e") for t in _EXCL_HOSTISH}),
    _P5_BARE_IP: _row((_F, "10.5.1.2"), {_t3: (_T, "10.5.1.2"), _t4: (_T, "10.5.1.2")}),
    _P6_CIDR: _row((_F, "10.5.1.2"), {_t3: (_T, "10.5.1.2"), _t4: (_T, "10.5.1.2")}),
    _P7_HOST_PORT: _row((_F, "10.r6"), {t: (_T, "10.3.1.3") for t in _H_SAME}),
    _P8_URL_NO_PORT: _row((_F, "10.4.1.3"), {t: (_T, "10.4.1.3") for t in _H_SAME}),
    _P9_URL_WITH_PORT: _row((_F, "10.4.1.3"), {t: (_T, "10.4.1.3") for t in _H_SAME}),
    _P10_URL_TRAILING_GLOB: _row((_F, "10.4.1.3"), {t: (_T, "10.4.1.3") for t in _H_SAME}),
    _P11_BUCKET_GLOB: _row((_F, "10.3.1.3"), {_t12: (_T, "10.3.1.3")}),
    _P12_ARN_GLOB: _row((_F, "10.3.1.3"), {_t13: (_T, "10.3.1.3")}),
    _P13_BUNDLE_GLOB: _row((_F, "10.3.1.3"), {_t14: (_T, "10.3.1.3")}),
}

_ALLOW_CELLS = [(nt, p, t) for nt in _GRID_NODE_TYPES for p in _PATTERNS for t in _TARGETS]
_EXCL_CELLS = [(p, t) for p in _PATTERNS for t in _TARGETS]
_ALLOW_ASSERTED = [c for c in _ALLOW_CELLS if _ALLOW_GRID[c][0] is not _PAUSE]
_EXCL_ASSERTED = [c for c in _EXCL_CELLS if _EXCLUSION_GRID[c[0]][c[1]][0] is not _PAUSE]
_PAUSE_ALLOW = sorted((nt, p, t) for (nt, p, t) in _ALLOW_CELLS if _ALLOW_GRID[(nt, p, t)][0] is _PAUSE)
_PAUSE_EXCL = sorted((p, t) for (p, t) in _EXCL_CELLS if _EXCLUSION_GRID[p][t][0] is _PAUSE)


def test_b105_5_3_grid_completeness_every_cell_declared_and_clause_referenced():
    """Zero undeclared cells; EVERY cell (allow x 12 types, and exclusion)
    carries a non-empty clause reference that exists in the registry."""
    assert len(_GRID_NODE_TYPES) == 12 and len(_PATTERNS) == 13 and len(_TARGETS) == 14
    undeclared = 0
    cells = 0
    for nt in _GRID_NODE_TYPES:
        for p in _PATTERNS:
            for t in _TARGETS:
                cell = _ALLOW_GRID.get((nt, p, t))
                if cell is None:
                    undeclared += 1
                    continue
                cells += 1
                assert cell[0] in (_T, _F, _PAUSE)
                assert cell[1] in _CL, (nt, p, t, cell)
    for p in _PATTERNS:
        for t in _TARGETS:
            cell = _EXCLUSION_GRID.get(p, {}).get(t)
            if cell is None:
                undeclared += 1
                continue
            cells += 1
            assert cell[0] in (_T, _F, _PAUSE)
            assert cell[1] in _CL, (p, t, cell)
    assert undeclared == 0
    assert cells == 12 * 13 * 14 + 13 * 14 == 2366


def test_b105_5_3_pause_decision_cells_are_exactly_the_reported_set():
    """The cells no prose in #10..#10.5 determines are NOT filled and NOT
    asserted. This test pins exactly which they are, so a silent fill (or a
    silent new gap) fails here. _P4_BOTH_ENDS_GLOB x _T1_HOST is the known
    one; the exclusion-side rows below are the same question (a both-ends
    glob vs the exact host / its representations) and are referred likewise."""
    # SPEC_BRIEF10.5 §1.3 (PD-5, maintainer-ruled): the 11 deferred cells
    # are now decided -- allow side denies (allow-narrow, FORK-U),
    # exclusion side is deny-broad. ZERO cells remain deferred, and this
    # test pins that: a NEW prose gap appearing later fails here.
    assert _PAUSE_ALLOW == []
    assert _PAUSE_EXCL == []


def test_b105_5_3_family_prose_matches_table():
    from kronos.scope_guard import NODE_TYPE_SHAPES as table
    for nt, fam in _FAMILY_PROSE.items():
        assert set(table[nt]) == fam, nt
    assert set(_FAMILY_PROSE) == set(table)


def test_b105_5_3_legacy_host_row_and_exclusion_agree_with_rebuilt_grid():
    """The legacy 10.3 grid (kept, unedited) must agree with the rebuilt
    grid everywhere the rebuilt grid asserts."""
    for p in _PATTERNS:
        for t in _TARGETS:
            v = _ALLOW_GRID[("HOST", p, t)][0]
            if v is not _PAUSE:
                assert _ALLOW_HOST_EXPECTATIONS[p][t] is v, ("allow", p, t)
            e = _EXCLUSION_GRID[p][t][0]
            if e is not _PAUSE:
                assert _EXCLUSION_EXPECTATIONS[p][t] is e, ("excl", p, t)


@pytest.mark.parametrize("node_type,pattern,target", _ALLOW_ASSERTED)
def test_b105_5_3_allow_grid_per_node_type_public_api(node_type, pattern, target):
    expected, clause = _ALLOW_GRID[(node_type, pattern, target)]
    got = scope_guard(target, _m([pattern], []), node_type=node_type, target_kind="id")
    assert got is expected, _CL[clause]


@pytest.mark.parametrize("pattern,target", _EXCL_ASSERTED)
def test_b105_5_3_exclusion_grid_public_api(pattern, target):
    """in_scope=['*'] + target_kind='scope_key': unconfounded exclusion
    semantics (no id-shape family table is consulted on the scope_key path),
    so a False here can only come from the exclusion. expected True ==
    the exclusion denies."""
    expected_excluded, clause = _EXCLUSION_GRID[pattern][target]
    got = scope_guard(target, _m(["*"], [pattern]), node_type="HOST", target_kind="scope_key")
    assert (got is False) is expected_excluded, _CL[clause]


# --- SPEC_BRIEF10.5 §1.4 / §5.4 -- the §6 gate is BYTE-verbatim.
# A real byte comparison (not a presence grep): §6's block is extracted from
# SPEC_BRIEF10.5.md and compared as bytes against the marker-delimited block
# in README_scope.md and DECISIONS.md.
import pathlib as _pl

_REPO = _pl.Path(__file__).resolve().parent.parent
_GATE_BEGIN = "<!-- BEGIN SPEC_BRIEF10.5 §6 GATE (byte-verbatim; tests/test_scope_guard.py compares) -->\n".encode()
_GATE_END = "<!-- END SPEC_BRIEF10.5 §6 GATE -->\n".encode()


def _spec_gate_bytes() -> bytes:
    raw = (_REPO / "SPEC_BRIEF10.5.md").read_bytes()
    start = raw.index(b"FORK-2 is complete, and issue #2 may close")
    end = raw.index(b"\n\n---\n", start)
    return raw[start:end] + b"\n"


def _embedded_gate_bytes(path: _pl.Path) -> bytes:
    raw = path.read_bytes()
    assert raw.count(_GATE_BEGIN) == 1, path
    s = raw.index(_GATE_BEGIN) + len(_GATE_BEGIN)
    e = raw.index(_GATE_END, s)
    return raw[s:e]


@pytest.mark.parametrize("rel", ["src/kronos/README_scope.md", "DECISIONS.md"])
def test_b105_5_4_gate_block_is_byte_identical_to_spec_section_6(rel):
    spec = _spec_gate_bytes()
    assert spec.startswith(b"FORK-2 is complete") and spec.rstrip().endswith(b"maintainer action.")
    assert b"This PR is merged" in spec and b"Issue #2 closed" in spec  # the very words 10.4 paraphrased
    assert _embedded_gate_bytes(_REPO / rel) == spec


# --- SPEC_BRIEF10.5 §5.5 / §8.8 -- guardrail §9 as a STANDING differential.
# The allow side is enumerated across the §5.4 pattern x target lists at
# dcbdba9 (main, type-blind), 2a676a8 (PR #15 head before this brief) and the
# current head. Old trees are exported read-only with `git archive` into a
# temp dir (no branch is checked out). Required: ZERO allow-side differences,
# and every exclusion-side difference is "allowed -> excluded" (False -> True
# in "is excluded" terms).
import importlib.util as _ilu
import io as _io
import subprocess as _sp
import tarfile as _tarfile
import tempfile as _tempfile

_OLD_REFS = ("dcbdba9", "2a676a8")

# The node type under which each target is a legitimate id (the type-blind
# dcbdba9 has no type; the typed trees are evaluated under the type whose
# prose family (SPEC_BRIEF10.3 §1.2) admits the target -- comparing a URL
# under HOST would measure the SPEC_BRIEF10.3 type gate, not this brief).
_DIFF_NODE_TYPE = {
    _T1_HOST: "HOST", _T2_HOST_PORT: "HOST", _T3_IP: "HOST", _T4_IP_PORT: "HOST",
    _T5_BRACKETED_IPV6_PORT: "HOST", _T6_URL_STD_PORT: "API_ENDPOINT",
    _T7_URL_NONSTD_PORT: "API_ENDPOINT", _T8_URL_USERINFO: "API_ENDPOINT",
    _T9_DOT_FREE_HOST: "HOST", _T10_LOOKALIKE: "HOST", _T11_MID_LABEL: "HOST",
    _T12_BUCKET_NAME: "CLOUD_RESOURCE", _T13_ARN: "CLOUD_RESOURCE",
    _T14_BUNDLE_ID: "MOBILE_APP",
}


def _load_old_scope_guard(ref, tmp):
    try:
        _sp.run(["git", "cat-file", "-e", f"{ref}^{{commit}}"], cwd=_REPO, check=True,
                capture_output=True)
    except (_sp.CalledProcessError, FileNotFoundError):
        pytest.skip(f"{ref} not present in this checkout (shallow clone?)")
    tar = _sp.run(["git", "archive", ref, "src/kronos/scope_guard.py"], cwd=_REPO,
                  check=True, capture_output=True).stdout
    with _tarfile.open(fileobj=_io.BytesIO(tar)) as tf:
        tf.extractall(tmp, filter="data")
    path = _pl.Path(tmp) / "src" / "kronos" / "scope_guard.py"
    path.chmod(0o444)
    spec = _ilu.spec_from_file_location(f"_old_scope_guard_{ref}", path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# §5.1's address-shaped patterns/targets join the enumeration so the
# deny-ward §1.2 change is actually exercised by the differential.
_DIFF_PATTERNS = _PATTERNS + [c[0] for c in _B105_ADDR_EXCLUSION_CASES]
_DIFF_TARGETS = _TARGETS + [c[1] for c in _B105_ADDR_EXCLUSION_CASES]
_DIFF_NODE_TYPE.update({c[1]: "HOST" for c in _B105_ADDR_EXCLUSION_CASES})


def _verdicts(fn_allow, fn_excl):
    allow, excl = {}, {}
    for p in _DIFF_PATTERNS:
        for t in _DIFF_TARGETS:
            allow[(p, t)] = fn_allow(p, t)
            excl[(p, t)] = fn_excl(p, t)
    return allow, excl


def _tree_verdicts(ref, tmp):
    if ref == "HEAD":
        mod = __import__("kronos.scope_guard", fromlist=["scope_guard"])
        sg = mod.scope_guard
        return _verdicts(
            lambda p, t: sg(t, _m([p], []), node_type=_DIFF_NODE_TYPE[t], target_kind="id"),
            lambda p, t: sg(t, _m(["*"], [p]), node_type="HOST", target_kind="scope_key") is False,
        )
    mod = _load_old_scope_guard(ref, tmp)
    sg = mod.scope_guard
    if ref == "dcbdba9":  # type-blind
        return _verdicts(
            lambda p, t: sg(t, _m([p], [])),
            lambda p, t: sg(t, _m(["*"], [p])) is False,
        )
    return _verdicts(
        lambda p, t: sg(t, _m([p], []), node_type=_DIFF_NODE_TYPE[t], target_kind="id"),
        lambda p, t: sg(t, _m(["*"], [p]), node_type="HOST", target_kind="scope_key") is False,
    )


def test_b105_5_5_differential_allow_side_unchanged_exclusion_only_tightens():
    with _tempfile.TemporaryDirectory() as tmp:
        trees = {}
        for ref in (*_OLD_REFS, "HEAD"):
            sub = _pl.Path(tmp) / ref
            sub.mkdir()
            trees[ref] = _tree_verdicts(ref, sub)
    pairs = len(set(_DIFF_PATTERNS)) * len(set(_DIFF_TARGETS))
    assert len(trees["HEAD"][0]) == pairs
    head_allow, head_excl = trees["HEAD"]
    for ref in _OLD_REFS:
        old_allow, old_excl = trees[ref]
        allow_diffs = [k for k in old_allow if old_allow[k] != head_allow[k]]
        assert allow_diffs == [], (ref, allow_diffs)  # guardrail §9: ZERO allow-side differences
        excl_diffs = [k for k in old_excl if old_excl[k] != head_excl[k]]
        # every exclusion-side difference is not-excluded -> excluded
        assert all(old_excl[k] is False and head_excl[k] is True for k in excl_diffs), (ref, excl_diffs)
    # 2a676a8 -> head additionally: the address-shaped exclusion fix (§1.2) is
    # a real, nonzero deny-ward change (else this test would prove nothing).
    import sys as _sys
    for ref in _OLD_REFS:
        oa, oe = trees[ref]
        print(f"DIFFERENTIAL {ref}->head: pairs={pairs} "
              f"allow_diffs={sum(oa[k] != head_allow[k] for k in oa)} "
              f"excl_diffs={sum(oe[k] != head_excl[k] for k in oe)}", file=_sys.stderr)
    _, mid_excl = trees["2a676a8"]
    assert [k for k in mid_excl if mid_excl[k] != head_excl[k]] != []
