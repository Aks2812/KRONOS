"""Validator registry keyed by decoded secret-value SHAPE (SPEC_BRIEF3
"VALIDATOR DESIGN"), not by `SECRET.kind` — Brief #2's mobile ingester
only ever tags `kind` as "api_key"/"api_key_obfuscated" (it never
distinguishes a cloud credential pair; see DECISIONS.md), so there is
nothing meaningful to dispatch on in that column yet. Classification here
is purely a function of the decoded value itself and never touches the
graph or the node's stored `kind`.

Unknown shape -> no validator -> caller must leave the secret at
`extracted`, logged, never guessed live (SPEC_BRIEF3 "Extensible: unknown
kinds -> no validator...").
"""

from __future__ import annotations

from typing import Callable, Literal

from kronos.validate.cloud_validator import validate_cloud_credential
from kronos.validate.http_validator import validate_api_token

ValidatorKind = Literal["cloud_credential_pair", "api_token", "unknown"]

# A real AWS-style access-key:secret-key pair: both sides non-trivial, the
# left side long enough to plausibly be an access-key id (CyberGym's own
# fixture ids run 21-23 chars; a short "a:b"-shaped value is far more
# likely to just be an ordinary token that happens to contain a colon).
_MIN_LEFT_LEN = 8
_MIN_RIGHT_LEN = 6


def classify_validator_kind(decoded_value: str) -> ValidatorKind:
    if not decoded_value:
        return "unknown"
    left, sep, right = decoded_value.partition(":")
    if sep and len(left) >= _MIN_LEFT_LEN and len(right) >= _MIN_RIGHT_LEN:
        return "cloud_credential_pair"
    return "api_token"


VALIDATORS: dict[ValidatorKind, Callable[..., object]] = {
    "api_token": validate_api_token,
    "cloud_credential_pair": validate_cloud_credential,
}


def get_validator(kind: ValidatorKind) -> Callable[..., object] | None:
    return VALIDATORS.get(kind)
