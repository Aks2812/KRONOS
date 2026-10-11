"""Tests for the mobile static ingestion module (SPEC_BRIEF2).

Written before the implementation per testing-with-discernment: these are
behavior tests that fail if extraction misses a planted secret/endpoint,
not coverage padding. The hostile-input tests are the most important ones
for KRONOS (SPEC_BRIEF2's own framing) — they prove the mobile parser
cannot become a new path around Brief #1's upsert allowlist.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest

from kronos.ingest import EdgeUpsert, NodeUpsert, apply_upserts
from kronos.ingest.mobile import light_extractors
from kronos.ingest.mobile.manifest_parser import ManifestParseError, parse_manifest
from kronos.ingest.mobile.mobsf_client import MobSFClient
from kronos.ingest.mobile.parser import ingest_mobile_static


def _load_mobsf_client_from_env() -> MobSFClient | None:
    """Reads tests/../.env for MOBSF_URL/MOBSF_API_KEY (operator-local,
    gitignored — never committed). Returns None if absent so this test
    file works unchanged on a machine without a MobSF instance set up."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return None
    values: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    url, key = values.get("MOBSF_URL"), values.get("MOBSF_API_KEY")
    if not url or not key:
        return None
    return MobSFClient(url, key)


FIXTURE_APK = Path(__file__).parent / "fixtures" / "leaky_test.apk"
BUNDLE_ID = "com.kronos.testfixture.leakyapp"
PLAINTEXT_SECRET = "KRONOS_FIXTURE_PLAINTEXT_SECRET_abcdef1234567890"
OBFUSCATED_SECRET_DECODED = "kronos_test_obfuscated_secret_987654321"
ENDPOINT_URL = "https://internal-api.kronos-fixture.test/v1/admin"


def _secret_node_id(value: str) -> str:
    return f"secret:{hashlib.sha256(value.encode()).hexdigest()[:16]}"


@pytest.fixture(scope="module")
def fixture_apk_exists():
    if not FIXTURE_APK.exists():
        pytest.fail(
            f"{FIXTURE_APK} missing — run tests/fixtures/build_leaky_apk.sh first"
        )
    return FIXTURE_APK


# ---------------------------------------------------------------------------
# Happy path: extraction against the planted fixture
# ---------------------------------------------------------------------------


def test_extracts_planted_secret_and_endpoint_and_components(engagement_graph, fixture_apk_exists):
    g = engagement_graph
    upserts = ingest_mobile_static(fixture_apk_exists, g)
    apply_upserts(g, upserts)

    app = g.get_node("MOBILE_APP", BUNDLE_ID)
    assert app is not None
    assert app["bundle_id"] == BUNDLE_ID
    assert app["source"] == "static"

    plaintext_id = _secret_node_id(PLAINTEXT_SECRET)
    secret_node = g.get_node("SECRET", plaintext_id)
    assert secret_node is not None
    assert secret_node["status"] == "extracted"
    assert secret_node["kind"] == "api_key"
    r = g.execute(
        "MATCH (a:MOBILE_APP {id: $bundle})-[:leaks]->(s:SECRET {id: $sid}) RETURN count(*)",
        {"bundle": BUNDLE_ID, "sid": plaintext_id},
    )
    assert r.get_next()[0] == 1

    obfuscated_id = _secret_node_id(OBFUSCATED_SECRET_DECODED)
    obf_node = g.get_node("SECRET", obfuscated_id)
    assert obf_node is not None
    assert obf_node["kind"] == "api_key_obfuscated"

    endpoint_node = g.get_node("API_ENDPOINT", ENDPOINT_URL)
    assert endpoint_node is not None
    r = g.execute(
        "MATCH (a:MOBILE_APP {id: $bundle})-[:references]->(e:API_ENDPOINT {id: $url}) RETURN count(*)",
        {"bundle": BUNDLE_ID, "url": ENDPOINT_URL},
    )
    assert r.get_next()[0] == 1

    leaky = g.get_node("MOBILE_COMPONENT", f"{BUNDLE_ID}/.LeakyActivity")
    assert leaky is not None
    assert leaky["exported"] is True
    internal = g.get_node("MOBILE_COMPONENT", f"{BUNDLE_ID}/.InternalService")
    assert internal is not None
    assert internal["exported"] is False

    # EVIDENCE: each secret gets a hash-addressed, linked evidence blob.
    r = g.execute(
        "MATCH (ev:EVIDENCE)-[:evidences]->(s:SECRET {id: $sid}) RETURN count(*)",
        {"sid": plaintext_id},
    )
    assert r.get_next()[0] == 1


def test_extraction_with_mobsf_anchor_does_not_crash_or_duplicate(engagement_graph, fixture_apk_exists):
    """Exercises the actual MobSF upload/scan/report path (decision D5:
    MobSF as primary anchor), not just the light-extractor fallback. Skips
    cleanly if no local MobSF is configured/reachable (SPEC_BRIEF2: "check
    reachability once and skip with a clear reason"), so this file runs
    unchanged on a machine without MobSF set up.
    """
    client = _load_mobsf_client_from_env()
    if client is None or not client.is_reachable():
        pytest.skip("MobSF not configured/reachable (see TOOLS_mobile.md) — skipping MobSF-anchored test")

    g = engagement_graph
    upserts = ingest_mobile_static(fixture_apk_exists, g, mobsf_client=client)
    apply_upserts(g, upserts)

    # The light-extractor findings must still be present even with MobSF in
    # the loop — MobSF augments, it doesn't replace, and must not cause
    # duplicates (plaintext secret found by both would be the same node id).
    plaintext_id = _secret_node_id(PLAINTEXT_SECRET)
    assert g.get_node("SECRET", plaintext_id) is not None
    r = g.execute("MATCH (s:SECRET {id: $sid}) RETURN count(s)", {"sid": plaintext_id})
    assert r.get_next()[0] == 1


def test_mobile_reingest_is_idempotent(engagement_graph, fixture_apk_exists):
    g = engagement_graph
    apply_upserts(g, ingest_mobile_static(fixture_apk_exists, g))
    apply_upserts(g, ingest_mobile_static(fixture_apk_exists, g))
    r = g.execute("MATCH (a:MOBILE_APP {id: $bundle}) RETURN count(a)", {"bundle": BUNDLE_ID})
    assert r.get_next()[0] == 1
    r = g.execute(
        "MATCH (s:SECRET {id: $sid}) RETURN count(s)", {"sid": _secret_node_id(PLAINTEXT_SECRET)}
    )
    assert r.get_next()[0] == 1
    r = g.execute("MATCH (e:API_ENDPOINT {id: $url}) RETURN count(e)", {"url": ENDPOINT_URL})
    assert r.get_next()[0] == 1


# ---------------------------------------------------------------------------
# Hostile input — the most important cases (SPEC_BRIEF2 security lens)
# ---------------------------------------------------------------------------


def test_hostile_manifest_malformed_xml_raises_clear_error_not_crash():
    with pytest.raises(ManifestParseError):
        parse_manifest("<manifest package='com.x'><application>" + "<activity" * 500)


def test_hostile_manifest_missing_package_raises_clear_error():
    with pytest.raises(ManifestParseError):
        parse_manifest("<manifest xmlns:android='http://schemas.android.com/apk/res/android'></manifest>")


def test_hostile_resource_value_does_not_crash_extractors():
    hostile = {
        "api_key": "\x00\x01" + "A" * 50_000 + "�",
        "secret_token": "'; DROP TABLE secrets; -- " + "x" * 100,
        "api_key_weird_b64": "====not-valid-base64====",
        "some_url": "https://" + "a" * 10_000 + ".test/" + ("?x=1" * 500),
    }
    secrets = light_extractors.extract_secrets_from_resources(hostile)
    endpoints = light_extractors.extract_endpoints_from_resources(hostile)
    # Must not crash (getting here at all proves it); must still produce
    # *something* bounded and well-typed.
    assert all(isinstance(s.decoded_value, str) for s in secrets)
    assert all(isinstance(e.url, str) for e in endpoints)


def test_hostile_input_graph_injection_blocked_by_construction(engagement_graph):
    """SPEC_BRIEF2's most important hostile case: a crafted secret/resource
    value shaped like a privileged-field injection attempt
    (status/confidence/in_scope) must not ride into the graph through the
    mobile parser. Three distinct properties, verified separately so none
    is overclaimed:

    (1) The extractor never treats a resource VALUE as a source of dict
        keys — a crafted value that *looks* like JSON with privileged
        keys is just string data, never parsed/spread.
    (2) `confidence` and `in_scope` are hard-forbidden on every
        NodeUpsert, always (schema.NODE_PROPS_FORBIDDEN) — no caller,
        this parser or any other, can ever set them via props. This is
        Brief #1's C1-fix backstop.
    (3) `status` is create-only, intentionally settable *at creation* by
        a trusted ingester (that's how "extracted" gets set in the first
        place) — it is NOT in the forbidden set, so a crafted NodeUpsert
        that sets ONLY `status` (no confidence/in_scope) is accepted at
        creation. The actual guarantee is narrower and code-level: THIS
        parser's own code (parser.py) always hardcodes
        `status="extracted"` literally — it never derives status from
        extracted/attacker-controlled content — which the happy-path and
        hostile-resource tests above already prove indirectly (the
        planted secrets' status is "extracted" even though their raw
        values are fully attacker-influenced test content).
    """
    g = engagement_graph

    # (1) A crafted resource value that LOOKS like an attempt to smuggle a
    # dict/JSON payload with privileged keys through a secret finding.
    hostile_resources = {
        "api_key": '{"status": "reported", "confidence": 10, "in_scope": true, "value": "x"}',
    }
    found = light_extractors.extract_secrets_from_resources(hostile_resources)
    assert len(found) == 1
    # The extractor only ever returns resource_name/raw_value/decoded_value/
    # obfuscation — there is no mechanism by which "status"/"confidence"/
    # "in_scope" could become dict KEYS here; the whole crafted string is
    # just string DATA (the secret value itself), never parsed as JSON or
    # spread into anything.
    assert found[0].decoded_value == hostile_resources["api_key"]

    g.upsert_node("MOBILE_APP", "com.hostile.app", {"bundle_id": "com.hostile.app", "platform": "android", "source": "static"})
    secret_id = "secret:" + hashlib.sha256(found[0].decoded_value.encode()).hexdigest()[:16]
    apply_upserts(
        g,
        [
            NodeUpsert(
                "SECRET",
                secret_id,
                {"value_ref": "sha256:deadbeef", "kind": "api_key", "status": "extracted", "source": "static"},
                scope_key="com.hostile.app",
            ),
            EdgeUpsert("leaks", "com.hostile.app", secret_id),
        ],
    )
    node = g.get_node("SECRET", secret_id)
    assert node["status"] == "extracted"
    assert node["confidence"] == 0
    # scope_guard-computed from the engagement's actual scope rules (this
    # fixture's manifest scopes "*.acme.example.com", which "com.hostile.app"
    # doesn't match) — never from anything in the crafted hostile string.
    assert node["in_scope"] is False

    # (2) `confidence`/`in_scope` are hard-forbidden on every caller,
    # always — the true backstop against a buggy or malicious parser.
    with pytest.raises(ValueError):
        apply_upserts(
            g,
            [
                NodeUpsert(
                    "SECRET",
                    "secret:hostile00000001",
                    {
                        "value_ref": "sha256:deadbeef",
                        "kind": "api_key",
                        "confidence": 10,  # forbidden: always rejected
                        "in_scope": True,  # forbidden: always rejected
                        "source": "static",
                    },
                    scope_key="com.hostile.app",
                )
            ],
        )

    # (3) `status` alone at creation is accepted by design (ingesters set
    # the initial status) — documenting the real boundary precisely rather
    # than claiming the allowlist blocks something it doesn't.
    g.upsert_node(
        "SECRET",
        "secret:hostile00000002",
        {"value_ref": "sha256:deadbeef", "kind": "api_key", "status": "reported", "source": "static"},
        scope_key="com.hostile.app",
    )
    assert g.get_node("SECRET", "secret:hostile00000002")["status"] == "reported"
    # And re-ingestion on the SAME id can never flip it back down or
    # change it — status is create-only, silently inert on a later call.
    g.upsert_node(
        "SECRET",
        "secret:hostile00000002",
        {"value_ref": "sha256:deadbeef", "kind": "api_key", "status": "extracted", "source": "static"},
        scope_key="com.hostile.app",
    )
    assert g.get_node("SECRET", "secret:hostile00000002")["status"] == "reported"
