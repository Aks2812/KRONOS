"""SPEC_BRIEF3: api_key/token/bearer validator is a READ/AUTH-CHECK only
(one HTTP request per header variant), 2xx = live, anything else
(including a transport error) = not live, never a crash.
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
def test_first_header_variant_returning_2xx_is_live(mock_request) -> None:
    mock_request.return_value = _response(200)
    outcome = validate_api_token("secret-value", "http://localhost:8091/x")
    assert outcome.live is True
    assert b"Authorization" in outcome.evidence
    # Default Authorization attempt must be sent as a Bearer token.
    _, kwargs = mock_request.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer secret-value"


@patch("kronos.validate.http_validator.requests.request")
def test_falls_back_to_next_header_when_first_is_not_2xx(mock_request) -> None:
    mock_request.side_effect = [_response(401), _response(200)]
    outcome = validate_api_token("secret-value", "http://localhost:8091/x")
    assert outcome.live is True
    assert mock_request.call_count == 2
    _, kwargs = mock_request.call_args
    assert kwargs["headers"]["X-Api-Key"] == "secret-value"


@patch("kronos.validate.http_validator.requests.request")
def test_all_header_variants_non_2xx_is_dead(mock_request) -> None:
    mock_request.return_value = _response(401)
    outcome = validate_api_token("wrong-value", "http://localhost:8091/x")
    assert outcome.live is False
    assert outcome.evidence == b""


@patch("kronos.validate.http_validator.requests.request")
def test_explicit_header_name_override_is_honored_without_fallback(mock_request) -> None:
    mock_request.return_value = _response(200)
    outcome = validate_api_token(
        "CYBERGYM_FIXTURE_CHAIN1_API_KEY_4d2f8a91",
        "http://localhost:8091/internal/v1/admin/export",
        header_name="X-Cybergym-Key",
        method="POST",
    )
    assert outcome.live is True
    assert mock_request.call_count == 1
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert kwargs["headers"] == {"X-Cybergym-Key": "CYBERGYM_FIXTURE_CHAIN1_API_KEY_4d2f8a91"}


@patch("kronos.validate.http_validator.requests.request")
def test_transport_error_counts_as_dead_not_a_crash(mock_request) -> None:
    mock_request.side_effect = requests.ConnectionError("refused")
    outcome = validate_api_token("secret-value", "http://localhost:9999/x")
    assert outcome.live is False
