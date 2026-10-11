"""aws / cloud credential-pair validator (SPEC_BRIEF3 "VALIDATOR DESIGN").

A READ/AUTH-CHECK operation only: a real `boto3` S3 `ListObjectsV2` call
against `bucket_name` via `proxy_endpoint` (honors the SigV4 proxy the
CyberGym range uses, or any other S3-compatible endpoint). Success = live.
Never raises on a dead/denied credential — that's a normal "not live"
outcome, not a crash.
"""

from __future__ import annotations

import json

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from kronos.validate.types import ValidationOutcome

_TIMEOUT_DEFAULT = 10


def validate_cloud_credential(
    secret_value: str,
    bucket_name: str,
    proxy_endpoint: str,
    *,
    region: str = "us-east-1",
    timeout: int = _TIMEOUT_DEFAULT,
) -> ValidationOutcome:
    access_key, _, secret_key = secret_value.partition(":")

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
        live = True
        detail = f"ListObjectsV2 on {bucket_name} via {proxy_endpoint}: 200"
    except (ClientError, BotoCoreError) as exc:
        live = False
        detail = f"ListObjectsV2 on {bucket_name} via {proxy_endpoint}: {exc}"

    evidence = (
        json.dumps(
            {
                "method": "ListObjectsV2",
                "bucket": bucket_name,
                "proxy_endpoint": proxy_endpoint,
                "live": live,
                "detail": detail,
            }
        ).encode()
        if live
        else b""
    )
    return ValidationOutcome(live=live, evidence=evidence, detail=detail)
