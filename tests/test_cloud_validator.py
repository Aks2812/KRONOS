"""SPEC_BRIEF3: aws/cloud credential-pair validator is a READ/AUTH-CHECK
only (one ListObjectsV2 call), success = live, AccessDenied/any
botocore error = not live, never a crash. Evidence never contains the
raw secret value.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from kronos.validate.cloud_validator import validate_cloud_credential


@patch("kronos.validate.cloud_validator.boto3.client")
def test_correct_pair_splits_on_first_colon_and_succeeds(mock_boto_client) -> None:
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3

    outcome = validate_cloud_credential(
        "CYBERGYMGENERALUSER0001:cybergym-fixture-general-secret-7f3a9c1e",
        "kronos-cybergym-general",
        "http://localhost:4567",
    )

    assert outcome.live is True
    _, kwargs = mock_boto_client.call_args
    assert kwargs["aws_access_key_id"] == "CYBERGYMGENERALUSER0001"
    assert kwargs["aws_secret_access_key"] == "cybergym-fixture-general-secret-7f3a9c1e"
    mock_s3.list_objects_v2.assert_called_once_with(Bucket="kronos-cybergym-general")
    assert b"CYBERGYMGENERALUSER0001" not in outcome.evidence
    assert b"cybergym-fixture-general-secret" not in outcome.evidence


@patch("kronos.validate.cloud_validator.boto3.client")
def test_access_denied_is_dead_not_a_crash(mock_boto_client) -> None:
    mock_s3 = MagicMock()
    mock_s3.list_objects_v2.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "ListObjectsV2"
    )
    mock_boto_client.return_value = mock_s3

    outcome = validate_cloud_credential(
        "CYBERGYMGENERALUSER0001:wrong-secret", "kronos-cybergym-admin-secrets", "http://localhost:4567"
    )

    assert outcome.live is False
    assert outcome.evidence == b""


@patch("kronos.validate.cloud_validator.boto3.client")
def test_value_with_no_colon_treats_whole_value_as_access_key_empty_secret(mock_boto_client) -> None:
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3

    validate_cloud_credential("not-a-pair", "some-bucket", "http://localhost:4567")

    _, kwargs = mock_boto_client.call_args
    assert kwargs["aws_access_key_id"] == "not-a-pair"
    assert kwargs["aws_secret_access_key"] == ""
