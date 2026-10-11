from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kronos.manifest import ManifestError, load_and_verify


def test_valid_manifest_loads(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    yaml_text = manifest_factory()
    m = load_and_verify(yaml_text, pub)
    assert m.engagement_id == "acme-2026"
    assert m.in_scope == ["*.acme.example.com"]


def test_unsigned_manifest_rejected(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    yaml_text = manifest_factory().replace("signature:", "signature: # tampered\nsignature_x:")
    with pytest.raises(ManifestError):
        load_and_verify(yaml_text, pub)


def test_tampered_content_rejected(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    yaml_text = manifest_factory().replace("Acme Corp", "Evil Corp")
    with pytest.raises(ManifestError):
        load_and_verify(yaml_text, pub)


def test_expired_window_rejected(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    now = datetime.now(timezone.utc)
    yaml_text = manifest_factory(engagement={
        "window_start": (now - timedelta(days=10)).isoformat(),
        "window_end": (now - timedelta(days=1)).isoformat(),
    })
    with pytest.raises(ManifestError):
        load_and_verify(yaml_text, pub)


def test_malformed_yaml_rejected(signing_keypair):
    _, pub = signing_keypair
    with pytest.raises(ManifestError):
        load_and_verify("not: valid: yaml: [", pub)


def test_wrong_public_key_rejected(manifest_factory):
    yaml_text = manifest_factory()
    wrong_pub = Ed25519PrivateKey.generate().public_key()
    with pytest.raises(ManifestError):
        load_and_verify(yaml_text, wrong_pub)
