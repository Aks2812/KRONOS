"""api_key / token / bearer validator (SPEC_BRIEF3 "VALIDATOR DESIGN",
SPEC_BRIEF8 "Negative-control validation").

A READ/AUTH-CHECK operation only: real HTTP requests, never a crash on a
dead target — a closed port or a timeout is a completely normal "not
live" outcome here, not an exception.

SPEC_BRIEF8 closes Hole 1 (§0): a single 2xx used to be treated as proof
on its own. It is not — an endpoint that 200s to *everything* (CyberGym's
own `/health`, with no auth required at all) would have been reported
live under the old single-arm logic. This validator now always runs a
second, negative-control arm (SPEC_BRIEF8 §3.3) with a derived,
guaranteed-invalid credential of the same shape, and hands both arms to
`kronos.validate.controls.run_differential` — the one chokepoint that
decides whether the target actually discriminates.
"""

from __future__ import annotations

import json

import requests

from kronos.validate.controls import ArmResult, derive_negative_control, run_differential
from kronos.validate.types import ValidationOutcome

_DEFAULT_HEADER_CANDIDATES = ("Authorization", "X-Api-Key")
_TIMEOUT_DEFAULT = 10


def _header_value(header: str, value: str, header_name: str | None) -> str:
    return f"Bearer {value}" if header == "Authorization" and header_name is None else value


def _try_headers(
    value: str,
    endpoint_url: str,
    headers_to_try: list[str],
    header_name: str | None,
    method: str,
    timeout: int,
    label: str,
) -> ArmResult:
    """Tries every header variant for `value`, exactly as the pre-brief-8
    single-arm loop did, but returns the outcome as an `ArmResult` instead
    of deciding `live` itself — classification is `controls.run_differential`'s
    job alone now."""
    any_response = False
    last_status: int | None = None
    for header in headers_to_try:
        header_specific_value = _header_value(header, value, header_name)
        try:
            response = requests.request(method, endpoint_url, headers={header: header_specific_value}, timeout=timeout)
        except requests.RequestException:
            continue
        any_response = True
        last_status = response.status_code
        if 200 <= response.status_code < 300:
            return ArmResult(label=label, success=True, status_code=response.status_code)
    if not any_response:
        return ArmResult(label=label, success=False, transport_error=True)
    return ArmResult(label=label, success=False, status_code=last_status)


def validate_api_token(
    secret_value: str,
    endpoint_url: str,
    *,
    header_name: str | None = None,
    method: str = "GET",
    timeout: int = _TIMEOUT_DEFAULT,
) -> ValidationOutcome:
    headers_to_try = [header_name] if header_name else list(_DEFAULT_HEADER_CANDIDATES)

    arm_a = _try_headers(secret_value, endpoint_url, headers_to_try, header_name, method, timeout, "A_canonical")

    control_value = derive_negative_control(secret_value, target_id=endpoint_url, kind="api_token")
    arm_b = _try_headers(
        control_value, endpoint_url, headers_to_try, header_name, method, timeout, "B_negative_control"
    )

    result = run_differential([arm_a, arm_b], kind="http")

    evidence = b""
    if result.live:
        # A positive claim's evidence MUST contain both arms — the
        # differential IS the proof, never a single arm's status alone
        # (SPEC_BRIEF8 §3.5). Never the secret or the derived control.
        evidence = json.dumps(
            {
                "method": method,
                "url": endpoint_url,
                "classification": result.classification,
                "arm_a": {"success": arm_a.success, "status_code": arm_a.status_code},
                "arm_b": {
                    "success": arm_b.success,
                    "status_code": arm_b.status_code,
                    "transport_error": arm_b.transport_error,
                },
            }
        ).encode()

    return ValidationOutcome(
        live=result.live,
        evidence=evidence,
        detail=f"{method} {endpoint_url}: {result.detail}",
        classification=result.classification,
        control_outcome=result.control_outcome,
        discriminated=result.discriminated,
    )
