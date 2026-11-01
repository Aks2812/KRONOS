"""Signed engagement scope manifest: load, verify, sign.

The manifest is the ONLY authorization object (SPEC.md "SCOPE MANIFEST
FORMAT"). `load_and_verify` is the sole entry point that turns raw YAML
into a trusted `ScopeManifest`: it rejects anything unsigned, tampered,
malformed, or outside its authorization window. Nothing downstream ever
constructs a `ScopeManifest` by any other path in production use.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


class ManifestError(Exception):
    """Raised for any unsigned, tampered, malformed, or expired manifest."""


# SPEC_BRIEF29 §4.4 / O1: ceiling for WatchdogPolicy.confirm_window_seconds.
WATCHDOG_CONFIRM_WINDOW_MAX = 300

# Strict numeric types: no bool, no str coercion (SPEC_BRIEF29 §4.1 fail-closed).
_NonNegInt = Annotated[int, Field(strict=True, ge=0)]
_NonNegFloat = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
_PosInt = Annotated[int, Field(strict=True, gt=0)]


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("datetime must include a UTC offset")
    return value


class _Strict(BaseModel):
    # extra="forbid": unknown keys (e.g. a raw credential field) are rejected.
    model_config = ConfigDict(extra="forbid")


class UnattendedBudget(_Strict):
    validation_attempts: _NonNegInt
    tool_invocations: _NonNegInt
    wall_clock_seconds: _NonNegFloat
    llm_tokens: _NonNegInt
    llm_cost_usd: _NonNegFloat


class UnattendedAuthorization(_Strict):
    action_class: Literal["A", "B", "C"]
    target: str
    target_node_type: str
    valid_from: datetime
    valid_until: datetime
    destructive: bool = Field(default=False, strict=True)

    @field_validator("valid_from", "valid_until")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @model_validator(mode="after")
    def _window_ordered(self) -> "UnattendedAuthorization":
        if not self.valid_until > self.valid_from:
            raise ValueError("valid_until must be > valid_from")
        return self


class ExfilSimulation(_Strict):
    allowed: bool = Field(default=False, strict=True)
    byte_budget: _NonNegInt = 0
    dataset_marker: str | None = None


class WatchdogPolicy(_Strict):
    may_auto_stop: bool = Field(default=False, strict=True)
    confirm_window_seconds: _NonNegInt = 0

    @model_validator(mode="after")
    def _window_rule(self) -> "WatchdogPolicy":
        if self.may_auto_stop and not (1 <= self.confirm_window_seconds <= WATCHDOG_CONFIRM_WINDOW_MAX):
            raise ValueError(f"may_auto_stop requires 1 <= confirm_window_seconds <= {WATCHDOG_CONFIRM_WINDOW_MAX}")
        return self


class AutonomyEnvelope(_Strict):
    mode_max: Literal["calm", "beast"] = "calm"
    unattended_authorizations: list[UnattendedAuthorization]
    max_unattended_duration_seconds: _PosInt
    max_unattended_budget: UnattendedBudget
    exfil_simulation: ExfilSimulation | None = None
    watchdog: WatchdogPolicy | None = None


class AmendmentRef(_Strict):
    manifest_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    effective_at: datetime

    @field_validator("effective_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _require_aware(value)


class ScopeManifest(BaseModel):
    engagement_id: str
    client: str
    authorized_by: str
    window_start: datetime
    window_end: datetime
    destructive_allowed: bool = False
    in_scope: list[str]
    excluded: list[str]
    autonomy: AutonomyEnvelope | None = None
    amends: AmendmentRef | None = None

    @field_validator("window_start", "window_end")
    @classmethod
    def _require_timezone_aware(cls, value: datetime) -> datetime:
        # Final review Important #5: a naive datetime (no UTC offset in
        # the YAML) used to reach load_and_verify's `window_start <= now
        # <= window_end` comparison and raise a bare TypeError instead of
        # ManifestError — a caller catching only ManifestError would
        # crash. Reject naive datetimes explicitly here instead of
        # guessing a timezone for them; this still surfaces as
        # ManifestError (load_and_verify wraps ValidationError).
        if value.tzinfo is None:
            raise ValueError("window_start/window_end must include a UTC offset (e.g. ...+00:00 or ...Z)")
        return value


class VerifiedManifest(ScopeManifest):
    """A `ScopeManifest` that `load_and_verify` produced after signature
    verification (SPEC_BRIEF29 §5). `canonical_content` is the verified,
    signature-stripped, pre-`_flatten` canonical bytes; `manifest_id` is
    its sha256, so it carries no `_flatten` defaults. A bare parsed
    `ScopeManifest` is not a `VerifiedManifest`."""

    canonical_content: bytes
    manifest_id: str

    @model_validator(mode="after")
    def _bound_to_canonical_content(self) -> "VerifiedManifest":
        # Construction guard (§5): manifest_id must be sha256(canonical_content)
        # and the fields must be exactly what that content parses to, so a
        # hand-built instance with forged content/id/fields is rejected.
        if self.manifest_id != hashlib.sha256(self.canonical_content).hexdigest():
            raise ValueError("manifest_id does not match sha256(canonical_content)")
        try:
            loaded = yaml.safe_load(self.canonical_content)
            expected = ScopeManifest(**_flatten(loaded))
        except Exception as exc:
            raise ValueError("canonical_content does not parse to a manifest") from exc
        for name in ScopeManifest.model_fields:
            if getattr(self, name) != getattr(expected, name):
                raise ValueError(f"field {name!r} does not match canonical_content")
        return self


def compute_manifest_id(verified: "VerifiedManifest") -> str:
    """sha256 hex over the verified canonical content (SPEC_BRIEF29 §5)."""
    if not isinstance(verified, VerifiedManifest):
        raise TypeError("compute_manifest_id requires a VerifiedManifest")
    return hashlib.sha256(verified.canonical_content).hexdigest()


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
    optional = {k: raw[k] for k in ("autonomy", "amends") if k in raw}
    return {
        **optional,
        "engagement_id": engagement.get("id"),
        "client": engagement.get("client"),
        "authorized_by": engagement.get("authorized_by"),
        "window_start": engagement.get("window_start"),
        "window_end": engagement.get("window_end"),
        "destructive_allowed": engagement.get("destructive_allowed", False),
        "in_scope": scope.get("in_scope", []),
        "excluded": scope.get("excluded", []),
    }


def load_and_verify(yaml_text: str, public_key: Ed25519PublicKey) -> VerifiedManifest:
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
        parsed = ScopeManifest(**_flatten(content))
        manifest = VerifiedManifest(
            **dict(parsed),
            canonical_content=canon,
            manifest_id=hashlib.sha256(canon).hexdigest(),
        )
    except ValidationError as exc:
        raise ManifestError(f"invalid manifest schema: {exc}") from exc

    now = datetime.now(timezone.utc)
    if not (manifest.window_start <= now <= manifest.window_end):
        raise ManifestError("outside authorization window")

    return manifest
