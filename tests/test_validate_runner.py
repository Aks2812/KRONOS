"""SPEC_BRIEF3's five mandated invariant tests, run against a real
EngagementGraph (no network — the validator callables themselves are
patched; the SCOPE-GATE behavior under test is `run_validation_pass`'s
own logic, not the validators).
"""

from __future__ import annotations

from unittest.mock import patch

from kronos.evidence import store_evidence
from kronos.graph import EngagementGraph
from kronos.lifecycle import derive_confidence
from kronos.validate.runner import run_validation_pass
from kronos.validate.types import ValidationOutcome


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


def test_live_in_scope_secret_reaches_reachable_with_evidence_and_edge(
    tmp_path, manifest_factory, signing_keypair
) -> None:
    graph, engagement_dir, secret_id = _graph_with_secret(
        tmp_path, manifest_factory, signing_keypair,
        decoded_value="plain-bearer-token", in_scope_globs=["http://localhost:8091*"],
    )
    _add_endpoint(graph, "http://localhost:8091")

    with patch("kronos.validate.http_validator.validate_api_token") as mock_validate:
        mock_validate.return_value = ValidationOutcome(live=True, evidence=b"proof", detail="200")
        run_validation_pass(graph, engagement_dir)

    secret = graph.get_node("SECRET", secret_id)
    assert secret["status"] == "reachable"
    assert secret["confidence"] == derive_confidence("secret", "reachable", True)

    result = graph.execute(
        "MATCH (s:SECRET {id: $id})-[:authenticates_to]->(ep:API_ENDPOINT) RETURN ep.id", {"id": secret_id}
    )
    assert result.has_next()


def test_live_but_out_of_scope_target_never_exceeds_validated_and_is_never_actioned(
    tmp_path, manifest_factory, signing_keypair
) -> None:
    graph, engagement_dir, secret_id = _graph_with_secret(
        tmp_path, manifest_factory, signing_keypair,
        decoded_value="plain-bearer-token", in_scope_globs=["http://nothing-matches-this*"],
    )
    _add_endpoint(graph, "http://localhost:8091")

    with patch("kronos.validate.http_validator.validate_api_token") as mock_validate:
        mock_validate.return_value = ValidationOutcome(live=True, evidence=b"proof", detail="200")
        run_validation_pass(graph, engagement_dir)

    secret = graph.get_node("SECRET", secret_id)
    assert secret["status"] == "extracted"  # never even attempted, so never exceeds validated
    assert secret["status"] != "reachable"

    result = graph.execute(
        "MATCH (s:SECRET {id: $id})-[:authenticates_to]->() RETURN count(*)", {"id": secret_id}
    )
    assert result.get_next()[0] == 0


def test_dead_secret_stays_extracted_no_edge_no_evidence(tmp_path, manifest_factory, signing_keypair) -> None:
    graph, engagement_dir, secret_id = _graph_with_secret(
        tmp_path, manifest_factory, signing_keypair,
        decoded_value="wrong-token", in_scope_globs=["http://localhost:8091*"],
    )
    _add_endpoint(graph, "http://localhost:8091")

    with patch("kronos.validate.http_validator.validate_api_token") as mock_validate:
        mock_validate.return_value = ValidationOutcome(live=False, evidence=b"", detail="401")
        run_validation_pass(graph, engagement_dir)

    secret = graph.get_node("SECRET", secret_id)
    assert secret["status"] == "extracted"

    result = graph.execute(
        "MATCH (s:SECRET {id: $id})-[:authenticates_to]->() RETURN count(*)", {"id": secret_id}
    )
    assert result.get_next()[0] == 0
    evidence_result = graph.execute(
        "MATCH (e:EVIDENCE)-[:evidences]->(s:SECRET {id: $id}) RETURN count(*)", {"id": secret_id}
    )
    assert evidence_result.get_next()[0] == 0


def test_credential_is_never_sent_to_an_out_of_scope_target(tmp_path, manifest_factory, signing_keypair) -> None:
    """The mandated transport-spy proof: the validator callable itself
    must never be invoked for an out-of-scope candidate — not just that
    the final status happens to look right."""
    graph, engagement_dir, secret_id = _graph_with_secret(
        tmp_path, manifest_factory, signing_keypair,
        decoded_value="plain-bearer-token", in_scope_globs=["http://nothing-matches-this*"],
    )
    _add_endpoint(graph, "http://localhost:8091")

    with patch("kronos.validate.http_validator.validate_api_token") as mock_validate:
        run_validation_pass(graph, engagement_dir)
        mock_validate.assert_not_called()


def test_out_of_scope_skip_does_not_also_skip_an_in_scope_candidate_of_the_same_secret(
    tmp_path, manifest_factory, signing_keypair
) -> None:
    graph, engagement_dir, secret_id = _graph_with_secret(
        tmp_path, manifest_factory, signing_keypair,
        decoded_value="plain-bearer-token", in_scope_globs=["http://in-scope.example.com*"],
    )
    _add_endpoint(graph, "http://out-of-scope.example.com")
    _add_endpoint(graph, "http://in-scope.example.com")

    def fake_validate(secret_value, endpoint_url, **kwargs):
        return ValidationOutcome(live=(endpoint_url == "http://in-scope.example.com"), evidence=b"proof", detail="")

    with patch("kronos.validate.http_validator.validate_api_token", side_effect=fake_validate) as mock_validate:
        run_validation_pass(graph, engagement_dir)

    called_urls = {call.args[1] for call in mock_validate.call_args_list}
    assert called_urls == {"http://in-scope.example.com"}

    secret = graph.get_node("SECRET", secret_id)
    assert secret["status"] == "reachable"


def test_confidence_after_reachable_matches_derived_cap_no_inflation(
    tmp_path, manifest_factory, signing_keypair
) -> None:
    graph, engagement_dir, secret_id = _graph_with_secret(
        tmp_path, manifest_factory, signing_keypair,
        decoded_value="plain-bearer-token", in_scope_globs=["http://localhost:8091*"],
    )
    _add_endpoint(graph, "http://localhost:8091")

    with patch("kronos.validate.http_validator.validate_api_token") as mock_validate:
        mock_validate.return_value = ValidationOutcome(live=True, evidence=b"proof", detail="200")
        run_validation_pass(graph, engagement_dir)

    secret = graph.get_node("SECRET", secret_id)
    assert secret["confidence"] == 9  # derive_confidence("secret", "reachable", has_evidence=True)


def test_rerunning_validation_pass_on_already_reachable_secret_is_a_safe_noop(
    tmp_path, manifest_factory, signing_keypair
) -> None:
    graph, engagement_dir, secret_id = _graph_with_secret(
        tmp_path, manifest_factory, signing_keypair,
        decoded_value="plain-bearer-token", in_scope_globs=["http://localhost:8091*"],
    )
    _add_endpoint(graph, "http://localhost:8091")

    with patch("kronos.validate.http_validator.validate_api_token") as mock_validate:
        mock_validate.return_value = ValidationOutcome(live=True, evidence=b"proof", detail="200")
        run_validation_pass(graph, engagement_dir)
        run_validation_pass(graph, engagement_dir)  # secret is already extracted->reachable; loop only considers "extracted" secrets

    secret = graph.get_node("SECRET", secret_id)
    assert secret["status"] == "reachable"


def test_unknown_shaped_decoded_secret_is_skipped_without_crashing(
    tmp_path, manifest_factory, signing_keypair
) -> None:
    graph, engagement_dir, secret_id = _graph_with_secret(
        tmp_path, manifest_factory, signing_keypair, decoded_value="", in_scope_globs=["http://localhost:8091*"]
    )
    _add_endpoint(graph, "http://localhost:8091")

    run_validation_pass(graph, engagement_dir)  # must not raise

    secret = graph.get_node("SECRET", secret_id)
    assert secret["status"] == "extracted"


def test_api_token_secret_never_dispatched_to_the_cloud_validator_even_with_cloud_candidates(
    tmp_path, manifest_factory, signing_keypair
) -> None:
    """Review-focus regression: find_candidate_targets_for_secret returns
    BOTH API_ENDPOINT and CLOUD_RESOURCE candidates for every secret
    (candidates.py tries every known CLOUD_RESOURCE regardless of kind).
    An api_token-classified secret must only ever be dispatched to
    validate_api_token, never validate_cloud_credential, even when an
    in-scope CLOUD_RESOURCE candidate exists in the same engagement —
    caught empirically running the real CyberGym e2e proof, where this
    crashed with a TypeError before the fix."""
    graph, engagement_dir, secret_id = _graph_with_secret(
        tmp_path, manifest_factory, signing_keypair,
        decoded_value="plain-bearer-token", in_scope_globs=["http://localhost:8091*", "arn:aws:s3:::*"],
    )
    _add_endpoint(graph, "http://localhost:8091")
    graph.upsert_node(
        "CLOUD_RESOURCE", "some-bucket", {"resource_type": "s3_bucket", "provider": "aws", "source": "test"},
        scope_key="arn:aws:s3:::some-bucket",
    )

    with patch("kronos.validate.http_validator.validate_api_token") as mock_http, \
         patch("kronos.validate.cloud_validator.validate_cloud_credential") as mock_cloud:
        mock_http.return_value = ValidationOutcome(live=True, evidence=b"proof", detail="200")
        run_validation_pass(graph, engagement_dir, cloud_proxy_endpoint="http://localhost:4567")

    mock_cloud.assert_not_called()
    mock_http.assert_called_once()
