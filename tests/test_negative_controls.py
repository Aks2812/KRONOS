"""SPEC_BRIEF8 "Negative-control validation (two-armed proof)" — §5.1's
mandated hermetic tests: the `/health` false positive this brief exists
to close (THE headline test), the invariant that `live=True` is
structurally impossible without `discriminated=True`, the cloud
classification matrix against every one of Brief #7's codes, the
`authenticated_not_authorized` (FORK-M) path, negative-control
derivation, and budget atomicity across a differential.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest
from botocore.exceptions import ClientError

from kronos.budget import BudgetExceeded, BudgetLedger, BudgetLimits
from kronos.evidence import store_evidence
from kronos.graph import EngagementGraph
from kronos.validate.cloud_validator import validate_cloud_credential
from kronos.validate.controls import ArmResult, derive_negative_control, run_differential
from kronos.validate.http_validator import validate_api_token
from kronos.validate.runner import run_validation_pass
from kronos.validate.types import ValidationOutcome

# --------------------------------------------------------------------------
# Graph fixtures (mirrors tests/test_validate_runner.py's pattern)
# --------------------------------------------------------------------------


def _graph_with_secret(tmp_path, manifest_factory, signing_keypair, *, decoded_value: str, in_scope_globs: list[str]):
    _, pub = signing_keypair
    manifest_text = manifest_factory(scope={"in_scope": in_scope_globs, "excluded": []})
    graph = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_text, pub)
    engagement_dir = tmp_path

    info = store_evidence(engagement_dir, decoded_value.encode(), kind="mobile_secret")
    secret_id = f"secret:{info['sha256'][:16]}"

    graph.upsert_node("MOBILE_APP", "com.kronos.lab", {"bundle_id": "com.kronos.lab", "platform": "android", "source": "static"})
    graph.upsert_node(
        "SECRET",
        secret_id,
        {"value_ref": "sha256:" + info["sha256"], "kind": "api_key", "status": "extracted", "source": "static"},
        scope_key="com.kronos.lab",
    )
    graph.upsert_edge("leaks", "com.kronos.lab", "MOBILE_APP", secret_id, "SECRET")
    return graph, engagement_dir, secret_id


def _add_endpoint(graph, url: str) -> None:
    graph.upsert_node("API_ENDPOINT", url, {"source": "static"})
    graph.upsert_edge("references", "com.kronos.lab", "MOBILE_APP", url, "API_ENDPOINT")


def _edge_count(graph, secret_id: str) -> int:
    result = graph.execute(
        "MATCH (s:SECRET {id: $id})-[:authenticates_to]->() RETURN count(*)", {"id": secret_id}
    )
    return result.get_next()[0]


# --------------------------------------------------------------------------
# §5.1.1 — THE headline test: the /health false positive this brief closes
# --------------------------------------------------------------------------


@patch("kronos.validate.http_validator.requests.request")
def test_health_shaped_stub_is_closed_hermetically(mock_request) -> None:
    """A stub that 200s to every request, exactly like CyberGym's real
    `/health` (reproducible against the live range too — see §5.3's
    selftest.py check). The NEW differential must abstain; the OLD
    single-arm logic (kept here only as a documented regression anchor,
    never as production code) would have claimed it live."""
    mock_request.return_value = Mock(status_code=200)

    outcome = validate_api_token("garbage-secret-not-real", "http://localhost:8091/health")

    assert outcome.live is False
    assert outcome.classification == "indiscriminate_target"
    assert outcome.discriminated is False
    assert outcome.evidence == b""

    # Regression anchor: the PRE-BRIEF-8 logic was exactly "first 2xx is
    # proof" — spelled out here, not imported, so it can never silently
    # start passing again if someone reintroduces it elsewhere.
    pre_brief8_would_have_claimed_live = 200 <= mock_request.return_value.status_code < 300
    assert pre_brief8_would_have_claimed_live is True


def test_health_shaped_target_closed_end_to_end_on_the_graph(tmp_path, manifest_factory, signing_keypair) -> None:
    """Same FP, exercised through the full runner/graph path: secret stays
    `extracted`, and critically, no `authenticates_to` edge is written."""
    graph, engagement_dir, secret_id = _graph_with_secret(
        tmp_path, manifest_factory, signing_keypair,
        decoded_value="garbage-secret-not-real", in_scope_globs=["http://localhost:8091*"],
    )
    _add_endpoint(graph, "http://localhost:8091/health")

    with patch("kronos.validate.http_validator.requests.request") as mock_request:
        mock_request.return_value = Mock(status_code=200)
        run_validation_pass(graph, engagement_dir)

    secret = graph.get_node("SECRET", secret_id)
    assert secret["status"] == "extracted"
    assert _edge_count(graph, secret_id) == 0


# --------------------------------------------------------------------------
# §5.1.2 — true positives still pass
# --------------------------------------------------------------------------


def test_true_positive_http_still_reaches_reachable_with_edge(tmp_path, manifest_factory, signing_keypair) -> None:
    graph, engagement_dir, secret_id = _graph_with_secret(
        tmp_path, manifest_factory, signing_keypair,
        decoded_value="the-real-secret", in_scope_globs=["http://localhost:8091*"],
    )
    _add_endpoint(graph, "http://localhost:8091/admin")

    def fake_request(method, url, headers, timeout):  # noqa: ANN001
        is_real = "the-real-secret" in headers.get("Authorization", "")
        return Mock(status_code=200 if is_real else 403)

    with patch("kronos.validate.http_validator.requests.request", side_effect=fake_request):
        run_validation_pass(graph, engagement_dir)

    secret = graph.get_node("SECRET", secret_id)
    assert secret["status"] == "reachable"
    assert _edge_count(graph, secret_id) == 1


# --------------------------------------------------------------------------
# §5.1.3 — invariant across the WHOLE classification matrix, not one case
# --------------------------------------------------------------------------


def _all_http_arm_combinations() -> list[tuple[ArmResult, ArmResult]]:
    statuses = [
        ArmResult(label="X", success=True, status_code=200),
        ArmResult(label="X", success=False, status_code=403),
        ArmResult(label="X", success=False, transport_error=True),
    ]
    combos = []
    for a in statuses:
        for b in statuses:
            combos.append(
                (
                    ArmResult(label="A_canonical", success=a.success, status_code=a.status_code, transport_error=a.transport_error),
                    ArmResult(label="B_negative_control", success=b.success, status_code=b.status_code, transport_error=b.transport_error),
                )
            )
    return combos


@pytest.mark.parametrize("arms", _all_http_arm_combinations())
def test_http_invariant_live_implies_discriminated_over_every_combination(arms) -> None:
    result = run_differential(list(arms), kind="http")
    assert not (result.live and not result.discriminated)
    if result.live:
        assert result.classification == "live_discriminated"


def _all_cloud_arm_combinations() -> list[tuple[ArmResult, ArmResult, ArmResult]]:
    codes = [None, "AccessDenied", "SignatureDoesNotMatch", "InvalidAccessKeyId", "AuthorizationHeaderMalformed"]
    combos = []
    for a_code in codes:
        for b_code in codes:
            for c_code in codes:
                a = ArmResult(label="A_canonical", success=a_code is None, error_code=a_code, status_code=403 if a_code else 200)
                b = ArmResult(label="B_bad_secret", success=b_code is None, error_code=b_code, status_code=403 if b_code else 200)
                c = ArmResult(label="C_unknown_key", success=c_code is None, error_code=c_code, status_code=403 if c_code else 200)
                combos.append((a, b, c))
    return combos


@pytest.mark.parametrize("arms", _all_cloud_arm_combinations())
def test_cloud_invariant_live_implies_discriminated_over_every_combination(arms) -> None:
    result = run_differential(list(arms), kind="cloud")
    assert not (result.live and not result.discriminated)
    if result.live:
        assert result.classification == "live_discriminated"


@pytest.mark.parametrize(
    "live,discriminated,classification",
    [
        (True, False, "live_discriminated"),
        (True, True, "indiscriminate_target"),
        (True, False, "not_live"),
    ],
)
def test_validation_outcome_structurally_rejects_live_without_proper_discrimination(
    live, discriminated, classification
) -> None:
    """Not a convention — `ValidationOutcome.__post_init__` itself refuses
    to construct an invalid combination, for ANY caller, forever."""
    with pytest.raises(ValueError):
        ValidationOutcome(
            live=live, evidence=b"x" if live else b"", detail="", classification=classification, discriminated=discriminated
        )


def test_validation_outcome_accepts_the_one_valid_live_combination() -> None:
    outcome = ValidationOutcome(
        live=True, evidence=b"proof", detail="", classification="live_discriminated", discriminated=True
    )
    assert outcome.live is True


# --------------------------------------------------------------------------
# §5.1.4 — cloud matrix parametrized over Brief #7's five codes
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a_code,b_code,c_code,expected",
    [
        # Brief #7's five rows, read as a three-arm differential:
        (None, "SignatureDoesNotMatch", "InvalidAccessKeyId", "live_discriminated"),  # A succeeds
        ("AccessDenied", "SignatureDoesNotMatch", "InvalidAccessKeyId", "authenticated_not_authorized"),
        ("AccessDenied", "AccessDenied", "InvalidAccessKeyId", "inconclusive"),
        (None, None, None, "indiscriminate_target"),  # A and B both succeed
        ("AuthorizationHeaderMalformed", "SignatureDoesNotMatch", "InvalidAccessKeyId", "self_request_malformed"),
        ("InvalidAccessKeyId", "InvalidAccessKeyId", "InvalidAccessKeyId", "not_live"),  # A itself unknown-key
    ],
)
def test_cloud_classification_matrix_matches_brief7_codes(a_code, b_code, c_code, expected) -> None:
    a = ArmResult(label="A_canonical", success=a_code is None, error_code=a_code, status_code=None if a_code is None else 403)
    b = ArmResult(label="B_bad_secret", success=b_code is None, error_code=b_code, status_code=None if b_code is None else 403)
    c = ArmResult(label="C_unknown_key", success=c_code is None, error_code=c_code, status_code=None if c_code is None else 403)
    result = run_differential([a, b, c], kind="cloud")
    assert result.classification == expected


# --------------------------------------------------------------------------
# §5.1.5 — authenticated_not_authorized: validated only, no edge, no reachable
# --------------------------------------------------------------------------


def test_authenticated_not_authorized_reaches_validated_only_no_edge(
    tmp_path, manifest_factory, signing_keypair
) -> None:
    graph, engagement_dir, secret_id = _graph_with_secret(
        tmp_path, manifest_factory, signing_keypair,
        decoded_value="CYBERGYMGENERALUSER0001:cybergym-fixture-general-secret-7f3a9c1e",
        in_scope_globs=["arn:aws:s3:::*"],
    )
    graph.upsert_node(
        "CLOUD_RESOURCE", "kronos-cybergym-admin-secrets",
        {"resource_type": "s3_bucket", "provider": "aws", "source": "test"},
        scope_key="arn:aws:s3:::kronos-cybergym-admin-secrets",
    )

    outcome = ValidationOutcome(
        live=False,
        evidence=b'{"classification": "authenticated_not_authorized"}',
        detail="proven real, denied on this bucket",
        classification="authenticated_not_authorized",
        discriminated=True,
    )
    with patch("kronos.validate.cloud_validator.validate_cloud_credential", return_value=outcome):
        run_validation_pass(graph, engagement_dir, cloud_proxy_endpoint="http://localhost:4567")

    secret = graph.get_node("SECRET", secret_id)
    assert secret["status"] == "validated"
    assert _edge_count(graph, secret_id) == 0


# --------------------------------------------------------------------------
# §5.1.6 — control derivation: deterministic, shape-preserving, never real
# --------------------------------------------------------------------------


def test_derive_negative_control_is_deterministic_across_calls() -> None:
    a = derive_negative_control("CYBERGYMGENERALUSER0001", target_id="bucket-x", kind="cloud_access_key")
    b = derive_negative_control("CYBERGYMGENERALUSER0001", target_id="bucket-x", kind="cloud_access_key")
    assert a == b


def test_derive_negative_control_differs_by_target_id_and_kind() -> None:
    base = derive_negative_control("CYBERGYMGENERALUSER0001", target_id="bucket-x", kind="cloud_access_key")
    other_target = derive_negative_control("CYBERGYMGENERALUSER0001", target_id="bucket-y", kind="cloud_access_key")
    other_kind = derive_negative_control("CYBERGYMGENERALUSER0001", target_id="bucket-x", kind="cloud_secret_key")
    assert base != other_target
    assert base != other_kind


@pytest.mark.parametrize(
    "real_value",
    [
        "CYBERGYMGENERALUSER0001",
        "cybergym-fixture-general-secret-7f3a9c1e",
        "CYBERGYMADMINUSER0001",
        "cybergym-fixture-admin-secret-b82d4f60",
        "CYBERGYM_FIXTURE_CHAIN1_API_KEY_4d2f8a91",
    ],
)
def test_derive_negative_control_never_equals_the_real_value_and_preserves_shape(real_value) -> None:
    control = derive_negative_control(real_value, target_id="some-target", kind="api_token")
    assert control != real_value
    assert len(control) == len(real_value)
    for original_ch, control_ch in zip(real_value, control):
        if original_ch.isdigit():
            assert control_ch.isdigit()
        elif original_ch.isupper():
            assert control_ch.isupper()
        elif original_ch.islower():
            assert control_ch.islower()
        else:
            assert control_ch == original_ch


_KNOWN_FIXTURE_SECRETS = [
    "CYBERGYMGENERALUSER0001",
    "cybergym-fixture-general-secret-7f3a9c1e",
    "CYBERGYMADMINUSER0001",
    "cybergym-fixture-admin-secret-b82d4f60",
]


@pytest.mark.parametrize("real_value", _KNOWN_FIXTURE_SECRETS)
def test_derive_negative_control_never_collides_with_another_known_real_secret(real_value) -> None:
    control = derive_negative_control(real_value, target_id="t", kind="cloud_secret_key")
    others = [v for v in _KNOWN_FIXTURE_SECRETS if v != real_value]
    assert control not in others


def test_derive_negative_control_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        derive_negative_control("", target_id="t", kind="api_token")


# --------------------------------------------------------------------------
# §5.1.7 — budget atomicity: never a half-run differential
# --------------------------------------------------------------------------


def test_budget_exceeded_between_candidates_never_mid_differential(
    tmp_path, manifest_factory, signing_keypair
) -> None:
    """A ledger with room for exactly one candidate's cloud differential
    (3 arms) but not two (6) must stop BETWEEN candidates — the first
    candidate's outcome is either fully recorded (edge + evidence) or the
    second candidate's validator is never even called; there is no
    partial arm record either way."""
    graph, engagement_dir, secret_id = _graph_with_secret(
        tmp_path, manifest_factory, signing_keypair,
        decoded_value="CYBERGYMGENERALUSER0001:cybergym-fixture-general-secret-7f3a9c1e",
        in_scope_globs=["arn:aws:s3:::*"],
    )
    graph.upsert_node(
        "CLOUD_RESOURCE", "bucket-a", {"resource_type": "s3_bucket", "provider": "aws", "source": "test"},
        scope_key="arn:aws:s3:::bucket-a",
    )
    graph.upsert_node(
        "CLOUD_RESOURCE", "bucket-b", {"resource_type": "s3_bucket", "provider": "aws", "source": "test"},
        scope_key="arn:aws:s3:::bucket-b",
    )

    live_outcome = ValidationOutcome(
        live=True, evidence=b"proof", detail="", classification="live_discriminated", discriminated=True
    )
    ledger = BudgetLedger(BudgetLimits(validation_attempts=10, tool_invocations=3, wall_clock_seconds=None))

    with patch("kronos.validate.cloud_validator.validate_cloud_credential", return_value=live_outcome) as mock_validate:
        with pytest.raises(BudgetExceeded):
            run_validation_pass(graph, engagement_dir, cloud_proxy_endpoint="http://localhost:4567", budget=ledger)

    # Exactly one candidate's differential ran to completion before the
    # second one's charge raised — never a half-called validator.
    assert mock_validate.call_count == 1
    secret = graph.get_node("SECRET", secret_id)
    assert secret["status"] == "reachable"
    assert _edge_count(graph, secret_id) == 1


# --------------------------------------------------------------------------
# No secret value ever reaches evidence/detail/control_outcome
# --------------------------------------------------------------------------


@patch("kronos.validate.cloud_validator.boto3.client")
def test_cloud_validator_evidence_and_control_outcome_never_contain_a_secret_value(mock_boto_client) -> None:
    mock_a, mock_b, mock_c = MagicMock(), MagicMock(), MagicMock()
    mock_b.list_objects_v2.side_effect = ClientError(
        {"Error": {"Code": "SignatureDoesNotMatch"}, "ResponseMetadata": {"HTTPStatusCode": 403}}, "ListObjectsV2"
    )
    mock_c.list_objects_v2.side_effect = ClientError(
        {"Error": {"Code": "InvalidAccessKeyId"}, "ResponseMetadata": {"HTTPStatusCode": 403}}, "ListObjectsV2"
    )
    mock_boto_client.side_effect = [mock_a, mock_b, mock_c]

    outcome = validate_cloud_credential(
        "CYBERGYMGENERALUSER0001:cybergym-fixture-general-secret-7f3a9c1e",
        "kronos-cybergym-general",
        "http://localhost:4567",
    )

    haystack = outcome.evidence + outcome.detail.encode() + outcome.control_outcome.encode()
    assert b"cybergym-fixture-general-secret-7f3a9c1e" not in haystack
    assert b"CYBERGYMGENERALUSER0001" not in haystack
