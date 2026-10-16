"""Hermetic tests for the §3.1 denial matrix (SPEC_BRIEF7 "CyberGym
denial fidelity") — exercise `cybergym.cloud.sigv4_proxy.app` directly
with FastAPI's `TestClient` against a STUBBED upstream, per §3.4. No
Docker, no LocalStack, no network: fast and runnable anywhere.

Requests are built with boto3's own SigV4 signer (no network call —
signing is a pure local computation) so the Authorization headers sent
through the proxy are byte-for-byte what a real client would produce,
the same technique already used in test_sigv4_verify.py.

Every assertion below is on `(HTTP status, Error.Code)` only. `Message`
text is never part of the contract (SPEC_BRIEF7 §3.1) and no test here
may assert on it.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import boto3
import pytest
from botocore.awsrequest import AWSRequest
from fastapi.testclient import TestClient

from cybergym.cloud import sigv4_proxy
from cybergym.cloud.sigv4_verify import ParsedAuth, parse_authorization_header

PROXY_BASE = "http://localhost:4567"
GENERAL_ACCESS_KEY = "CYBERGYMGENERALUSER0001"
GENERAL_SECRET = "cybergym-fixture-general-secret-7f3a9c1e"
GENERAL_BUCKET = "kronos-cybergym-general"
ADMIN_BUCKET = "kronos-cybergym-admin-secrets"

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A TestClient wrapping the real proxy app. The upstream LocalStack
    call (`requests.request` inside sigv4_proxy) is stubbed per §3.4 —
    the denial matrix is decided entirely before that call is reached,
    so a stub is faithful to what the live range actually does for
    every denial arm, and gives the one authorized arm a deterministic
    stand-in response instead of a real network dependency."""

    class _StubUpstreamResponse:
        status_code = 200
        content = b"<stub-upstream-ok/>"
        headers: dict[str, str] = {}

    def _stub_request(**kwargs):  # noqa: ANN003, ANN201
        return _StubUpstreamResponse()

    monkeypatch.setattr(sigv4_proxy.requests, "request", _stub_request)
    return TestClient(sigv4_proxy.app, base_url=PROXY_BASE)


def _sign(access_key: str, secret: str, bucket: str) -> dict[str, str]:
    """Builds a real, fully-signed SigV4 Authorization header for a GET
    ListObjectsV2 against `bucket`, using boto3's own signer. Purely
    local — no network call."""
    session = boto3.Session(aws_access_key_id=access_key, aws_secret_access_key=secret, region_name="us-east-1")
    s3 = session.client("s3", endpoint_url=PROXY_BASE)
    request = AWSRequest(
        method="GET",
        url=f"{PROXY_BASE}/{bucket}?list-type=2",
        headers={"x-amz-content-sha256": "UNSIGNED-PAYLOAD", "host": "localhost:4567"},
    )
    s3._request_signer.sign("ListObjectsV2", request)
    return dict(request.headers.items())


def _error_code(response_text: str) -> str | None:
    return ET.fromstring(response_text).findtext("Code")


def _get(client: TestClient, bucket: str, headers: dict[str, str] | None = None):  # noqa: ANN201
    return client.get(f"/{bucket}?list-type=2", headers=headers or {})


# --- Unit: header parsing (§3.1) ------------------------------------------


def test_well_formed_header_still_parses_to_the_same_parsed_auth_fields() -> None:
    """No regression: a well-formed header parses exactly as it did
    before this brief — the success path for parsing is unchanged."""
    headers = _sign(GENERAL_ACCESS_KEY, GENERAL_SECRET, GENERAL_BUCKET)
    parsed = parse_authorization_header(headers["Authorization"])
    assert parsed == ParsedAuth(
        access_key=GENERAL_ACCESS_KEY,
        date=parsed.date,
        region="us-east-1",
        service="s3",
        signed_headers=parsed.signed_headers,
        signature=parsed.signature,
    )
    assert re.fullmatch(r"\d{8}", parsed.date)
    assert "host" in parsed.signed_headers


def test_absent_and_malformed_headers_now_take_different_paths(client: TestClient) -> None:
    """Previously identical (both flattened to 403 AccessDenied) —
    SPEC_BRIEF7's entire point is that they must now diverge."""
    absent = _get(client, GENERAL_BUCKET)
    malformed = _get(
        client,
        GENERAL_BUCKET,
        headers={"Authorization": f"AWS4-HMAC-SHA256 Credential={GENERAL_ACCESS_KEY}/20260101/us-east-1/s3/aws4_request"},
    )
    assert (absent.status_code, _error_code(absent.text)) != (malformed.status_code, _error_code(malformed.text))


# --- Unit: the denial matrix itself (§3.1), one test per row, hermetic (§3.4) --


def test_row_no_auth_header_at_all_is_403_access_denied(client: TestClient) -> None:
    response = _get(client, GENERAL_BUCKET)
    assert response.status_code == 403
    assert _error_code(response.text) == "AccessDenied"


def test_row_case_m1_malformed_header_is_400_authorization_header_malformed(client: TestClient) -> None:
    """SPEC_BRIEF7 §3.1a, case M1 exactly as specified: the
    AWS4-HMAC-SHA256 algorithm token and a Credential= component are
    present, but SignedHeaders= and Signature= are absent."""
    response = _get(
        client,
        GENERAL_BUCKET,
        headers={"Authorization": f"AWS4-HMAC-SHA256 Credential={GENERAL_ACCESS_KEY}/20260101/us-east-1/s3/aws4_request"},
    )
    assert response.status_code == 400
    assert _error_code(response.text) == "AuthorizationHeaderMalformed"


def test_row_well_formed_header_unknown_access_key_is_403_invalid_access_key_id(client: TestClient) -> None:
    headers = _sign("CYBERGYMBOGUSUSER9999", "some-secret-that-does-not-matter", GENERAL_BUCKET)
    response = _get(client, GENERAL_BUCKET, headers=headers)
    assert response.status_code == 403
    assert _error_code(response.text) == "InvalidAccessKeyId"


def test_row_known_access_key_signature_mismatch_is_403_signature_does_not_match(client: TestClient) -> None:
    headers = _sign(GENERAL_ACCESS_KEY, "a-completely-wrong-secret-value", GENERAL_BUCKET)
    response = _get(client, GENERAL_BUCKET, headers=headers)
    assert response.status_code == 403
    assert _error_code(response.text) == "SignatureDoesNotMatch"


def test_row_valid_signature_bucket_not_allowed_is_403_access_denied(client: TestClient) -> None:
    """The deliberate ambiguity (SPEC_BRIEF7 §3.1): same (403,
    AccessDenied) outcome as the absent-header row, but for a genuinely
    different reason — a valid, known credential that simply isn't
    allowed on this bucket. This is correct and must not be "fixed"."""
    headers = _sign(GENERAL_ACCESS_KEY, GENERAL_SECRET, ADMIN_BUCKET)
    response = _get(client, ADMIN_BUCKET, headers=headers)
    assert response.status_code == 403
    assert _error_code(response.text) == "AccessDenied"


def test_row_authorized_request_is_forwarded_unchanged(client: TestClient) -> None:
    """The success path must behave identically to before this brief:
    still forwarded, still returning the upstream status and body."""
    headers = _sign(GENERAL_ACCESS_KEY, GENERAL_SECRET, GENERAL_BUCKET)
    response = _get(client, GENERAL_BUCKET, headers=headers)
    assert response.status_code == 200
    assert response.content == b"<stub-upstream-ok/>"


# --- Determinism -----------------------------------------------------------


@pytest.mark.parametrize(
    "bucket,headers_factory",
    [
        (GENERAL_BUCKET, lambda: {}),
        (
            GENERAL_BUCKET,
            lambda: {
                "Authorization": f"AWS4-HMAC-SHA256 Credential={GENERAL_ACCESS_KEY}/20260101/us-east-1/s3/aws4_request"
            },
        ),
        (GENERAL_BUCKET, lambda: _sign(GENERAL_ACCESS_KEY, "a-completely-wrong-secret-value", GENERAL_BUCKET)),
    ],
)
def test_same_arm_repeated_yields_the_same_status_and_code(client: TestClient, bucket, headers_factory) -> None:  # noqa: ANN001
    first = _get(client, bucket, headers=headers_factory())
    second = _get(client, bucket, headers=headers_factory())
    assert (first.status_code, _error_code(first.text)) == (second.status_code, _error_code(second.text))


# --- Guard: anti-leak (mechanical) ------------------------------------------


def test_src_kronos_never_references_the_fixture_only_discriminator_header() -> None:
    """FORK-H's DEFAULT (option 1) was taken: AWS-faithful codes only, no
    custom fixture-only discriminator header. This guard must exist and
    pass regardless of which FORK-H option a future change takes — it is
    the mechanical proof that the signal `src/kronos/validate/` will read
    next is one that transfers to a real target, not a lab-only shortcut.
    Mirrors the budget-exemption grep guard in tests/test_cleanup.py."""
    offenders = []
    for path in (REPO_ROOT / "src" / "kronos").rglob("*.py"):
        text = path.read_text()
        if "x-cybergym-deny-reason" in text.lower():
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"src/kronos/ must never reference the fixture-only discriminator header: {offenders}"
