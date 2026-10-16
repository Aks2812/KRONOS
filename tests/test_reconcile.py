"""SPEC_BRIEF4's acceptance tests (§4) for the reconciliation/dedup pass,
plus the two guardrail-diff checks (§4 test 8) and the pipeline-invariant
proof (§4 test 6) run generically (CyberGym's own live run is the
docker-backed proof of the same invariant; this test proves it without a
live range so it holds in plain CI too).

SPEC_BRIEF4.1 adds the tests that turn the no-op proof into a real one:
genuine distinct-id duplicates for SECRET and API_ENDPOINT, proving Fix
#1 (a tombstoned loser ends up with ZERO relationships, not just a
`merged_into` label — `find_paths` returns the survivor only) and the
FINDING guard (Fix #2: a real FINDING group must raise `NotImplementedError`
rather than silently merge with no evidence recompute).
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
from kronos.query import find_paths, query_graph
from kronos.reconcile import run_reconciliation_pass
from kronos.reconcile.merge import merge_group
from kronos.schema import EDGE_PAIRS
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
        mock_validate.return_value = ValidationOutcome(live=True, evidence=b"proof", detail="200", classification="live_discriminated", discriminated=True)
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

    tombstones = query_graph(g, "SECRET", {"merged_into": record.survivor_id})
    assert any(n["id"] == "secret:bbb" and n["status"] == "merged" for n in tombstones)


# --- SPEC_BRIEF4.1 §4: real duplicates — inertness + FINDING guard ---------

def _edge_count_touching(graph, node_type: str, node_id: str) -> int:
    """Every relationship this node participates in, either direction,
    across every label/pair `EDGE_PAIRS` declares it for — the same walk
    `merge.py`'s own carry-over/delete steps use, so this is a faithful
    "is this node genuinely edgeless" check (Fix #1), not just a count of
    the one or two edge types a given test happens to set up."""
    total = 0
    for label, pairs in EDGE_PAIRS.items():
        for frm, to in pairs:
            if frm == node_type:
                result = graph.execute(
                    f"MATCH (a:{frm} {{id: $id}})-[:{label}]->(b:{to}) RETURN count(*)", {"id": node_id}
                )
                total += result.get_next()[0]
            if to == node_type:
                result = graph.execute(
                    f"MATCH (a:{frm})-[:{label}]->(b:{to} {{id: $id}}) RETURN count(*)", {"id": node_id}
                )
                total += result.get_next()[0]
    return total


def test_secret_real_duplicate_moves_edges_recomputes_status_loser_is_edgeless_and_idempotent(
    tmp_path, manifest_factory, signing_keypair
):
    """The SECRET case SPEC_BRIEF4.1 §4 asks for: two distinct-id
    secrets, same material, each with its OWN edges (one evidence-backed
    plus a cloud `authenticates_to`, one only `leaks`-linked from an
    app). Proves: the survivor holds the union of both secrets' edges;
    the loser ends up with ZERO relationships (Fix #1's actual
    inertness, not just a `merged_into` label — `find_paths` returns the
    survivor only, never the loser); the survivor's status is
    `recompute_status_from_evidence` of the merged evidence, not a
    carried-over label; and a second pass on this now-non-empty,
    already-tombstoned graph is still a true no-op."""
    g = _graph(tmp_path, manifest_factory, signing_keypair, scope={"in_scope": ["*"], "excluded": []})
    engagement_dir = tmp_path

    _secret_with_material(g, engagement_dir, "secret:aaa", b"real-dup-material")
    advance_secret_status(g, "secret:aaa", "validated")
    evidence_id = attach_evidence(
        g, engagement_dir, b"real-dup-proof", kind="validation_proof", target_type="secret", target_id="secret:aaa"
    )
    advance_secret_status(g, "secret:aaa", "reachable")
    g.upsert_node("CLOUD_RESOURCE", "cr1", {"resource_type": "s3_bucket", "provider": "aws", "source": "test"})
    g.upsert_edge("authenticates_to", "secret:aaa", "SECRET", "cr1", "CLOUD_RESOURCE")

    _secret_with_material(g, engagement_dir, "secret:bbb", b"real-dup-material")  # extracted, no evidence
    g.upsert_node("MOBILE_APP", "app1", {"bundle_id": "app1", "platform": "android", "source": "test"})
    g.upsert_edge("leaks", "app1", "MOBILE_APP", "secret:bbb", "SECRET")

    first = run_reconciliation_pass(g, engagement_dir)
    assert len(first.merges) == 1
    survivor_id, loser_id = "secret:aaa", "secret:bbb"
    assert first.merges[0].survivor_id == survivor_id
    assert first.merges[0].merged_ids == (loser_id,)

    # Fix #1: the loser is a genuinely edgeless tombstone.
    assert _edge_count_touching(g, "SECRET", loser_id) == 0
    loser = g.get_node("SECRET", loser_id)
    assert loser["status"] == "merged"
    assert loser["merged_into"] == survivor_id

    # The survivor holds the UNION of both secrets' edges.
    result = g.execute(
        "MATCH (app:MOBILE_APP {id: 'app1'})-[:leaks]->(s:SECRET {id: $id}) RETURN count(*)", {"id": survivor_id}
    )
    assert result.get_next()[0] == 1
    result = g.execute(
        "MATCH (s:SECRET {id: $id})-[:authenticates_to]->(c:CLOUD_RESOURCE {id: 'cr1'}) RETURN count(*)",
        {"id": survivor_id},
    )
    assert result.get_next()[0] == 1

    # Status recomputed from the merged evidence (guardrail 3) — the
    # survivor already had real evidence and stays reachable, but that's
    # recompute.py's own derivation re-confirming it, not an untouched
    # carried-over label.
    survivor = g.get_node("SECRET", survivor_id)
    assert survivor["status"] == "reachable"
    result = g.execute(
        "MATCH (e:EVIDENCE {id: $eid})-[:evidences]->(s:SECRET {id: $sid}) RETURN count(*)",
        {"eid": evidence_id, "sid": survivor_id},
    )
    assert result.get_next()[0] == 1

    # find_paths never traverses through the edgeless loser.
    paths = find_paths(g, "MOBILE_APP", "CLOUD_RESOURCE")
    assert len(paths) >= 1
    for path in paths:
        assert loser_id not in path["nodes"]
        assert survivor_id in path["nodes"]

    # Idempotent on this now-non-empty, already-tombstoned graph.
    survivor_before = g.get_node("SECRET", survivor_id)
    loser_before = g.get_node("SECRET", loser_id)
    second = run_reconciliation_pass(g, engagement_dir)
    assert second.is_empty()
    assert g.get_node("SECRET", survivor_id) == survivor_before
    assert g.get_node("SECRET", loser_id) == loser_before


def test_api_endpoint_real_duplicate_edges_move_and_find_paths_returns_survivor_only(
    tmp_path, manifest_factory, signing_keypair
):
    """The API_ENDPOINT case SPEC_BRIEF4.1 §4 asks for: two endpoints
    merge on their templated path, a third with a genuinely different
    path stays separate, and a `find_paths` traversal through the
    endpoint domain returns the survivor only — never a loser id."""
    g = _graph(tmp_path, manifest_factory, signing_keypair, scope={"in_scope": ["*"], "excluded": []})

    url_a = "http://api.acme.example.com/users/123"
    url_b = "http://api.acme.example.com/users/456"
    url_c = "http://api.acme.example.com/admin/1"
    for url in (url_a, url_b, url_c):
        g.upsert_node("API_ENDPOINT", url, {"url": url, "method": "GET", "source": "test"})
    g.upsert_node("HOST", "h1", {"source": "test"})
    for url in (url_a, url_b, url_c):
        g.upsert_edge("exposes", "h1", "HOST", url, "API_ENDPOINT")

    report = run_reconciliation_pass(g, tmp_path)

    merges = [r for r in report.merges if r.node_type == "API_ENDPOINT"]
    assert len(merges) == 1
    survivor_id = min(url_a, url_b)
    loser_id = url_b if survivor_id == url_a else url_a
    assert merges[0].survivor_id == survivor_id
    assert merges[0].merged_ids == (loser_id,)

    # Fix #1: the loser is edgeless.
    assert _edge_count_touching(g, "API_ENDPOINT", loser_id) == 0
    # The survivor still carries the exposes edge from h1.
    result = g.execute(
        "MATCH (h:HOST {id: 'h1'})-[:exposes]->(e:API_ENDPOINT {id: $id}) RETURN count(*)", {"id": survivor_id}
    )
    assert result.get_next()[0] == 1
    # url_c never merged — genuinely different path.
    assert g.get_node("API_ENDPOINT", url_c)["merged_into"] is None

    paths = find_paths(g, "HOST", "API_ENDPOINT")
    found_ids = {node_id for path in paths for node_id in path["nodes"]}
    assert survivor_id in found_ids
    assert url_c in found_ids
    assert loser_id not in found_ids


def test_finding_merge_group_refuses_a_real_duplicate(tmp_path, manifest_factory, signing_keypair):
    """SPEC_BRIEF4.1 §3 Fix #2's backstop: `canonical_key_for_finding`
    always returns `None` today, so the runner never actually calls
    `merge_group` for FINDING — but if it ever did (a future brief
    populates `location_sig`), a >=2 FINDING group must refuse to merge
    rather than silently settle on an un-recomputed survivor. Calls
    `merge_group` directly, bypassing the None-key runner path, to prove
    the guard itself fires."""
    g = _graph(tmp_path, manifest_factory, signing_keypair)
    g.upsert_node("FINDING", "f1", {"title": "t", "severity": "high", "status": "hypothesis"})
    g.upsert_node("FINDING", "f2", {"title": "t", "severity": "high", "status": "hypothesis"})

    with pytest.raises(NotImplementedError):
        merge_group(g, "FINDING", ["f1", "f2"], "some:canonical:key", "test_pass")


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
