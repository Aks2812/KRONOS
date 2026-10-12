#!/usr/bin/env python3
"""The first real X-score measurement (SPEC_BRIEF3 deliverable #4):
stands up the live CyberGym range, runs Brief #2's real mobile
ingestion on the planted APK, applies a small CYBERGYM-ONLY enrichment
step (documented below and in DECISIONS.md), then hands the completed
graph to the real, generic `kronos.validate.run_validation_pass` — the
exact same function any other engagement would use — and checks the
result against `ground_truth.yaml`.

HARD RULE on the enrichment step (explicit user guardrail, logged in
DECISIONS.md): it is test-harness glue, CyberGym-only, standing in for
a fuller ingestion layer a later brief will build natively. It may
ONLY add target nodes/edges (the full endpoint URL, the two
CLOUD_RESOURCE buckets) and reconstruct chain-3's secret by the EXACT
method `ground_truth.yaml` documents (concatenating
`assets/cfg.dat` + `kronos_chain3_secret_part2`). Every node it writes
goes through the SAME scope-gated, allowlisted `apply_upserts()` path
any ingester uses, and every SECRET it writes is created at
status="extracted" — exactly what an ingester's initial value always
is. It NEVER calls `advance_secret_status`, NEVER sets `status` to
anything but "extracted", and NEVER touches confidence/in_scope/
scope_note. `_assert_enrichment_did_not_shortcut_anyone` checks this
mechanically, not just by convention, right after enrichment runs and
BEFORE the validation pass — so if this ever regresses, the run fails
loudly instead of producing a lying X-score.

SPEC_BRIEF5: this run is now budget-governed. A `budget.yaml` is written
into the engagement dir before anything else runs (FORK-D's DEFAULT —
a file, not a signed-manifest section) with a deliberately generous
ceiling on every metered dimension, and the one `BudgetLedger` created
from it is passed into `run_validation_pass` and checked between every
pipeline phase. A `BudgetExceeded` anywhere stops the run cleanly: the
ledger snapshot is written to the engagement dir, a "stopped early"
marker is printed, and whatever chain checks are still answerable from
the graph as it stands run anyway — this script never crashes on an
exhausted budget, and never produces an unmetered X-score.

Run (from the repo root, after `docker compose up` is NOT required —
this script brings the lab up and down itself):
    PYTHONPATH=. .venv/bin/python cybergym/kronos_validation_run.py
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from cybergym.selftest import compose, wait_for_services  # noqa: E402

from kronos.budget import (  # noqa: E402
    BudgetExceeded,
    BudgetLedger,
    load_budget_limits,
    stopped_early_marker,
    write_ledger_snapshot,
)
from kronos.evidence import store_evidence  # noqa: E402
from kronos.graph import EngagementGraph  # noqa: E402
from kronos.ingest import EdgeUpsert, NodeUpsert, apply_upserts, ingest  # noqa: E402
from kronos.manifest import load_and_verify  # noqa: E402
from kronos.query import find_paths  # noqa: E402
from kronos.reconcile import MergeReport, run_reconciliation_pass  # noqa: E402
from kronos.validate import run_validation_pass  # noqa: E402

from cryptography.hazmat.primitives import serialization  # noqa: E402

# A deliberately generous ceiling for this fixture (SPEC_BRIEF5 §4 test
# 6: "non-interference" — the budget must change nothing about a run
# this small) — written to the engagement dir so this run also
# exercises FORK-D's real file-loading path, not just the in-memory
# default. The acceptance tests for "missing/invalid budget.yaml falls
# back to the conservative default" (§4 test 5) live in
# `tests/test_budget.py`, exercising that path directly.
_GENEROUS_BUDGET_YAML = """\
validation_attempts: 100
tool_invocations: 100
wall_clock_seconds: 900
llm_tokens: 0
llm_cost_usd: 0
"""

APK_PATH = HERE / "mobile" / "cybergym_lab.apk"
BUNDLE_ID = "com.kronos.cybergym.lab"
CHAIN1_FULL_URL = "http://localhost:8091/internal/v1/admin/export"
CLOUD_PROXY_ENDPOINT = "http://localhost:4567"
GENERAL_BUCKET = "kronos-cybergym-general"
ADMIN_BUCKET = "kronos-cybergym-admin-secrets"

CHAIN1_SECRET_VALUE = "CYBERGYM_FIXTURE_CHAIN1_API_KEY_4d2f8a91"
CHAIN2_SECRET_VALUE = "CYBERGYMGENERALUSER0001:cybergym-fixture-general-secret-7f3a9c1e"


def _secret_node_id(value: str) -> str:
    # Mirrors kronos.ingest.mobile.parser._secret_node_id exactly — the
    # convention is duplicated here (not imported) because this script
    # computes it for secrets Brief #2's ingestion ALREADY created, not
    # ones it's creating itself; see chain-3's handling below for the
    # one secret this script does create.
    return f"secret:{hashlib.sha256(value.encode()).hexdigest()[:16]}"


def _extract_resource(xml_text: str, name: str) -> str:
    root = ET.fromstring(xml_text)
    for el in root.findall("string"):
        if el.attrib.get("name") == name and el.text is not None:
            return el.text
    raise KeyError(f"resource {name!r} not found")


def _load_manifest_and_graph(engagement_dir: Path) -> EngagementGraph:
    manifest_text = (HERE / "scope_manifest.yaml").read_text()
    pubkey = serialization.load_pem_public_key((HERE / "scope_manifest_pubkey.pem").read_bytes())
    load_and_verify(manifest_text, pubkey)  # fail loudly here, not deep inside init_engagement
    return EngagementGraph.init_engagement(engagement_dir / "e.kz", manifest_text, pubkey)


def _print_merge_report(report: MergeReport) -> None:
    if report.is_empty():
        print("  no duplicates found")
        return
    for record in report.merges:
        print(
            f"  merged {record.node_type} {record.merged_ids} -> {record.survivor_id} "
            f"(canonical_key={record.canonical_key!r})"
        )


def _survivor_of(graph: EngagementGraph, secret_id: str) -> str:
    """Follow `merged_into` to whichever id this secret's data now lives
    on (a no-op if it was never merged) — Brief #4's reconciliation can
    rename which id a chain's secret is addressable under."""
    current = secret_id
    while True:
        node = graph.get_node("SECRET", current)
        if node is None or node.get("merged_into") is None:
            return current
        current = node["merged_into"]


def _assert_enrichment_did_not_shortcut_anyone(graph: EngagementGraph, secret_id: str) -> None:
    """Mechanical check, not just convention (explicit user guardrail):
    every secret the enrichment step touches must still be exactly
    "extracted" immediately after enrichment and before any validation
    call. If this ever fails, the run aborts — an X-score built on a
    shortcut is worse than no X-score."""
    secret = graph.get_node("SECRET", secret_id)
    if secret["status"] != "extracted":
        raise AssertionError(
            f"enrichment-created secret {secret_id} has status={secret['status']!r}, "
            "not 'extracted' — enrichment must never pre-set a terminal status"
        )


def _print_budget_snapshot(ledger: BudgetLedger) -> None:
    snapshot = ledger.snapshot()
    print(f"BUDGET: config_source={snapshot.config_source}" + (f" ({snapshot.config_reason})" if snapshot.config_reason else ""))
    for dimension, ceiling in dataclasses.asdict(snapshot.limits).items():
        spent = snapshot.totals.get(dimension, 0)
        print(f"  {dimension}: {spent} / {ceiling if ceiling is not None else 'unlimited'}")
    marker = stopped_early_marker(snapshot)
    if marker:
        print(f"  {marker}")


def _run_pipeline(engagement_dir: Path) -> int:
    """Everything from loading the manifest through the X-SCORE line —
    extracted to its own function (SPEC_BRIEF5) so the budget-exhaustion
    wind-down (write the ledger snapshot, print the "stopped early"
    marker, exit non-crash) has exactly one place to catch
    `BudgetExceeded`, no matter which phase raised it."""
    graph = _load_manifest_and_graph(engagement_dir)

    (engagement_dir / "budget.yaml").write_text(_GENEROUS_BUDGET_YAML)
    config_result = load_budget_limits(engagement_dir)
    ledger = BudgetLedger(config_result.limits, config_source=config_result.source, config_reason=config_result.reason)

    try:
        print("running Brief #2 mobile static ingestion on the planted APK...")
        upserts = ingest(APK_PATH, "mobile_static", graph)
        apply_upserts(graph, upserts)
        ledger.check_wall_clock()

        print("reconciling (post-ingest pass)...")
        post_ingest_report = run_reconciliation_pass(graph, engagement_dir, pass_name="post_ingest")
        _print_merge_report(post_ingest_report)
        ledger.check_wall_clock()

        print("applying CyberGym-only enrichment (target nodes/edges + documented secret reconstruction)...")
        strings_xml = (HERE / "mobile" / "apk_src" / "res" / "values" / "strings.xml").read_text()

        # Chain 2's secret: Brief #2's secret-name regex matches
        # "credential" but not the abbreviation "creds", so
        # "kronos_chain2_creds_enc" was never captured at all (found
        # empirically running this script — not anticipated in the
        # original plan). ground_truth.yaml documents this resource's
        # exact location and decode method (base64), so decoding it
        # here is the same class of allowance already granted for
        # chain 3, applied to a second, independently-discovered gap.
        chain2_value = base64.b64decode(_extract_resource(strings_xml, "kronos_chain2_creds_enc")).decode()
        chain2_secret_id = _secret_node_id(chain2_value)
        chain2_info = store_evidence(engagement_dir, chain2_value.encode(), kind="mobile_secret_reconstructed")

        # Chain 3's secret: split across assets/cfg.dat + a strings.xml
        # fragment — ground_truth.yaml's documented reconstruction.
        part1 = (HERE / "mobile" / "apk_src" / "assets" / "cfg.dat").read_text()
        part2 = _extract_resource(strings_xml, "kronos_chain3_secret_part2")
        chain3_value = part1 + part2
        chain3_secret_id = _secret_node_id(chain3_value)
        chain3_info = store_evidence(engagement_dir, chain3_value.encode(), kind="mobile_secret_reconstructed")

        reconstructed_secret_ids = [chain2_secret_id, chain3_secret_id]

        enrichment_upserts: list[NodeUpsert | EdgeUpsert] = [
            NodeUpsert("API_ENDPOINT", CHAIN1_FULL_URL, {"source": "cybergym_enrichment"}),
            EdgeUpsert("references", BUNDLE_ID, CHAIN1_FULL_URL),
            NodeUpsert(
                "CLOUD_RESOURCE", GENERAL_BUCKET,
                {"resource_type": "s3_bucket", "provider": "aws", "source": "cybergym_enrichment"},
                scope_key=f"arn:aws:s3:::{GENERAL_BUCKET}",
            ),
            NodeUpsert(
                "CLOUD_RESOURCE", ADMIN_BUCKET,
                {"resource_type": "s3_bucket", "provider": "aws", "source": "cybergym_enrichment"},
                scope_key=f"arn:aws:s3:::{ADMIN_BUCKET}",
            ),
            NodeUpsert(
                "SECRET", chain2_secret_id,
                {"value_ref": "sha256:" + chain2_info["sha256"], "kind": "api_key_obfuscated",
                 "status": "extracted", "source": "cybergym_enrichment"},
                scope_key=BUNDLE_ID,
            ),
            EdgeUpsert("leaks", BUNDLE_ID, chain2_secret_id),
            NodeUpsert(
                "SECRET", chain3_secret_id,
                {"value_ref": "sha256:" + chain3_info["sha256"], "kind": "api_key_obfuscated",
                 "status": "extracted", "source": "cybergym_enrichment"},
                scope_key=BUNDLE_ID,
            ),
            EdgeUpsert("leaks", BUNDLE_ID, chain3_secret_id),
        ]
        apply_upserts(graph, enrichment_upserts)
        for sid in reconstructed_secret_ids:
            _assert_enrichment_did_not_shortcut_anyone(graph, sid)

        print("reconciling (post-enrichment pass, before validation)...")
        post_enrich_report = run_reconciliation_pass(graph, engagement_dir, pass_name="post_enrich")
        _print_merge_report(post_enrich_report)
        # Reconciliation must never become a second shortcut path
        # (guardrail 7): re-assert on whichever id each reconstructed
        # secret survived as (reconcile may have renamed the survivor
        # if it merged with an ingestion-discovered twin).
        for sid in reconstructed_secret_ids:
            survivor_id = _survivor_of(graph, sid)
            _assert_enrichment_did_not_shortcut_anyone(graph, survivor_id)
        ledger.check_wall_clock()

        print("running the REAL kronos.validate validation pass against the live range...")
        attempts = run_validation_pass(
            graph,
            engagement_dir,
            cloud_proxy_endpoint=CLOUD_PROXY_ENDPOINT,
            http_hints={CHAIN1_FULL_URL: {"method": "POST", "header_name": "X-Cybergym-Key"}},
            budget=ledger,
        )
        for a in attempts:
            print(f"  attempt: secret={a.secret_id[:20]} target={a.target_id} live={a.live} ({a.detail})")

        # Resolve each chain's secret to wherever reconciliation left
        # its data (a no-op if it was never merged) — Brief #4 can
        # legitimately rename which id a chain's data now lives under.
        chain1_id = _survivor_of(graph, _secret_node_id(CHAIN1_SECRET_VALUE))
        chain2_id = _survivor_of(graph, _secret_node_id(CHAIN2_SECRET_VALUE))
        chain3_id = _survivor_of(graph, chain3_secret_id)

        print()
        chain_results = [
            _check_chain(graph, "chain-1", chain1_id, expect_edges_to=[CHAIN1_FULL_URL], expect_no_edges_to=[]),
            _check_chain(
                graph, "chain-2", chain2_id, expect_edges_to=[GENERAL_BUCKET], expect_no_edges_to=[ADMIN_BUCKET]
            ),
            _check_chain(
                graph, "chain-3", chain3_id,
                expect_edges_to=[GENERAL_BUCKET, ADMIN_BUCKET], expect_no_edges_to=[],
            ),
        ]

        print()
        print("cross-domain chains (find_paths):")
        for path in find_paths(graph, "MOBILE_APP", "API_ENDPOINT"):
            print(f"  {' -> '.join(f'{n}[{l}]' for n, l in zip(path['nodes'], [''] + path['labels']))}")
        for path in find_paths(graph, "MOBILE_APP", "CLOUD_RESOURCE"):
            print(f"  {' -> '.join(f'{n}[{l}]' for n, l in zip(path['nodes'], [''] + path['labels']))}")

        x_score = sum(chain_results)
        print()
        total_merges = len(post_ingest_report.merges) + len(post_enrich_report.merges)
        print(f"RECONCILIATION: {total_merges} duplicate(s) collapsed across both passes")
        print(f"X-SCORE: {x_score}/3 chains validated end-to-end")
        write_ledger_snapshot(engagement_dir, ledger)
        _print_budget_snapshot(ledger)
        return 0 if x_score == 3 else 1
    except BudgetExceeded as exc:
        # Fail-closed wind-down (SPEC_BRIEF5 §2/guardrail 6): never a
        # crash, never an unmetered continuation. Write what the ledger
        # has, print the one canonical marker, and report whatever the
        # graph as it stands can answer — an interrupted chain simply
        # reads as not-yet-reachable, exactly like a chain validation
        # never got to would under the EXISTING `_check_chain` logic, no
        # special-casing needed.
        write_ledger_snapshot(engagement_dir, ledger)
        print()
        print(f"BUDGET EXCEEDED: {exc}")
        _print_budget_snapshot(ledger)
        print("X-SCORE: incomplete — run stopped early by budget enforcement, not evaluated")
        return 3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-teardown", action="store_true")
    parser.add_argument("--no-standup", action="store_true")
    args = parser.parse_args()

    try:
        if not args.no_standup:
            print("standing up the lab (docker compose up -d --build)...")
            compose("up", "-d", "--build")
            print("waiting for services...")
            wait_for_services()

        with TemporaryDirectory(prefix="kronos-cybergym-run-") as tmp:
            return _run_pipeline(Path(tmp))
    finally:
        if not args.no_teardown and not args.no_standup:
            print("tearing down the lab (docker compose down)...")
            compose("down", "-v")


def _check_chain(
    graph: EngagementGraph, label: str, secret_id: str, *, expect_edges_to: list[str], expect_no_edges_to: list[str]
) -> bool:
    secret = graph.get_node("SECRET", secret_id)
    if secret is None:
        print(f"[FAIL] {label}: secret {secret_id} not found in graph")
        return False
    ok = secret["status"] == "reachable"
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: status={secret['status']} confidence={secret['confidence']}")

    for target_id in expect_edges_to:
        result = graph.execute(
            "MATCH (s:SECRET {id: $sid})-[:authenticates_to]->(t {id: $tid}) RETURN count(*)",
            {"sid": secret_id, "tid": target_id},
        )
        has_edge = result.get_next()[0] > 0
        print(f"  {'PASS' if has_edge else 'FAIL'}: authenticates_to -> {target_id}: {has_edge}")
        ok = ok and has_edge

    for target_id in expect_no_edges_to:
        result = graph.execute(
            "MATCH (s:SECRET {id: $sid})-[:authenticates_to]->(t {id: $tid}) RETURN count(*)",
            {"sid": secret_id, "tid": target_id},
        )
        has_edge = result.get_next()[0] > 0
        print(f"  {'PASS' if not has_edge else 'FAIL'}: NOT authenticates_to -> {target_id} (boundary): {not has_edge}")
        ok = ok and not has_edge

    return ok


if __name__ == "__main__":
    raise SystemExit(main())
