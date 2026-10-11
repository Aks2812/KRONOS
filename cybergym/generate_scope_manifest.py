"""Generates (or reuses) a dedicated CyberGym test Ed25519 keypair, signs
the lab's scope manifest with it via Brief #1's own `kronos.manifest.
sign_manifest`, and immediately verifies the result with Brief #1's own
`kronos.manifest.load_and_verify` — so this script fails loudly if the
manifest it produces would NOT actually be accepted by KRONOS. Not just
the right YAML shape; a real, re-verifiable signature.

Run from the repo root: `.venv/bin/python cybergym/generate_scope_manifest.py`

Outputs:
  cybergym/.keys/cybergym_signing_key.pem   — PRIVATE key. Gitignored,
                                               never committed. See
                                               cybergym/README.md for where
                                               it lives and why.
  cybergym/scope_manifest_pubkey.pem        — PUBLIC key. Committed.
  cybergym/scope_manifest.yaml              — the signed manifest. Committed.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kronos.manifest import load_and_verify, sign_manifest  # noqa: E402

HERE = Path(__file__).resolve().parent
PRIVATE_KEY_PATH = HERE / ".keys" / "cybergym_signing_key.pem"
PUBLIC_KEY_PATH = HERE / "scope_manifest_pubkey.pem"
MANIFEST_PATH = HERE / "scope_manifest.yaml"

# A 100-year window: this is a standing local test lab, not a dated
# engagement, so there's no real expiry to track — the long window is
# deliberate, not an oversight (logged in DECISIONS.md).
WINDOW_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
WINDOW_END = WINDOW_START + timedelta(days=365 * 100)

MANIFEST_DICT = {
    "engagement": {
        "id": "cybergym-x-instrument-v1",
        "client": "KRONOS self-test (CyberGym X-score measurement lab)",
        "authorized_by": "KRONOS project maintainer (Aks2812)",
        "window_start": WINDOW_START.isoformat(),
        "window_end": WINDOW_END.isoformat(),
        "destructive_allowed": False,
    },
    "scope": {
        "in_scope": [
            "com.kronos.cybergym.*",  # the lab's mobile bundle id
            "localhost*",
            "127.0.0.1*",
            # API_ENDPOINT node ids are full URLs (scheme included) — a
            # bare "localhost*"/"127.0.0.1*" glob never matches
            # "http://localhost:8091..." (fnmatch has no substring
            # matching; it requires the target to START with the
            # pattern's literal prefix). Found empirically running
            # SPEC_BRIEF3's validation pass against this lab: without
            # these, every API_ENDPOINT candidate was (correctly, given
            # the manifest as it stood) scope-gated out, so chain 1 was
            # never attempted at all. Not a scope_guard bug — the guard
            # did exactly what a manifest missing these globs says to do.
            "http://localhost*",
            "http://127.0.0.1*",
            "kronos-cybergym-*",  # bucket-name-shaped CLOUD_RESOURCE ids
            "arn:aws:s3:::kronos-cybergym-*",  # ARN-shaped CLOUD_RESOURCE ids
        ],
        "excluded": [],
    },
}


def main() -> None:
    PRIVATE_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)

    if PRIVATE_KEY_PATH.exists():
        private_key = serialization.load_pem_private_key(PRIVATE_KEY_PATH.read_bytes(), password=None)
        print(f"reusing existing signing key: {PRIVATE_KEY_PATH}")
    else:
        private_key = Ed25519PrivateKey.generate()
        PRIVATE_KEY_PATH.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        print(f"generated new signing key: {PRIVATE_KEY_PATH}")

    public_key = private_key.public_key()
    PUBLIC_KEY_PATH.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    signed_yaml = sign_manifest(MANIFEST_DICT, private_key)
    MANIFEST_PATH.write_text(signed_yaml)

    # The actual requirement: prove Brief #1's own verifier accepts this,
    # not just that the YAML looks right.
    verified = load_and_verify(signed_yaml, public_key)
    assert verified.engagement_id == MANIFEST_DICT["engagement"]["id"]
    print(f"VERIFIED by kronos.manifest.load_and_verify: engagement_id={verified.engagement_id!r}")
    print(f"wrote: {PUBLIC_KEY_PATH}")
    print(f"wrote: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
