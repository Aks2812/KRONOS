#!/usr/bin/env bash
# Creates the lab's two S3 buckets in real LocalStack. Run as a one-shot
# docker-compose service after LocalStack is healthy — see
# docker-compose.yml's "init-buckets" service. No IAM users are created
# here: LocalStack's free tier doesn't enforce IAM authorization anyway
# (confirmed empirically, see DECISIONS.md), so the sigv4-proxy owns the
# ENTIRE access-control decision via known_secrets.py instead.
set -euo pipefail

: "${AWS_ENDPOINT_URL:=http://localstack:4566}"
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1

aws --endpoint-url "$AWS_ENDPOINT_URL" s3 mb s3://kronos-cybergym-general
aws --endpoint-url "$AWS_ENDPOINT_URL" s3 mb s3://kronos-cybergym-admin-secrets

# A real object in each bucket, so a ListObjectsV2/GetObject the self-test
# runs has something non-empty to actually prove it reached — not just an
# empty bucket that happens to list successfully either way.
echo "kronos-cybergym-general marker" > /tmp/general-marker.txt
echo "kronos-cybergym-admin-secrets marker" > /tmp/admin-marker.txt
aws --endpoint-url "$AWS_ENDPOINT_URL" s3 cp /tmp/general-marker.txt s3://kronos-cybergym-general/marker.txt
aws --endpoint-url "$AWS_ENDPOINT_URL" s3 cp /tmp/admin-marker.txt s3://kronos-cybergym-admin-secrets/marker.txt

echo "buckets provisioned"
