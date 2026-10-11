from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


@pytest.fixture
def signing_keypair():
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def _deep_merge(base: dict, overrides: dict) -> dict:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@pytest.fixture
def manifest_factory(signing_keypair):
    priv, _ = signing_keypair

    def _make(**overrides) -> str:
        from kronos.manifest import sign_manifest

        now = datetime.now(timezone.utc)
        data = {
            "engagement": {
                "id": "acme-2026",
                "client": "Acme Corp",
                "authorized_by": "Jane CISO",
                "window_start": (now - timedelta(days=1)).isoformat(),
                "window_end": (now + timedelta(days=30)).isoformat(),
                "destructive_allowed": False,
            },
            "scope": {"in_scope": ["*.acme.example.com"], "excluded": []},
        }
        data = _deep_merge(data, overrides)
        return sign_manifest(data, priv)

    return _make


@pytest.fixture
def engagement_graph(tmp_path, manifest_factory, signing_keypair):
    from kronos.graph import EngagementGraph

    _, pub = signing_keypair
    return EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_factory(), pub)
