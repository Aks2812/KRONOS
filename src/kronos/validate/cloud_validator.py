"""aws / cloud credential-pair validator (SPEC_BRIEF3 "VALIDATOR DESIGN",
SPEC_BRIEF8 "Negative-control validation").

A READ/AUTH-CHECK operation only: real `boto3` S3 `ListObjectsV2` calls,
never a crash on a dead/denied credential.

SPEC_BRIEF8 closes Hole 2 (§0): collapsing every `ClientError` to
`live=False` could never tell *no-credential* from *wrong-credential*
from *valid-but-unauthorized*. On Brief #7's AWS-faithful error codes, a
signed request that comes back `AccessDenied` means the signature
*verified* and policy denied the resource — that is positive evidence the
credential is real, but it is only safe to trust if the target actually
discriminates. This validator always runs three arms (SPEC_BRIEF8 §3.4):
the real credential, the real access key with a derived bad secret, and a
derived unknown access key — and hands all three to
`kronos.validate.controls.run_differential`, the one chokepoint that
decides the classification.
"""

from __future__ import annotations

import json

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from kronos.validate.controls import ArmResult, derive_negative_control, run_differential
from kronos.validate.types import ValidationOutcome

_TIMEOUT_DEFAULT = 10


def _attempt(
    access_key: str,
    secret_key: str,
    bucket_name: str,
    proxy_endpoint: str,
    region: str,
    timeout: int,
    label: str,
) -> ArmResult:
    client = boto3.client(
        "s3",
        endpoint_url=proxy_endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(
            s3={"addressing_style": "path"},
            signature_version="s3v4",
            connect_timeout=timeout,
            read_timeout=timeout,
        ),
    )
    try:
        client.list_objects_v2(Bucket=bucket_name)
        return ArmResult(label=label, success=True)
    except ClientError as exc:
        error = exc.response.get("Error", {})
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return ArmResult(label=label, success=False, status_code=status, error_code=error.get("Code"))
    except BotoCoreError:
        return ArmResult(label=label, success=False, transport_error=True)


def _arm_summary(arm: ArmResult) -> dict:
    return {
        "success": arm.success,
        "status_code": arm.status_code,
        "error_code": arm.error_code,
        "transport_error": arm.transport_error,
    }


def validate_cloud_credential(
    secret_value: str,
    bucket_name: str,
    proxy_endpoint: str,
    *,
    region: str = "us-east-1",
    timeout: int = _TIMEOUT_DEFAULT,
) -> ValidationOutcome:
    access_key, _, secret_key = secret_value.partition(":")

    arm_a = _attempt(access_key, secret_key, bucket_name, proxy_endpoint, region, timeout, "A_canonical")

    bad_secret = derive_negative_control(secret_key or access_key, target_id=bucket_name, kind="cloud_secret_key")
    arm_b = _attempt(access_key, bad_secret, bucket_name, proxy_endpoint, region, timeout, "B_bad_secret")

    bad_access_key = derive_negative_control(access_key, target_id=bucket_name, kind="cloud_access_key")
    arm_c = _attempt(bad_access_key, secret_key, bucket_name, proxy_endpoint, region, timeout, "C_unknown_key")

    result = run_differential([arm_a, arm_b, arm_c], kind="cloud")

    evidence = b""
    if result.live or result.classification == "authenticated_not_authorized":
        # A positive claim (live) or a proven-real-but-denied credential
        # MUST carry all three arms as evidence — never a single arm's
        # status alone (SPEC_BRIEF8 §3.5). Never the secret values.
        evidence = json.dumps(
            {
                "method": "ListObjectsV2",
                "bucket": bucket_name,
                "proxy_endpoint": proxy_endpoint,
                "classification": result.classification,
                "arm_a": _arm_summary(arm_a),
                "arm_b": _arm_summary(arm_b),
                "arm_c": _arm_summary(arm_c),
            }
        ).encode()

    return ValidationOutcome(
        live=result.live,
        evidence=evidence,
        detail=f"ListObjectsV2 on {bucket_name} via {proxy_endpoint}: {result.detail}",
        classification=result.classification,
        control_outcome=result.control_outcome,
        discriminated=result.discriminated,
    )
