"""api_key / token / bearer validator (SPEC_BRIEF3 "VALIDATOR DESIGN").

A READ/AUTH-CHECK operation only: one authenticated HTTP request per
header variant tried, 2xx = live, anything else (including a transport
error) = not live. Never raises on a dead target — a closed port or a
timeout is a completely normal "not live" outcome here, not a crash.
"""

from __future__ import annotations

import json

import requests

from kronos.validate.types import ValidationOutcome

_DEFAULT_HEADER_CANDIDATES = ("Authorization", "X-Api-Key")
_TIMEOUT_DEFAULT = 10


def validate_api_token(
    secret_value: str,
    endpoint_url: str,
    *,
    header_name: str | None = None,
    method: str = "GET",
    timeout: int = _TIMEOUT_DEFAULT,
) -> ValidationOutcome:
    headers_to_try = [header_name] if header_name else list(_DEFAULT_HEADER_CANDIDATES)

    for header in headers_to_try:
        value = f"Bearer {secret_value}" if header == "Authorization" and header_name is None else secret_value
        try:
            response = requests.request(method, endpoint_url, headers={header: value}, timeout=timeout)
        except requests.RequestException as exc:
            detail = f"{method} {endpoint_url} header={header}: transport error {exc}"
            continue
        if 200 <= response.status_code < 300:
            evidence = json.dumps(
                {
                    "method": method,
                    "url": endpoint_url,
                    "header_tried": header,
                    "status_code": response.status_code,
                }
            ).encode()
            return ValidationOutcome(
                live=True, evidence=evidence, detail=f"{header} -> {response.status_code}"
            )
        detail = f"{method} {endpoint_url} header={header}: status {response.status_code}"

    return ValidationOutcome(live=False, evidence=b"", detail=detail)
