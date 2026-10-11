#!/usr/bin/env python3
"""Stands the CyberGym lab up, verifies the scope manifest actually
verifies against Brief #1's own verifier, verifies all 3 planted chains
are genuinely live (correct secret -> accept; wrong secret -> reject),
verifies the chain-3 over-privilege boundary is real (chain-2's
credential must be denied on chain-3's bucket), and tears the lab back
down (SPEC_BRIEF05 "leave nothing running or exposed after teardown").

Run from the repo root: `.venv/bin/python cybergym/selftest.py`
(or `cybergym/selftest.py --no-teardown` to inspect the running lab after).
"""

from __future__ import annotations

import argparse
import base64
import subprocess
import sys
import time
from pathlib import Path

import boto3
import requests
from botocore.config import Config

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from kronos.manifest import load_and_verify  # noqa: E402

from cryptography.hazmat.primitives import serialization  # noqa: E402

API_BASE = "http://localhost:8091"
PROXY_BASE = "http://localhost:4567"

CHAIN1_SECRET = "CYBERGYM_FIXTURE_CHAIN1_API_KEY_4d2f8a91"
CHAIN2_ENC = Path(HERE / "mobile/apk_src/res/values/strings.xml").read_text()


def _extract_resource(xml_text: str, name: str) -> str:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_text)
    for el in root.findall("string"):
        if el.attrib.get("name") == name and el.text is not None:
            return el.text
    raise KeyError(f"resource {name!r} not found")


def s3_client(access_key: str, secret_key: str):
    return boto3.client(
        "s3",
        endpoint_url=PROXY_BASE,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
    )


class Result:
    def __init__(self) -> None:
        self.checks: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

    def all_passed(self) -> bool:
        return all(ok for _, ok, _ in self.checks)


def check_scope_manifest(result: Result) -> None:
    manifest_text = (HERE / "scope_manifest.yaml").read_text()
    pubkey_bytes = (HERE / "scope_manifest_pubkey.pem").read_bytes()
    public_key = serialization.load_pem_public_key(pubkey_bytes)
    try:
        verified = load_and_verify(manifest_text, public_key)
        result.check(
            "scope_manifest.yaml verifies against kronos.manifest.load_and_verify",
            True,
            f"engagement_id={verified.engagement_id!r}",
        )
    except Exception as exc:  # noqa: BLE001
        result.check("scope_manifest.yaml verifies against kronos.manifest.load_and_verify", False, str(exc))


def check_chain1(result: Result) -> None:
    path = _extract_resource(CHAIN2_ENC, "kronos_chain1_endpoint_path")
    r_correct = requests.post(API_BASE + path, headers={"X-Cybergym-Key": CHAIN1_SECRET}, timeout=10)
    result.check("chain-1: correct key accepted (200)", r_correct.status_code == 200, f"got {r_correct.status_code}")

    r_wrong = requests.post(API_BASE + path, headers={"X-Cybergym-Key": "wrong-key-xyz"}, timeout=10)
    result.check("chain-1: wrong key rejected (401)", r_wrong.status_code == 401, f"got {r_wrong.status_code}")


def check_chain2(result: Result) -> tuple[str, str]:
    encoded = _extract_resource(CHAIN2_ENC, "kronos_chain2_creds_enc")
    decoded = base64.b64decode(encoded).decode()
    access_key, _, secret_key = decoded.partition(":")

    client = s3_client(access_key, secret_key)
    try:
        client.list_objects_v2(Bucket="kronos-cybergym-general")
        result.check("chain-2: correct creds accepted on kronos-cybergym-general", True)
    except Exception as exc:  # noqa: BLE001
        result.check("chain-2: correct creds accepted on kronos-cybergym-general", False, str(exc))

    wrong_client = s3_client(access_key, "wrong-secret-entirely")
    try:
        wrong_client.list_objects_v2(Bucket="kronos-cybergym-general")
        result.check("chain-2: wrong secret rejected on kronos-cybergym-general", False, "unexpectedly succeeded")
    except Exception as exc:  # noqa: BLE001
        result.check(
            "chain-2: wrong secret rejected on kronos-cybergym-general",
            "AccessDenied" in str(exc),
            str(exc),
        )
    return access_key, secret_key


def check_chain3(result: Result, chain2_access_key: str, chain2_secret_key: str) -> None:
    part1 = (HERE / "mobile/apk_src/assets/cfg.dat").read_text()
    part2 = _extract_resource(CHAIN2_ENC, "kronos_chain3_secret_part2")
    reassembled = part1 + part2
    access_key, _, secret_key = reassembled.partition(":")

    client = s3_client(access_key, secret_key)
    for bucket in ["kronos-cybergym-general", "kronos-cybergym-admin-secrets"]:
        try:
            client.list_objects_v2(Bucket=bucket)
            result.check(f"chain-3: over-privileged creds accepted on {bucket}", True)
        except Exception as exc:  # noqa: BLE001
            result.check(f"chain-3: over-privileged creds accepted on {bucket}", False, str(exc))

    # The boundary check: chain-2's credential must NOT work on chain-3's
    # bucket — this is what proves the over-privilege is a real,
    # verified relationship, not just two independent buckets.
    boundary_client = s3_client(chain2_access_key, chain2_secret_key)
    try:
        boundary_client.list_objects_v2(Bucket="kronos-cybergym-admin-secrets")
        result.check("chain-3 boundary: chain-2 creds denied on admin bucket", False, "unexpectedly succeeded")
    except Exception as exc:  # noqa: BLE001
        result.check(
            "chain-3 boundary: chain-2 creds denied on admin bucket", "AccessDenied" in str(exc), str(exc)
        )


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], cwd=HERE, check=True)


def wait_for_services(timeout: int = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if (
                requests.get(API_BASE + "/health", timeout=2).status_code == 200
                and requests.get(PROXY_BASE + "/nonexistent-probe", timeout=2).status_code == 403
            ):
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise TimeoutError("lab services did not become ready in time")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-teardown", action="store_true")
    parser.add_argument("--no-standup", action="store_true", help="assume the lab is already up")
    args = parser.parse_args()

    result = Result()
    try:
        if not args.no_standup:
            print("standing up the lab (docker compose up -d --build)...")
            compose("up", "-d", "--build")
            print("waiting for services...")
            wait_for_services()

        check_scope_manifest(result)
        check_chain1(result)
        access_key_2, secret_key_2 = check_chain2(result)
        check_chain3(result, access_key_2, secret_key_2)
    finally:
        if not args.no_teardown and not args.no_standup:
            print("tearing down the lab (docker compose down)...")
            compose("down", "-v")

    print()
    if result.all_passed():
        print(f"ALL {len(result.checks)} CHECKS PASSED")
        return 0
    failed = [name for name, ok, _ in result.checks if not ok]
    print(f"{len(failed)}/{len(result.checks)} CHECKS FAILED: {failed}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
