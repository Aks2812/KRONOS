"""Real AWS SigV4 signature verification — recomputes the signature from a
KNOWN secret for the claimed access-key-id and compares it against what
the client sent. A wrong secret produces a genuine cryptographic mismatch;
this is not a presence check on the Authorization header.

Implements the standard AWS Signature Version 4 process directly
(no botocore internals): canonical request -> string to sign -> derived
signing key (HMAC chain) -> signature. Reference:
https://docs.aws.amazon.com/general/latest/gr/sigv4-create-canonical-request.html
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from urllib.parse import quote

_AUTH_HEADER_RE = re.compile(
    r"^AWS4-HMAC-SHA256\s+"
    r"Credential=(?P<access_key>[^/]+)/(?P<date>\d{8})/(?P<region>[^/]+)/(?P<service>[^/]+)/aws4_request,\s*"
    r"SignedHeaders=(?P<signed_headers>[^,]+),\s*"
    r"Signature=(?P<signature>[0-9a-f]{64})$"
)


class MalformedAuthHeader(ValueError):
    """The Authorization header isn't a well-formed SigV4 header at all —
    distinct from a well-formed one with a wrong signature, so callers
    can report "missing/malformed credentials" separately from "signature
    mismatch" (the user's requirement: these must be distinguishable)."""


@dataclass(frozen=True)
class ParsedAuth:
    access_key: str
    date: str
    region: str
    service: str
    signed_headers: list[str]
    signature: str


def parse_authorization_header(auth_header: str) -> ParsedAuth:
    match = _AUTH_HEADER_RE.match(auth_header.strip())
    if not match:
        raise MalformedAuthHeader(f"not a well-formed AWS4-HMAC-SHA256 Authorization header: {auth_header!r}")
    return ParsedAuth(
        access_key=match["access_key"],
        date=match["date"],
        region=match["region"],
        service=match["service"],
        signed_headers=match["signed_headers"].split(";"),
        signature=match["signature"],
    )


def _canonical_uri(path: str) -> str:
    # S3 canonical URI: percent-encode each path segment, keep "/" literal,
    # don't re-encode already-encoded sequences' structure beyond this.
    if not path:
        return "/"
    segments = path.split("/")
    return "/".join(quote(seg, safe="-_.~") for seg in segments)


def _canonical_query_string(query_string: str) -> str:
    if not query_string:
        return ""
    pairs = []
    for part in query_string.split("&"):
        if "=" in part:
            k, _, v = part.partition("=")
        else:
            k, v = part, ""
        pairs.append((quote(k, safe="-_.~"), quote(v, safe="-_.~")))
    pairs.sort()
    return "&".join(f"{k}={v}" for k, v in pairs)


def _canonical_headers(headers: dict[str, str], signed_header_names: list[str]) -> str:
    lower_headers = {k.lower(): v for k, v in headers.items()}
    lines = []
    for name in signed_header_names:
        value = lower_headers.get(name, "")
        collapsed = re.sub(r"\s+", " ", value.strip())
        lines.append(f"{name}:{collapsed}")
    return "\n".join(lines) + "\n"


def _payload_hash(headers: dict[str, str], body: bytes) -> str:
    lower_headers = {k.lower(): v for k, v in headers.items()}
    declared = lower_headers.get("x-amz-content-sha256")
    if declared == "UNSIGNED-PAYLOAD":
        return "UNSIGNED-PAYLOAD"
    if declared:
        return declared
    return hashlib.sha256(body).hexdigest()


def _canonical_request(
    method: str, path: str, query_string: str, headers: dict[str, str], signed_header_names: list[str], body: bytes
) -> str:
    return "\n".join(
        [
            method,
            _canonical_uri(path),
            _canonical_query_string(query_string),
            _canonical_headers(headers, signed_header_names),
            ";".join(signed_header_names),
            _payload_hash(headers, body),
        ]
    )


def _signing_key(secret_access_key: str, date: str, region: str, service: str) -> bytes:
    k_date = hmac.new(f"AWS4{secret_access_key}".encode(), date.encode(), hashlib.sha256).digest()
    k_region = hmac.new(k_date, region.encode(), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service.encode(), hashlib.sha256).digest()
    return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()


def compute_expected_signature(
    *,
    secret_access_key: str,
    method: str,
    path: str,
    query_string: str,
    headers: dict[str, str],
    body: bytes,
    amz_date: str,
    parsed_auth: ParsedAuth,
) -> str:
    """Recomputes what the Authorization header's signature SHOULD be, if
    `secret_access_key` is the real secret for the claimed access key."""
    canonical_request = _canonical_request(
        method, path, query_string, headers, parsed_auth.signed_headers, body
    )
    credential_scope = f"{parsed_auth.date}/{parsed_auth.region}/{parsed_auth.service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    signing_key = _signing_key(secret_access_key, parsed_auth.date, parsed_auth.region, parsed_auth.service)
    return hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()


def verify_signature(
    *,
    secret_access_key: str,
    method: str,
    path: str,
    query_string: str,
    headers: dict[str, str],
    body: bytes,
    amz_date: str,
    parsed_auth: ParsedAuth,
) -> bool:
    """True iff the request's signature matches what it should be for
    `secret_access_key` — a genuine cryptographic comparison, not a
    presence/shape check."""
    expected = compute_expected_signature(
        secret_access_key=secret_access_key,
        method=method,
        path=path,
        query_string=query_string,
        headers=headers,
        body=body,
        amz_date=amz_date,
        parsed_auth=parsed_auth,
    )
    return hmac.compare_digest(expected, parsed_auth.signature)
