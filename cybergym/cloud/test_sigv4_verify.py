"""Proves the SigV4 proxy's signature check is REAL cryptographic
verification, not a presence check (the user's explicit requirement):
a wrong secret for a valid, known access-key-id must produce a genuine
signature MISMATCH, distinguishable from a request with no/malformed
Authorization header at all.

Builds real boto3 requests (so the Authorization header is genuine AWS
SigV4, not hand-crafted), extracts their method/path/headers/body, and
runs them straight through cybergym.cloud.sigv4_verify — no network, no
LocalStack, no proxy process needed.
"""

from __future__ import annotations

import boto3
import pytest
from botocore.awsrequest import AWSRequest

from cybergym.cloud.sigv4_verify import MalformedAuthHeader, parse_authorization_header, verify_signature

ACCESS_KEY = "CYBERGYMGENERALUSER0001"
REAL_SECRET = "cybergym-fixture-general-secret-7f3a9c1e"
WRONG_SECRET = "totally-wrong-secret-value-0000000000000"


def _sign_request(secret: str) -> AWSRequest:
    """Builds a real, fully-signed S3 GET request using boto3's own
    signer with the given secret — the Authorization header this
    produces is exactly what a real boto3 client would send."""
    session = boto3.Session(
        aws_access_key_id=ACCESS_KEY, aws_secret_access_key=secret, region_name="us-east-1"
    )
    client = session.client("s3", endpoint_url="http://localhost:4567")
    request = AWSRequest(
        method="GET",
        url="http://localhost:4567/kronos-cybergym-general?list-type=2",
        headers={"x-amz-content-sha256": "UNSIGNED-PAYLOAD", "host": "localhost:4567"},
    )
    signer = client._request_signer
    signer.sign("ListObjectsV2", request)
    return request


def _as_headers_dict(request: AWSRequest) -> dict[str, str]:
    return {k: v for k, v in request.headers.items()}


def test_correct_secret_verifies() -> None:
    request = _sign_request(REAL_SECRET)
    headers = _as_headers_dict(request)
    parsed = parse_authorization_header(headers["Authorization"])
    assert verify_signature(
        secret_access_key=REAL_SECRET,
        method="GET",
        path="/kronos-cybergym-general",
        query_string="list-type=2",
        headers=headers,
        body=b"",
        amz_date=headers["X-Amz-Date"],
        parsed_auth=parsed,
    )


def test_wrong_secret_produces_genuine_signature_mismatch() -> None:
    """The critical case: the request is signed with ACCESS_KEY (a known,
    valid access-key-id) but the WRONG secret. The Authorization header
    is well-formed (parses fine) — the failure must be a genuine
    cryptographic mismatch against the REAL secret, not a parse error."""
    request = _sign_request(WRONG_SECRET)
    headers = _as_headers_dict(request)
    # Confirm this path is NOT the missing/malformed-header path at all —
    # it parses as a perfectly well-formed SigV4 header.
    parsed = parse_authorization_header(headers["Authorization"])
    assert parsed.access_key == ACCESS_KEY

    # Verifying against the REAL secret must fail — the signature was
    # computed with WRONG_SECRET, so it cannot match what verify_signature
    # recomputes using REAL_SECRET.
    assert not verify_signature(
        secret_access_key=REAL_SECRET,
        method="GET",
        path="/kronos-cybergym-general",
        query_string="list-type=2",
        headers=headers,
        body=b"",
        amz_date=headers["X-Amz-Date"],
        parsed_auth=parsed,
    )


def test_missing_authorization_header_is_a_distinct_failure_mode() -> None:
    """Distinguishable from the wrong-secret case above: no Authorization
    header at all raises MalformedAuthHeader during PARSING, before any
    signature comparison is even attempted — a different failure mode,
    not the same code path as a signature mismatch."""
    with pytest.raises(MalformedAuthHeader):
        parse_authorization_header("")


def test_malformed_authorization_header_is_a_distinct_failure_mode() -> None:
    with pytest.raises(MalformedAuthHeader):
        parse_authorization_header("Bearer not-even-sigv4-shaped")
