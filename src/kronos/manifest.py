"""Signed engagement scope manifest: load, verify, sign.

The manifest is the ONLY authorization object (SPEC.md "SCOPE MANIFEST
FORMAT"). `load_and_verify` is the sole entry point that turns raw YAML
into a trusted `ScopeManifest`: it rejects anything unsigned, tampered,
malformed, or outside its authorization window. Nothing downstream ever
constructs a `ScopeManifest` by any other path in production use.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, ValidationError


class ManifestError(Exception):
    """Raised for any unsigned, tampered, malformed, or expired manifest."""


class ScopeManifest(BaseModel):
    engagement_id: str
    client: str
    authorized_by: str
    window_start: datetime
    window_end: datetime
    destructive_allowed: bool = False
    in_scope: list[str]
    excluded: list[str]


def canonicalize(data: dict[str, Any]) -> bytes:
    """Deterministic byte representation signed over / verified against.

    `data` must be the `{"engagement": {...}, "scope": {...}}` content
    only — no `signature` key. Sorted keys make the output independent of
    dict insertion order, so the same logical manifest always canonicalizes
    identically regardless of how it was constructed.
    """
    return yaml.safe_dump(data, sort_keys=True, default_flow_style=False).encode("utf-8")


def sign_manifest(manifest_dict: dict[str, Any], private_key: Ed25519PrivateKey) -> str:
    """Sign `manifest_dict` and return the full YAML text, signature included."""
    canon = canonicalize(manifest_dict)
    signature = base64.b64encode(private_key.sign(canon)).decode("ascii")
    signed = {**manifest_dict, "signature": signature}
    return yaml.safe_dump(signed, sort_keys=True, default_flow_style=False)


def _flatten(raw: dict[str, Any]) -> dict[str, Any]:
    """Map the nested `engagement:`/`scope:` YAML shape onto ScopeManifest's fields."""
    engagement = raw.get("engagement") or {}
    scope = raw.get("scope") or {}
    return {
        "engagement_id": engagement.get("id"),
        "client": engagement.get("client"),
        "authorized_by": engagement.get("authorized_by"),
        "window_start": engagement.get("window_start"),
        "window_end": engagement.get("window_end"),
        "destructive_allowed": engagement.get("destructive_allowed", False),
        "in_scope": scope.get("in_scope", []),
        "excluded": scope.get("excluded", []),
    }


def load_and_verify(yaml_text: str, public_key: Ed25519PublicKey) -> ScopeManifest:
    """Reject unsigned/invalid manifests; reject ones outside their window.

    Raises `ManifestError` on any of: malformed YAML, missing/empty
    signature, invalid signature (tampered content or wrong key), a
    schema the manifest doesn't satisfy, or a current time outside
    [window_start, window_end].
    """
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ManifestError("malformed manifest YAML") from exc

    if not isinstance(raw, dict):
        raise ManifestError("malformed manifest YAML")

    signature = raw.get("signature")
    if not signature or not isinstance(signature, str):
        raise ManifestError("missing signature")

    content = {k: v for k, v in raw.items() if k != "signature"}
    canon = canonicalize(content)
    try:
        public_key.verify(base64.b64decode(signature), canon)
    except (InvalidSignature, ValueError) as exc:
        raise ManifestError("invalid signature") from exc

    try:
        manifest = ScopeManifest(**_flatten(content))
    except ValidationError as exc:
        raise ManifestError(f"invalid manifest schema: {exc}") from exc

    now = datetime.now(timezone.utc)
    if not (manifest.window_start <= now <= manifest.window_end):
        raise ManifestError("outside authorization window")

    return manifest
