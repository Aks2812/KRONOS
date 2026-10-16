"""SPEC_BRIEF9 §8 tests 1-3: the formal ingestion-source contract —
conformance, the sole-writer guard, and declining as a recorded,
non-silent outcome.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import kronos
from kronos.ingest import NodeUpsert
from kronos.ingest.contract import IngestionSource, IngestPlan, IngestReport, apply_plan
from kronos.ingest.mobile.parser import MOBILE_STATIC_SOURCE, ingest_mobile_static, ingest_mobile_static_plan

FIXTURE_APK = Path(__file__).parent / "fixtures" / "leaky_test.apk"


@pytest.fixture(scope="module")
def fixture_apk_exists():
    if not FIXTURE_APK.exists():
        pytest.fail(f"{FIXTURE_APK} missing — run tests/fixtures/build_leaky_apk.sh first")
    return FIXTURE_APK


# --- test 1: contract conformance ------------------------------------------


def test_mobile_source_satisfies_the_ingestion_source_protocol():
    assert isinstance(ingest_mobile_static_plan, IngestionSource)


def test_mobile_source_returns_a_plan_and_never_emits_lifecycle_or_scope_props(engagement_graph, fixture_apk_exists):
    g = engagement_graph
    plan = ingest_mobile_static_plan(fixture_apk_exists, g)

    assert isinstance(plan, IngestPlan)
    assert isinstance(plan.report, IngestReport)
    assert plan.report.source == MOBILE_STATIC_SOURCE

    forbidden_prop_keys = {"in_scope", "status", "confidence", "scope_note", "merged_into"}
    for item in plan.upserts:
        if isinstance(item, NodeUpsert):
            offending = forbidden_prop_keys & item.props.keys()
            # status IS legitimately settable at creation by a trusted
            # ingester (schema.py's NODE_PROPS_CREATE_ONLY) — only the
            # other four are hard-forbidden on every caller, always.
            assert offending <= {"status"}, f"{item.id} planned forbidden props: {offending}"


def test_mobile_source_holds_no_graph_handle_in_its_report(engagement_graph, fixture_apk_exists):
    """The report/plan returned must never itself carry a live graph
    reference — it is pure, inert data describing what WOULD be
    written, not a handle into what was."""
    g = engagement_graph
    plan = ingest_mobile_static_plan(fixture_apk_exists, g)
    assert g not in plan.report.__dict__.values()
    assert not any(v is g for v in vars(plan.report).values())


# --- acceptance #3: conformance did not change any planned node's id/props -


def test_conforming_entry_point_produces_byte_identical_upserts_to_the_legacy_one(
    engagement_graph, fixture_apk_exists
):
    """SPEC_BRIEF9 §8 test 3 / acceptance #3: proof, not assertion-by-
    convention. `ingest_mobile_static` is the pre-existing, unchanged-
    signature entry point `cybergym/kronos_validation_run.py` depends
    on; `ingest_mobile_static_plan` is the new contract-conforming one.
    Both share one extraction core (`_ingest_mobile_static_core`) — this
    proves that sharing it actually held, by running BOTH against the
    identical fixture and diffing every planned node/edge's id and
    props directly, not just trusting that adaptation didn't rewrite
    anything."""
    g = engagement_graph
    legacy_upserts = ingest_mobile_static(fixture_apk_exists, g)
    plan = ingest_mobile_static_plan(fixture_apk_exists, g)

    assert len(legacy_upserts) == len(plan.upserts)
    for legacy_item, plan_item in zip(legacy_upserts, plan.upserts):
        assert type(legacy_item) is type(plan_item)
        if isinstance(legacy_item, NodeUpsert):
            assert legacy_item.type == plan_item.type
            assert legacy_item.id == plan_item.id
            # created_at is the one legitimate exception (both brief
            # language and schema.py: create-only, stamped fresh per
            # call) — every other prop must match exactly.
            legacy_props = {k: v for k, v in legacy_item.props.items() if k != "created_at"}
            plan_props = {k: v for k, v in plan_item.props.items() if k != "created_at"}
            assert legacy_props == plan_props
            assert legacy_item.scope_key == plan_item.scope_key
        else:  # EdgeUpsert
            assert legacy_item.label == plan_item.label
            assert legacy_item.from_id == plan_item.from_id
            assert legacy_item.to_id == plan_item.to_id
            assert legacy_item.props == plan_item.props


# --- test 2: apply_plan is the sole graph writer under ingest/ -------------


def test_apply_plan_is_the_sole_graph_writer_under_ingest_mechanically():
    """Mirrors the budget-exemption guard in `tests/test_cleanup.py`:
    scan real source lines (not just a bare substring match anywhere),
    and assert the scan was non-vacuous (SPEC_BRIEF8.1 §4's lesson) —
    `apply_upserts` (in `ingest/__init__.py`) is the one place that
    legitimately calls `.upsert_node(`/`.upsert_edge(` directly; every
    other module under `ingest/`, including `contract.py`'s `apply_plan`
    (which delegates to `apply_upserts` rather than writing itself),
    must never do so."""
    root = Path(kronos.__file__).parent / "ingest"
    exempt_files = {"__init__.py"}  # apply_upserts' own direct writes
    scanned = 0
    offenders = []
    for path in root.rglob("*.py"):
        scanned += 1
        if path.name in exempt_files:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if ".upsert_node(" in line or ".upsert_edge(" in line:
                offenders.append(f"{path.relative_to(root)}:{lineno}: {line.strip()}")
    assert scanned > 0, "guard scanned zero files — src/kronos/ingest/ path resolution is broken, not clean"
    assert offenders == [], f"direct graph writes found outside apply_upserts: {offenders}"


def test_apply_plan_delegates_to_apply_upserts_and_writes_identically(engagement_graph, fixture_apk_exists):
    g = engagement_graph
    plan = ingest_mobile_static_plan(fixture_apk_exists, g)
    apply_plan(g, plan)

    app = g.get_node("MOBILE_APP", "com.kronos.testfixture.leakyapp")
    assert app is not None
    assert app["source"] == "static"


# --- test 3: declining is recorded, not silent ------------------------------


def test_declined_manifest_produces_a_report_entry_and_an_event_not_a_crash(
    monkeypatch, engagement_graph, tmp_path
):
    import kronos.ingest.mobile.parser as parser_module

    def _fake_apktool_decode(apk_path, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "AndroidManifest.xml").write_text("<manifest xmlns:android='x'></manifest>")  # missing package

    monkeypatch.setattr(parser_module, "_run_apktool_decode", _fake_apktool_decode)

    g = engagement_graph
    fake_apk = tmp_path / "fake.apk"
    fake_apk.write_bytes(b"not a real apk, apktool call is mocked above")

    plan = parser_module.ingest_mobile_static_plan(fake_apk, g)

    assert plan.upserts == ()
    assert len(plan.report.declined) == 1
    assert plan.report.declined[0].reason == "unparseable_manifest"

    events_path = g.db_path.parent / "events.jsonl"
    records = [json.loads(line) for line in events_path.read_text().splitlines()]
    kinds = [r["kind"] for r in records]
    assert "ingest_started" in kinds
    assert "ingest_declined" in kinds
    assert "ingest_finished" in kinds
    declined_event = next(r for r in records if r["kind"] == "ingest_declined")
    assert declined_event["reason"] == "unparseable_manifest"
