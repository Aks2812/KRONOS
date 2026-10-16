"""SPEC_BRIEF3 + SPEC_BRIEF8: api_key/token/bearer validator now runs a
TWO-ARMED differential (the real secret, then a derived negative
control) and never a crash, including never on a transport error.
`live=True` only when the canonical arm succeeds AND the negative
control is rejected — a single 2xx is no longer proof on its own
(SPEC_BRIEF8 closes exactly this hole; see test_negative_controls.py for
the `/health`-shaped headline regression test).
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import requests

from kronos.validate.http_validator import validate_api_token


def _response(status_code: int) -> Mock:
    resp = Mock()
    resp.status_code = status_code
    return resp


@patch("kronos.validate.http_validator.requests.request")
def test_canonical_2xx_and_control_rejected_is_live_discriminated(mock_request) -> None:
    # Arm A (canonical): 200 on the first header tried (Authorization),
    # so arm A stops there. Arm B (negative control) falls back across
    # BOTH header variants (Authorization -> 401, X-Api-Key -> 403), same
    # as the pre-brief-8 fallback loop, and is rejected on every one.
    mock_request.side_effect = [_response(200), _response(401), _response(403)]
    outcome = validate_api_token("secret-value", "http://localhost:8091/x")
    assert outcome.live is True
    assert outcome.classification == "live_discriminated"
    assert outcome.discriminated is True
    assert b"live_discriminated" in outcome.evidence
    # Never the secret or the derived control value anywhere in evidence.
    assert b"secret-value" not in outcome.evidence
    first_call_kwargs = mock_request.call_args_list[0].kwargs
    assert first_call_kwargs["headers"]["Authorization"] == "Bearer secret-value"


@patch("kronos.validate.http_validator.requests.request")
def test_canonical_2xx_but_control_also_2xx_is_indiscriminate_target(mock_request) -> None:
    # THE /health case: everything gets a 200, including the fake credential.
    mock_request.return_value = _response(200)
    outcome = validate_api_token("secret-value", "http://localhost:8091/health")
    assert outcome.live is False
    assert outcome.classification == "indiscriminate_target"
    assert outcome.discriminated is False
    assert outcome.evidence == b""


@patch("kronos.validate.http_validator.requests.request")
def test_falls_back_to_next_header_when_first_is_not_2xx(mock_request) -> None:
    # Arm A: Authorization->401, X-Api-Key->200 (succeeds on 2nd header).
    # Arm B (negative control): both headers rejected.
    mock_request.side_effect = [_response(401), _response(200), _response(401), _response(403)]
    outcome = validate_api_token("secret-value", "http://localhost:8091/x")
    assert outcome.live is True
    assert outcome.classification == "live_discriminated"
    assert mock_request.call_count == 4


@patch("kronos.validate.http_validator.requests.request")
def test_all_header_variants_non_2xx_is_not_live(mock_request) -> None:
    mock_request.return_value = _response(401)
    outcome = validate_api_token("wrong-value", "http://localhost:8091/x")
    assert outcome.live is False
    assert outcome.classification == "not_live"
    assert outcome.evidence == b""


@patch("kronos.validate.http_validator.requests.request")
def test_explicit_header_name_override_is_honored_without_fallback(mock_request) -> None:
    # Arm A: 200. Arm B (control, same explicit header): 401.
    mock_request.side_effect = [_response(200), _response(401)]
    outcome = validate_api_token(
        "CYBERGYM_FIXTURE_CHAIN1_API_KEY_4d2f8a91",
        "http://localhost:8091/internal/v1/admin/export",
        header_name="X-Cybergym-Key",
        method="POST",
    )
    assert outcome.live is True
    assert mock_request.call_count == 2
    args, kwargs = mock_request.call_args_list[0]
    assert args[0] == "POST"
    assert kwargs["headers"] == {"X-Cybergym-Key": "CYBERGYM_FIXTURE_CHAIN1_API_KEY_4d2f8a91"}
    # The control arm must use a DIFFERENT value under the same header.
    control_kwargs = mock_request.call_args_list[1].kwargs
    assert control_kwargs["headers"]["X-Cybergym-Key"] != "CYBERGYM_FIXTURE_CHAIN1_API_KEY_4d2f8a91"


@patch("kronos.validate.http_validator.requests.request")
def test_transport_error_on_both_arms_is_inconclusive_not_a_crash(mock_request) -> None:
    mock_request.side_effect = requests.ConnectionError("refused")
    outcome = validate_api_token("secret-value", "http://localhost:9999/x")
    assert outcome.live is False
    assert outcome.classification == "inconclusive"


@patch("kronos.validate.http_validator.requests.request")
def test_canonical_transport_error_is_not_live(mock_request) -> None:
    # Arm A: transport error throughout. Arm B: a real (non-2xx) response —
    # the two arms are NOT both transport errors, so this is "not_live",
    # not "inconclusive".
    mock_request.side_effect = [requests.ConnectionError("refused"), _response(401)]
    outcome = validate_api_token("secret-value", "http://localhost:9999/x", header_name="Authorization")
    assert outcome.live is False
    assert outcome.classification == "not_live"
