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


def test_naive_window_timestamp_rejected_as_manifest_error_not_typeerror(manifest_factory, signing_keypair):
    """Final review Important #5: a window timestamp with no UTC offset
    used to reach the aware/naive datetime comparison in load_and_verify
    and raise a bare TypeError. A caller catching only ManifestError (as
    this module's whole contract promises) would crash instead of
    getting a clean rejection."""
    _, pub = signing_keypair
    naive = manifest_factory(engagement={
        "window_start": "2026-01-01T00:00:00",  # no offset
        "window_end": "2026-12-31T23:59:59",
    })
    with pytest.raises(ManifestError):
        load_and_verify(naive, pub)
