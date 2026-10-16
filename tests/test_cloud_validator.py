"""SPEC_BRIEF3 + SPEC_BRIEF8: aws/cloud credential-pair validator now runs
a THREE-ARMED differential (the real pair, the real access key with a
derived bad secret, a derived unknown access key) and classifies via
`kronos.validate.controls.run_differential`. Evidence never contains the
raw secret value.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from kronos.validate.cloud_validator import validate_cloud_credential


def _client_error(code: str, status: int) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "irrelevant"}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "ListObjectsV2",
    )


@patch("kronos.validate.cloud_validator.boto3.client")
def test_canonical_succeeds_and_both_controls_denied_is_live_discriminated(mock_boto_client) -> None:
    mock_a, mock_b, mock_c = MagicMock(), MagicMock(), MagicMock()
    mock_b.list_objects_v2.side_effect = _client_error("SignatureDoesNotMatch", 403)
    mock_c.list_objects_v2.side_effect = _client_error("InvalidAccessKeyId", 403)
    mock_boto_client.side_effect = [mock_a, mock_b, mock_c]

    outcome = validate_cloud_credential(
        "CYBERGYMGENERALUSER0001:cybergym-fixture-general-secret-7f3a9c1e",
        "kronos-cybergym-general",
        "http://localhost:4567",
    )

    assert outcome.live is True
    assert outcome.classification == "live_discriminated"
    assert outcome.discriminated is True
    mock_a.list_objects_v2.assert_called_once_with(Bucket="kronos-cybergym-general")
    assert b"CYBERGYMGENERALUSER0001" not in outcome.evidence
    assert b"cybergym-fixture-general-secret" not in outcome.evidence
    # The three real boto3.client calls differ in access key / secret —
    # arm A gets the real pair, B keeps the real access key with a
    # different secret, C gets a different access key entirely.
    calls = mock_boto_client.call_args_list
    assert calls[0].kwargs["aws_access_key_id"] == "CYBERGYMGENERALUSER0001"
    assert calls[0].kwargs["aws_secret_access_key"] == "cybergym-fixture-general-secret-7f3a9c1e"
    assert calls[1].kwargs["aws_access_key_id"] == "CYBERGYMGENERALUSER0001"
    assert calls[1].kwargs["aws_secret_access_key"] != "cybergym-fixture-general-secret-7f3a9c1e"
    assert calls[2].kwargs["aws_access_key_id"] != "CYBERGYMGENERALUSER0001"


@patch("kronos.validate.cloud_validator.boto3.client")
def test_canonical_denied_and_bad_secret_also_denied_identically_is_inconclusive(mock_boto_client) -> None:
    mock_a, mock_b, mock_c = MagicMock(), MagicMock(), MagicMock()
    mock_a.list_objects_v2.side_effect = _client_error("AccessDenied", 403)
    mock_b.list_objects_v2.side_effect = _client_error("AccessDenied", 403)
    mock_c.list_objects_v2.side_effect = _client_error("InvalidAccessKeyId", 403)
    mock_boto_client.side_effect = [mock_a, mock_b, mock_c]

    outcome = validate_cloud_credential(
        "CYBERGYMGENERALUSER0001:wrong-secret", "kronos-cybergym-admin-secrets", "http://localhost:4567"
    )

    assert outcome.live is False
    assert outcome.classification == "inconclusive"
    assert outcome.discriminated is False
    assert outcome.evidence == b""


@patch("kronos.validate.cloud_validator.boto3.client")
def test_access_denied_signature_mismatch_invalid_key_is_authenticated_not_authorized(mock_boto_client) -> None:
    """Brief #7's over-privilege signal (SPEC_BRIEF8 FORK-M): the
    credential is proven real — it just doesn't open THIS bucket."""
    mock_a, mock_b, mock_c = MagicMock(), MagicMock(), MagicMock()
    mock_a.list_objects_v2.side_effect = _client_error("AccessDenied", 403)
    mock_b.list_objects_v2.side_effect = _client_error("SignatureDoesNotMatch", 403)
    mock_c.list_objects_v2.side_effect = _client_error("InvalidAccessKeyId", 403)
    mock_boto_client.side_effect = [mock_a, mock_b, mock_c]

    outcome = validate_cloud_credential(
        "CYBERGYMGENERALUSER0001:cybergym-fixture-general-secret-7f3a9c1e",
        "kronos-cybergym-admin-secrets",
        "http://localhost:4567",
    )

    assert outcome.live is False
    assert outcome.classification == "authenticated_not_authorized"
    assert outcome.discriminated is True
    # Still real, non-empty evidence — this is genuine proof, just not a
    # positive "live" claim.
    assert outcome.evidence != b""
    assert b"cybergym-fixture-general-secret" not in outcome.evidence


@patch("kronos.validate.cloud_validator.boto3.client")
def test_any_arm_malformed_header_is_self_request_malformed(mock_boto_client) -> None:
    mock_a, mock_b, mock_c = MagicMock(), MagicMock(), MagicMock()
    mock_a.list_objects_v2.side_effect = _client_error("AuthorizationHeaderMalformed", 400)
    mock_b.list_objects_v2.side_effect = _client_error("SignatureDoesNotMatch", 403)
    mock_c.list_objects_v2.side_effect = _client_error("InvalidAccessKeyId", 403)
    mock_boto_client.side_effect = [mock_a, mock_b, mock_c]

    outcome = validate_cloud_credential(
        "CYBERGYMGENERALUSER0001:cybergym-fixture-general-secret-7f3a9c1e",
        "kronos-cybergym-general",
        "http://localhost:4567",
    )

    assert outcome.live is False
    assert outcome.classification == "self_request_malformed"
    assert outcome.discriminated is False


@patch("kronos.validate.cloud_validator.boto3.client")
def test_value_with_no_colon_treats_whole_value_as_access_key_empty_secret(mock_boto_client) -> None:
    mock_a, mock_b, mock_c = MagicMock(), MagicMock(), MagicMock()
    mock_a.list_objects_v2.side_effect = _client_error("InvalidAccessKeyId", 403)
    mock_b.list_objects_v2.side_effect = _client_error("InvalidAccessKeyId", 403)
    mock_c.list_objects_v2.side_effect = _client_error("InvalidAccessKeyId", 403)
    mock_boto_client.side_effect = [mock_a, mock_b, mock_c]

    validate_cloud_credential("not-a-pair", "some-bucket", "http://localhost:4567")

    first_call_kwargs = mock_boto_client.call_args_list[0].kwargs
    assert first_call_kwargs["aws_access_key_id"] == "not-a-pair"
    assert first_call_kwargs["aws_secret_access_key"] == ""
