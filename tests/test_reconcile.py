"""SPEC_BRIEF4's acceptance tests (§4) for the reconciliation/dedup pass,
plus the two guardrail-diff checks (§4 test 8) and the pipeline-invariant
proof (§4 test 6) run generically (CyberGym's own live run is the
docker-backed proof of the same invariant; this test proves it without a
live range so it holds in plain CI too).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

import kronos
from kronos.evidence import attach_evidence, store_evidence
from kronos.graph import EngagementGraph
from kronos.lifecycle import advance_secret_status
from kronos.reconcile import run_reconciliation_pass
from kronos.validate.runner import run_validation_pass
from kronos.validate.types import ValidationOutcome


def _graph(tmp_path, manifest_factory, signing_keypair, **manifest_overrides):
    _, pub = signing_keypair
    manifest_text = manifest_factory(**manifest_overrides)
    return EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_text, pub)


def _secret_with_material(graph, engagement_dir, node_id, material: bytes, *, kind="api_key", status="extracted"):
    info = store_evidence(engagement_dir, material, kind="mobile_secret")
    graph.upsert_node(
        "SECRET", node_id,
        {"value_ref": "sha256:" + info["sha256"], "kind": kind, "status": status, "source": "test"},
    )


# --- §4 test 1: SECRET dedup ------------------------------------------------

def test_secret_dedup_merges_same_normalized_material_different_source(tmp_path, manifest_factory, signing_keypair):
    g = _graph(tmp_path, manifest_factory, signing_keypair)
    engagement_dir = tmp_path

    # Same normalized material ("shared-fixture-secret"), different raw
    # bytes (one whitespace-padded) so the two secrets get different
    # value_ref hashes and different ids, exactly like two independent
    # extractors finding the "same" secret would.
    _secret_with_material(g, engagement_dir, "secret:aaa", b"shared-fixture-secret")
    _secret_with_material(g, engagement_dir, "secret:bbb", b"  shared-fixture-secret  \n")
    ev_a = attach_evidence(g, engagement_dir, b"proof-a", kind="extraction_proof", target_type="secret", target_id="secret:aaa")
    ev_b = attach_evidence(g, engagement_dir, b"proof-b", kind="extraction_proof", target_type="secret", target_id="secret:bbb")

    report = run_reconciliation_pass(g, engagement_dir)

    assert len(report.merges) == 1
    record = report.merges[0]
    assert record.node_type == "SECRET"
    assert record.survivor_id == "secret:aaa"
    assert record.merged_ids == ("secret:bbb",)

    loser = g.get_node("SECRET", "secret:bbb")
    assert loser["status"] == "merged"
    assert loser["merged_into"] == "secret:aaa"

    evidence_ids = set()
    result = g.execute("MATCH (e:EVIDENCE)-[:evidences]->(s:SECRET {id: $id}) RETURN e.id", {"id": "secret:aaa"})
    while result.has_next():
        evidence_ids.add(result.get_next()[0])
    assert {ev_a, ev_b} <= evidence_ids


# --- §4 test 2: API_ENDPOINT template merge ---------------------------------

def test_api_endpoint_numeric_path_segments_merge(tmp_path, manifest_factory, signing_keypair):
    g = _graph(tmp_path, manifest_factory, signing_keypair)
    url_a, url_b = "http://api.acme.example.com/users/123", "http://api.acme.example.com/users/456"
    g.upsert_node("API_ENDPOINT", url_a, {"url": url_a, "method": "GET", "source": "test"})
    g.upsert_node("API_ENDPOINT", url_b, {"url": url_b, "method": "GET", "source": "test"})

    report = run_reconciliation_pass(g, tmp_path)

    merges = [r for r in report.merges if r.node_type == "API_ENDPOINT"]
    assert len(merges) == 1
    survivor_id = min(url_a, url_b)
    loser_id = url_b if survivor_id == url_a else url_a
    assert merges[0].survivor_id == survivor_id
    assert merges[0].merged_ids == (loser_id,)
    assert g.get_node("API_ENDPOINT", loser_id)["merged_into"] == survivor_id


def test_api_endpoint_genuinely_different_paths_never_merge(tmp_path, manifest_factory, signing_keypair):
    g = _graph(tmp_path, manifest_factory, signing_keypair)
    url_a, url_b = "http://api.acme.example.com/users/1", "http://api.acme.example.com/admin/1"
    g.upsert_node("API_ENDPOINT", url_a, {"url": url_a, "method": "GET", "source": "test"})
    g.upsert_node("API_ENDPOINT", url_b, {"url": url_b, "method": "GET", "source": "test"})

    report = run_reconciliation_pass(g, tmp_path)

    assert [r for r in report.merges if r.node_type == "API_ENDPOINT"] == []
    assert g.get_node("API_ENDPOINT", url_a)["merged_into"] is None
    assert g.get_node("API_ENDPOINT", url_b)["merged_into"] is None


# --- §4 test 3: no cross-shape merge -----------------------------------------

def test_fqdn_and_ipv4_host_never_merge(tmp_path, manifest_factory, signing_keypair):
    g = _graph(tmp_path, manifest_factory, signing_keypair)
    g.upsert_node("HOST", "api.acme.example.com", {"source": "test"})
    g.upsert_node("HOST", "10.0.5.10", {"source": "test"})

    report = run_reconciliation_pass(g, tmp_path)

    assert [r for r in report.merges if r.node_type == "HOST"] == []
    assert g.get_node("HOST", "api.acme.example.com") is not None
    assert g.get_node("HOST", "10.0.5.10") is not None
    assert g.get_node("HOST", "api.acme.example.com")["merged_into"] is None
    assert g.get_node("HOST", "10.0.5.10")["merged_into"] is None


# --- §4 test 4: idempotency ---------------------------------------------------

def test_second_pass_is_a_true_noop(tmp_path, manifest_factory, signing_keypair):
    g = _graph(tmp_path, manifest_factory, signing_keypair)
    engagement_dir = tmp_path
    _secret_with_material(g, engagement_dir, "secret:aaa", b"dup-material")
    _secret_with_material(g, engagement_dir, "secret:bbb", b"dup-material")

    first = run_reconciliation_pass(g, engagement_dir)
    assert len(first.merges) == 1

    survivor_before = g.get_node("SECRET", "secret:aaa")
    loser_before = g.get_node("SECRET", "secret:bbb")

    second = run_reconciliation_pass(g, engagement_dir)

    assert second.is_empty()
    assert g.get_node("SECRET", "secret:aaa") == survivor_before
    assert g.get_node("SECRET", "secret:bbb") == loser_before


# --- §4 test 5: status cannot be laundered through a merge -------------------

def test_reachable_with_evidence_plus_extracted_twin_survivor_is_reachable(tmp_path, manifest_factory, signing_keypair):
    g = _graph(tmp_path, manifest_factory, signing_keypair)
    engagement_dir = tmp_path

    _secret_with_material(g, engagement_dir, "secret:aaa", b"laundering-case-a")
    advance_secret_status(g, "secret:aaa", "validated")
    evidence_id = attach_evidence(g, engagement_dir, b"real-proof", kind="validation_proof", target_type="secret", target_id="secret:aaa")
    advance_secret_status(g, "secret:aaa", "reachable")

    _secret_with_material(g, engagement_dir, "secret:bbb", b"laundering-case-a")  # extracted, no evidence

    report = run_reconciliation_pass(g, engagement_dir)

    assert len(report.merges) == 1
    survivor = g.get_node("SECRET", "secret:aaa")
    assert survivor["status"] == "reachable"

    result = g.execute(
        "MATCH (e:EVIDENCE {id: $eid})-[:evidences]->(s:SECRET {id: 'secret:aaa'}) RETURN count(*)",
        {"eid": evidence_id},
    )
    assert result.get_next()[0] == 1


def test_evidenceless_reachable_label_plus_extracted_twin_survivor_is_extracted(
    tmp_path, manifest_factory, signing_keypair
):
    g = _graph(tmp_path, manifest_factory, signing_keypair)
    engagement_dir = tmp_path

    _secret_with_material(g, engagement_dir, "secret:aaa", b"laundering-case-b")
    advance_secret_status(g, "secret:aaa", "validated")
    advance_secret_status(g, "secret:aaa", "reachable")  # labelled reachable, NO evidence ever attached

    _secret_with_material(g, engagement_dir, "secret:bbb", b"laundering-case-b")  # real extracted, no evidence

    report = run_reconciliation_pass(g, engagement_dir)

    assert len(report.merges) == 1
    survivor_id = min("secret:aaa", "secret:bbb")
    survivor = g.get_node("SECRET", survivor_id)
    assert survivor["status"] == "extracted"
    assert survivor["status"] != "reachable"


def test_dead_twin_plus_evidenceless_optimistic_twin_survivor_is_dead(tmp_path, manifest_factory, signing_keypair):
    g = _graph(tmp_path, manifest_factory, signing_keypair)
    engagement_dir = tmp_path

    _secret_with_material(g, engagement_dir, "secret:aaa", b"laundering-case-c")
    advance_secret_status(g, "secret:aaa", "dead")

    _secret_with_material(g, engagement_dir, "secret:bbb", b"laundering-case-c")
    advance_secret_status(g, "secret:bbb", "validated")
    advance_secret_status(g, "secret:bbb", "reachable")  # evidenceless optimistic twin

    report = run_reconciliation_pass(g, engagement_dir)

    assert len(report.merges) == 1
    survivor_id = min("secret:aaa", "secret:bbb")
    assert g.get_node("SECRET", survivor_id)["status"] == "dead"


# --- §4 test 6: pipeline invariant (generic, no live docker range needed) --

def test_reconcile_in_pipeline_never_shortcuts_or_changes_reachability(tmp_path, manifest_factory, signing_keypair):
    """Mirrors `cybergym/kronos_validation_run.py`'s own pipeline shape
    (ingest -> reconcile -> enrich -> reconcile -> assert -> validate)
    without needing the live docker-backed range: proves inserting
    reconcile changes nothing about which secret ends up reachable, and
    that an accidental enrichment-time duplicate never confers a status
    the real validation pass didn't itself earn."""
    g = _graph(tmp_path, manifest_factory, signing_keypair, scope={"in_scope": ["*"], "excluded": []})
    engagement_dir = tmp_path

    # "ingest": one secret leaked by a mobile app, referencing an endpoint.
    g.upsert_node("MOBILE_APP", "com.acme.app", {"bundle_id": "com.acme.app", "platform": "android", "source": "static"})
    _secret_with_material(g, engagement_dir, "secret:real", b"pipeline-secret")
    g.upsert_edge("leaks", "com.acme.app", "MOBILE_APP", "secret:real", "SECRET")
    g.upsert_node("API_ENDPOINT", "http://api.acme.example.com", {"url": "http://api.acme.example.com", "method": "GET", "source": "static"})
    g.upsert_edge("references", "com.acme.app", "MOBILE_APP", "http://api.acme.example.com", "API_ENDPOINT")

    # reconcile pass #1 (post-ingest): nothing to collapse yet.
    first_pass = run_reconciliation_pass(g, engagement_dir, pass_name="post_ingest")
    assert first_pass.is_empty()

    # "enrich": a second ingestion source re-discovers the SAME secret
    # under a different id/source (the exact scenario this brief exists
    # to fix) — created at status="extracted", same as any ingester.
    _secret_with_material(g, engagement_dir, "secret:enrichment_dup", b"pipeline-secret")
    g.upsert_edge("leaks", "com.acme.app", "MOBILE_APP", "secret:enrichment_dup", "SECRET")

    # the enrichment-shortcut invariant: every secret enrichment just
    # created is still exactly "extracted" right before reconcile/validate.
    assert g.get_node("SECRET", "secret:enrichment_dup")["status"] == "extracted"

    # reconcile pass #2 (post-enrich): the duplicate collapses.
    second_pass = run_reconciliation_pass(g, engagement_dir, pass_name="post_enrich")
    assert len(second_pass.merges) == 1
    survivor_id = second_pass.merges[0].survivor_id

    # the survivor is STILL exactly "extracted" after reconcile, before
    # validation ever runs — reconcile itself must never shortcut anyone.
    assert g.get_node("SECRET", survivor_id)["status"] == "extracted"

    with patch("kronos.validate.http_validator.validate_api_token") as mock_validate:
        mock_validate.return_value = ValidationOutcome(live=True, evidence=b"proof", detail="200")
        run_validation_pass(g, engagement_dir)

    # the real validation pass is what earns reachable — exactly once,
    # on the single surviving node (no duplicate work, no duplicate
    # finding).
    assert g.get_node("SECRET", survivor_id)["status"] == "reachable"
    for node_type, node_id in (("SECRET", "secret:real"), ("SECRET", "secret:enrichment_dup")):
        node = g.get_node(node_type, node_id)
        if node_id != survivor_id:
            assert node["merged_into"] == survivor_id

    # idempotent: reconciling again post-validation changes nothing.
    assert run_reconciliation_pass(g, engagement_dir, pass_name="post_validate").is_empty()


# --- §4 test 7: audit ---------------------------------------------------------

def test_merge_report_and_tombstones_are_queryable(tmp_path, manifest_factory, signing_keypair):
    g = _graph(tmp_path, manifest_factory, signing_keypair)
    engagement_dir = tmp_path
    _secret_with_material(g, engagement_dir, "secret:aaa", b"audit-material")
    _secret_with_material(g, engagement_dir, "secret:bbb", b"audit-material")

    report = run_reconciliation_pass(g, engagement_dir)
    record = report.merges[0]
    assert record.canonical_key.startswith("api_key:")
    assert record.pass_name == "reconcile"
    assert record.timestamp  # non-empty ISO timestamp

    from kronos.query import query_graph

    tombstones = query_graph(g, "SECRET", {"merged_into": record.survivor_id})
    assert any(n["id"] == "secret:bbb" and n["status"] == "merged" for n in tombstones)


# --- §4 test 8: guardrail diff checks -----------------------------------------

# Captured from `sha256sum src/kronos/scope_guard.py` before this brief's
# work began — SPEC_BRIEF4 guardrail 1 requires a ZERO-line diff on this
# file. If this assertion ever fails, scope_guard.py was touched; FORK-2
# (GitHub Aks2812/KRONOS#2) stays open and is not this brief's to resolve.
_SCOPE_GUARD_SHA256 = "41e56781c2f05fa28b4071e616364223094804d8f6d99fe0985414787ae7bde0"


def test_scope_guard_has_zero_line_diff():
    scope_guard_path = Path(kronos.__file__).parent / "scope_guard.py"
    digest = hashlib.sha256(scope_guard_path.read_bytes()).hexdigest()
    assert digest == _SCOPE_GUARD_SHA256, "scope_guard.py changed — FORK-2 must stay untouched (guardrail 1)"


def test_advance_secret_status_still_called_only_by_the_validation_runner():
    root = Path(kronos.__file__).parent
    callers = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if path.name != "lifecycle.py" and "advance_secret_status(" in path.read_text()
    )
    assert callers == ["validate/runner.py"], (
        "advance_secret_status must remain the forward mutator called only by the "
        f"validation runner; found callers: {callers}"
    )


def test_reconcile_never_calls_advance_secret_status():
    root = Path(kronos.__file__).parent / "reconcile"
    for path in root.rglob("*.py"):
        assert "advance_secret_status(" not in path.read_text(), (
            f"{path} calls advance_secret_status — reconciliation must only ever "
            "write status via lifecycle.set_secret_status_from_evidence"
        )
