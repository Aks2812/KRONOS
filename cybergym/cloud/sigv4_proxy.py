"""The cloud-tier enforcement proxy (FORK resolution, see DECISIONS.md):
LocalStack's free/community tier does not enforce IAM authorization on S3
at all (confirmed empirically — unregistered, made-up credentials get
full access). This proxy sits in front of real LocalStack S3 and is the
ONLY thing that actually decides accept/reject for Chains 2 and 3: it
verifies the request's AWS SigV4 signature for real against
`known_secrets.KNOWN_SECRETS`, checks the claimed access key is allowed
on the target bucket, and only forwards authorized requests to LocalStack.

Honesty boundary (also in cybergym/README.md and ground_truth.yaml): this
is a faithful SigV4 signature check plus a flat allowed-buckets table —
NOT a general AWS IAM policy engine. It proves the chaining logic (does
this key cryptographically open this resource, yes/no); it does not
replicate real IAM's policy language, conditions, or resource ARNs
matching beyond the bucket name.

SPEC_BRIEF7 "CyberGym denial fidelity": each denial condition now emits
the distinct S3 `Error.Code` real AWS would return for it (previously
every denial flattened to 403 `AccessDenied`) — see the matrix in
cybergym/README.md and cybergym/ground_truth.yaml. `Message` text is
never part of the contract; only `(HTTP status, Error.Code)` is.
"""

from __future__ import annotations

import os

import requests
from fastapi import FastAPI, Request, Response

from cybergym.cloud.known_secrets import KNOWN_SECRETS
from cybergym.cloud.sigv4_verify import (
    MalformedAuthHeader,
    is_case_m1_malformed,
    parse_authorization_header,
    verify_signature,
)

LOCALSTACK_URL = os.environ.get("LOCALSTACK_URL", "http://localhost:4566")

app = FastAPI(title="cybergym-sigv4-proxy")


def _s3_error_xml(code: str, message: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<Error><Code>{code}</Code><Message>{message}</Message></Error>"
    )


def _extract_bucket(path: str) -> str | None:
    # Path-style addressing only (self-test forces addressing_style="path")
    # — the first path segment is the bucket name.
    parts = [p for p in path.split("/") if p]
    return parts[0] if parts else None


@app.api_route("/{full_path:path}", methods=["GET", "PUT", "POST", "DELETE", "HEAD"])
async def proxy(full_path: str, request: Request) -> Response:
    headers = dict(request.headers)
    body = await request.body()
    path = "/" + full_path
    query_string = str(request.url.query)

    auth_header = headers.get("authorization", "")
    amz_date = headers.get("x-amz-date", "")

    if not auth_header:
        # No Authorization header at all — matches real AWS for
        # anonymous access to a private resource (SPEC_BRIEF7 §3.1).
        # Deliberately the same Error.Code as the bucket-not-allowed
        # case below; see cybergym/README.md for why that's correct.
        return Response(
            content=_s3_error_xml("AccessDenied", "Missing AWS SigV4 Authorization header"),
            status_code=403,
            media_type="application/xml",
        )

    if is_case_m1_malformed(auth_header):
        # Case M1 ONLY (SPEC_BRIEF7 §3.1a) — real AWS distinguishes a
        # malformed header from an absent one. Other malformed shapes
        # fall through to the generic MalformedAuthHeader handling below,
        # unchanged from before this brief.
        return Response(
            content=_s3_error_xml("AuthorizationHeaderMalformed", "The authorization header you provided is not valid."),
            status_code=400,
            media_type="application/xml",
        )

    try:
        parsed = parse_authorization_header(auth_header)
    except MalformedAuthHeader:
        return Response(
            content=_s3_error_xml("AccessDenied", "Missing or malformed AWS SigV4 Authorization header"),
            status_code=403,
            media_type="application/xml",
        )

    secret_entry = KNOWN_SECRETS.get(parsed.access_key)
    if secret_entry is None:
        return Response(
            content=_s3_error_xml("InvalidAccessKeyId", "Unknown access key"),
            status_code=403,
            media_type="application/xml",
        )

    signature_ok = verify_signature(
        secret_access_key=secret_entry["secret_access_key"],
        method=request.method,
        path=path,
        query_string=query_string,
        headers=headers,
        body=body,
        amz_date=amz_date,
        parsed_auth=parsed,
    )
    if not signature_ok:
        # Genuine cryptographic mismatch — the access key is known, but
        # the signature doesn't match what it should be for that key's
        # real secret (e.g. the caller used the wrong secret).
        return Response(
            content=_s3_error_xml("SignatureDoesNotMatch", "The request signature we calculated does not match the signature you provided."),
            status_code=403,
            media_type="application/xml",
        )

    bucket = _extract_bucket(path)
    if bucket is not None and bucket.startswith("kronos-cybergym-") and bucket not in secret_entry["allowed_buckets"]:
        return Response(
            content=_s3_error_xml("AccessDenied", f"{parsed.access_key} is not authorized to access {bucket}"),
            status_code=403,
            media_type="application/xml",
        )

    # Authorized — forward to real LocalStack S3. LocalStack's own
    # permissiveness (confirmed empirically) means it accepts this
    # regardless of the Authorization header's content, so no re-signing
    # is needed; the enforcement decision has already been made above.
    upstream = requests.request(
        method=request.method,
        url=f"{LOCALSTACK_URL}{path}",
        params=dict(request.query_params),
        headers={k: v for k, v in headers.items() if k.lower() != "host"},
        data=body,
        timeout=30,
    )
    return Response(content=upstream.content, status_code=upstream.status_code, headers=dict(upstream.headers))
