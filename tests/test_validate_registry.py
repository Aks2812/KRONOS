"""SPEC_BRIEF3 "VALIDATOR DESIGN": kind classification is a pure
function of the decoded secret VALUE's shape (Brief #2 never tags
SECRET.kind beyond "api_key"/"api_key_obfuscated" — see DECISIONS.md),
never a guess based on anything else, and never raises on garbage input.
"""

from __future__ import annotations

from kronos.validate.registry import classify_validator_kind, get_validator


def test_aws_shaped_pair_classifies_as_cloud_credential_pair() -> None:
    assert (
        classify_validator_kind("CYBERGYMGENERALUSER0001:cybergym-fixture-general-secret-7f3a9c1e")
        == "cloud_credential_pair"
    )


def test_bare_bearer_token_classifies_as_api_token() -> None:
    assert classify_validator_kind("CYBERGYM_FIXTURE_CHAIN1_API_KEY_4d2f8a91") == "api_token"


def test_short_left_side_is_not_treated_as_a_credential_pair() -> None:
    # A single colon alone isn't enough to call it a cloud credential pair
    # — the left side must be long enough to plausibly be an access-key id.
    assert classify_validator_kind("a:b") == "api_token"


def test_empty_value_classifies_as_unknown() -> None:
    assert classify_validator_kind("") == "unknown"


def test_get_validator_for_unknown_kind_returns_none() -> None:
    assert get_validator("unknown") is None


def test_get_validator_returns_callables_for_known_kinds() -> None:
    assert callable(get_validator("api_token"))
    assert callable(get_validator("cloud_credential_pair"))
