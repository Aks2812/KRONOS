"""SPEC_BRIEF5 §4's eight acceptance tests for per-engagement budget
governance: fail-closed enforcement, never-fails-open, determinism, the
wall-clock cap, config fallback, non-interference with a generous
budget, the audit trail, and the two guardrail diffs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

import kronos
from kronos.budget import (
    BudgetConfigResult,
    BudgetExceeded,
    BudgetLedger,
    BudgetLimits,
    DEFAULT_BUDGET_LIMITS,
    load_budget_limits,
    write_ledger_snapshot,
)
from kronos.budget.ledger import stopped_early_marker
from kronos.evidence import store_evidence
from kronos.graph import EngagementGraph
from kronos.reconcile import run_reconciliation_pass
from kronos.validate.runner import run_validation_pass
from kronos.validate.types import ValidationOutcome


def _graph_with_secret_and_endpoints(engagement_dir, manifest_factory, signing_keypair, n_endpoints: int):
    _, pub = signing_keypair
    manifest_text = manifest_factory(scope={"in_scope": ["http://ep-*"], "excluded": []})
    graph = EngagementGraph.init_engagement(Path(engagement_dir) / "e.kz", manifest_text, pub)

    info = store_evidence(engagement_dir, b"plain-bearer-token", kind="mobile_secret")
    secret_id = f"secret:{info['sha256'][:16]}"
    graph.upsert_node("MOBILE_APP", "com.kronos.lab", {"bundle_id": "com.kronos.lab", "platform": "android", "source": "static"})
    graph.upsert_node(
        "SECRET", secret_id,
        {"value_ref": "sha256:" + info["sha256"], "kind": "api_key", "status": "extracted", "source": "static"},
        scope_key="com.kronos.lab",
    )
    graph.upsert_edge("leaks", "com.kronos.lab", "MOBILE_APP", secret_id, "SECRET")
    for i in range(n_endpoints):
        url = f"http://ep-{i}"
        graph.upsert_node("API_ENDPOINT", url, {"source": "static"})
        graph.upsert_edge("references", "com.kronos.lab", "MOBILE_APP", url, "API_ENDPOINT")
    return graph, secret_id


# --- §4 test 1: fail-closed enforcement ---------------------------------------

def test_fail_closed_enforcement_stops_exactly_at_the_cap(tmp_path, manifest_factory, signing_keypair):
    graph, secret_id = _graph_with_secret_and_endpoints(tmp_path, manifest_factory, signing_keypair, n_endpoints=2)
    ledger = BudgetLedger(BudgetLimits(validation_attempts=1), config_source="test")

    with patch("kronos.validate.http_validator.validate_api_token") as mock_validate:
        mock_validate.return_value = ValidationOutcome(live=True, evidence=b"proof", detail="200", classification="live_discriminated", discriminated=True)
        with pytest.raises(BudgetExceeded) as excinfo:
            run_validation_pass(graph, tmp_path, budget=ledger)

    assert excinfo.value.dimension == "validation_attempts"
    # The over-cap SECOND candidate's validator call never ran.
    mock_validate.assert_called_once()

    result = graph.execute(
        "MATCH (s:SECRET {id: $id})-[:authenticates_to]->() RETURN count(*)", {"id": secret_id}
    )
    assert result.get_next()[0] == 1  # exactly the one attempt that ran before the cap stopped it

    snapshot = ledger.snapshot()
    assert snapshot.totals["validation_attempts"] == 1  # the ledger shows the cap hit, not a partial/odd number
    assert snapshot.stopped_reason == "validation_attempts"


# --- §4 test 2: never fails open -----------------------------------------------

def test_never_fails_open_zero_further_actions_once_already_exhausted(
    tmp_path, manifest_factory, signing_keypair
):
    graph, secret_id = _graph_with_secret_and_endpoints(tmp_path, manifest_factory, signing_keypair, n_endpoints=1)
    ledger = BudgetLedger(BudgetLimits(validation_attempts=0), config_source="test")

    with patch("kronos.validate.http_validator.validate_api_token") as mock_validate:
        with pytest.raises(BudgetExceeded):
            run_validation_pass(graph, tmp_path, budget=ledger)
        mock_validate.assert_not_called()  # NOT "ran unmetered" — zero charged actions, period

    secret = graph.get_node("SECRET", secret_id)
    assert secret["status"] == "extracted"  # never advanced; the run stopped, it didn't continue degraded


# --- §4 test 3: determinism -----------------------------------------------------

def _run_capped(tmp_path_factory, manifest_factory, signing_keypair, label: str):
    run_dir = tmp_path_factory.mktemp(label)
    graph, _ = _graph_with_secret_and_endpoints(run_dir, manifest_factory, signing_keypair, n_endpoints=3)
    ledger = BudgetLedger(BudgetLimits(validation_attempts=2), config_source="test")
    with patch("kronos.validate.http_validator.validate_api_token") as mock_validate:
        mock_validate.return_value = ValidationOutcome(live=True, evidence=b"proof", detail="200", classification="live_discriminated", discriminated=True)
        with pytest.raises(BudgetExceeded) as excinfo:
            run_validation_pass(graph, run_dir, budget=ledger)
    return excinfo.value.dimension, ledger.snapshot()


def test_determinism_same_graph_same_budget_same_stop_point(
    tmp_path_factory, manifest_factory, signing_keypair
):
    dim1, snap1 = _run_capped(tmp_path_factory, manifest_factory, signing_keypair, "run1")
    dim2, snap2 = _run_capped(tmp_path_factory, manifest_factory, signing_keypair, "run2")

    assert dim1 == dim2 == "validation_attempts"
    assert snap1.stopped_reason == snap2.stopped_reason

    # Identical ledger, clock-based readings aside (real elapsed
    # wall-clock seconds vary run to run exactly like a timestamp does —
    # SPEC_BRIEF5 §4 test 3's own "(timestamps aside)" caveat covers
    # it): every DETERMINISTIC dimension — the one the budget actually
    # capped, and the one the cap never touched — matches exactly, and
    # so does the full entry log for those dimensions, in order.
    deterministic_dims = {"validation_attempts", "tool_invocations"}
    assert {k: v for k, v in snap1.totals.items() if k in deterministic_dims} == {
        k: v for k, v in snap2.totals.items() if k in deterministic_dims
    }
    strip = lambda entries: [
        (e.dimension, e.amount, e.running_total, e.actor, e.detail)
        for e in entries
        if e.dimension in deterministic_dims
    ]
    assert strip(snap1.entries) == strip(snap2.entries)


# --- §4 test 4: wall-clock cap --------------------------------------------------

def test_wall_clock_cap_triggers_a_clean_stop_with_the_right_marker(
    tmp_path, manifest_factory, signing_keypair
):
    graph, secret_id = _graph_with_secret_and_endpoints(tmp_path, manifest_factory, signing_keypair, n_endpoints=1)
    # A deterministic fake clock, not a real sleep: first call (ledger
    # construction) reads 0.0 as the start; the very next call (the
    # first charge's wall-clock assertion) reads 10.0 -> 10s elapsed
    # against a 1s cap, every time, with no timing flakiness.
    readings = iter([0.0, 10.0, 10.0, 10.0])
    ledger = BudgetLedger(BudgetLimits(wall_clock_seconds=1.0), config_source="test", clock=lambda: next(readings))

    with patch("kronos.validate.http_validator.validate_api_token") as mock_validate:
        with pytest.raises(BudgetExceeded) as excinfo:
            run_validation_pass(graph, tmp_path, budget=ledger)
        mock_validate.assert_not_called()  # clean stop before the first attempt, not mid-attempt

    assert excinfo.value.dimension == "wall_clock_seconds"
    snapshot = ledger.snapshot()
    assert snapshot.stopped_reason == "wall_clock_seconds"
    assert stopped_early_marker(snapshot) == "stopped early: budget wall_clock_seconds exhausted"


# --- §4 test 5: missing/invalid budget.yaml -------------------------------------

def test_missing_budget_yaml_falls_back_to_the_conservative_default(tmp_path):
    result = load_budget_limits(tmp_path)
    assert result.source == "default"
    assert result.reason is not None and "not found" in result.reason
    assert result.limits == DEFAULT_BUDGET_LIMITS
    assert result.limits.validation_attempts is not None  # a real ceiling, never unlimited


def test_syntactically_invalid_budget_yaml_falls_back(tmp_path):
    (tmp_path / "budget.yaml").write_text("key: value: another\n")  # not valid YAML (ScannerError)
    result = load_budget_limits(tmp_path)
    assert result.source == "default"
    assert result.limits == DEFAULT_BUDGET_LIMITS
    assert "not valid YAML" in result.reason


def test_non_mapping_budget_yaml_falls_back(tmp_path):
    (tmp_path / "budget.yaml").write_text("- just\n- a\n- list\n")
    result = load_budget_limits(tmp_path)
    assert result.source == "default"
    assert result.limits == DEFAULT_BUDGET_LIMITS


def test_unknown_dimension_in_budget_yaml_falls_back(tmp_path):
    (tmp_path / "budget.yaml").write_text("made_up_dimension: 5\n")
    result = load_budget_limits(tmp_path)
    assert result.source == "default"
    assert "unknown dimension" in result.reason


def test_non_numeric_dimension_value_falls_back(tmp_path):
    (tmp_path / "budget.yaml").write_text("validation_attempts: not_a_number\n")
    result = load_budget_limits(tmp_path)
    assert result.source == "default"
    assert result.limits == DEFAULT_BUDGET_LIMITS


def test_negative_dimension_value_falls_back(tmp_path):
    (tmp_path / "budget.yaml").write_text("validation_attempts: -1\n")
    result = load_budget_limits(tmp_path)
    assert result.source == "default"


def test_valid_partial_budget_yaml_keeps_the_default_for_omitted_dimensions(tmp_path):
    """A VALID but partial file isn't the "missing/invalid" fallback case
    — it's accepted (`source == "file"`) — but a dimension it doesn't
    mention still gets the conservative default, never `None`/unlimited,
    so a run is never unlimited just because an operator's file happened
    not to mention every dimension."""
    (tmp_path / "budget.yaml").write_text("validation_attempts: 7\n")
    result = load_budget_limits(tmp_path)
    assert result.source == "file"
    assert result.reason is None
    assert result.limits.validation_attempts == 7
    assert result.limits.tool_invocations == DEFAULT_BUDGET_LIMITS.tool_invocations
    assert result.limits.wall_clock_seconds == DEFAULT_BUDGET_LIMITS.wall_clock_seconds


def test_explicit_null_in_budget_yaml_is_genuinely_unlimited(tmp_path):
    """The ONLY way to get `None`/unlimited for a dimension out of the
    loader: an operator writing `null` themselves — never an accident
    of a missing key or a missing file."""
    (tmp_path / "budget.yaml").write_text("tool_invocations: null\n")
    result = load_budget_limits(tmp_path)
    assert result.source == "file"
    assert result.limits.tool_invocations is None
    assert result.limits.validation_attempts == DEFAULT_BUDGET_LIMITS.validation_attempts


# --- §4 test 6: non-interference ------------------------------------------------

def test_full_pipeline_with_generous_budget_is_a_pure_passthrough(tmp_path, manifest_factory, signing_keypair):
    """Mirrors `cybergym/kronos_validation_run.py`'s own pipeline shape
    (ingest -> reconcile -> validate) without needing the live
    docker-backed range: a generous budget must change NOTHING about the
    outcome, and the ledger must show real, non-zero consumption safely
    below every ceiling — not "ran out of things to charge," but "spent
    less than it was allowed to.\""""
    _, pub = signing_keypair
    manifest_text = manifest_factory(scope={"in_scope": ["*"], "excluded": []})
    graph = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_text, pub)

    graph.upsert_node("MOBILE_APP", "com.acme.app", {"bundle_id": "com.acme.app", "platform": "android", "source": "static"})
    info = store_evidence(tmp_path, b"pipeline-secret", kind="mobile_secret")
    secret_id = f"secret:{info['sha256'][:16]}"
    graph.upsert_node(
        "SECRET", secret_id,
        {"value_ref": "sha256:" + info["sha256"], "kind": "api_key", "status": "extracted", "source": "static"},
        scope_key="com.acme.app",
    )
    graph.upsert_edge("leaks", "com.acme.app", "MOBILE_APP", secret_id, "SECRET")
    graph.upsert_node("API_ENDPOINT", "http://api.acme.example.com", {"source": "static"})
    graph.upsert_edge("references", "com.acme.app", "MOBILE_APP", "http://api.acme.example.com", "API_ENDPOINT")

    assert run_reconciliation_pass(graph, tmp_path, pass_name="post_ingest").is_empty()

    ledger = BudgetLedger(BudgetLimits(validation_attempts=500, tool_invocations=1000, wall_clock_seconds=3600.0), config_source="test")
    with patch("kronos.validate.http_validator.validate_api_token") as mock_validate:
        mock_validate.return_value = ValidationOutcome(live=True, evidence=b"proof", detail="200", classification="live_discriminated", discriminated=True)
        run_validation_pass(graph, tmp_path, budget=ledger)  # must NOT raise

    assert graph.get_node("SECRET", secret_id)["status"] == "reachable"

    snapshot = ledger.snapshot()
    assert snapshot.stopped_reason is None
    assert stopped_early_marker(snapshot) is None
    for dimension, ceiling in (("validation_attempts", 500), ("tool_invocations", 1000)):
        assert 0 < snapshot.totals[dimension] < ceiling  # real consumption, comfortably under the ceiling
    assert snapshot.totals["wall_clock_seconds"] < 3600.0


# --- §4 test 7: audit ------------------------------------------------------------

def test_ledger_snapshot_is_written_queryable_and_append_only(tmp_path, manifest_factory, signing_keypair):
    import json

    graph, secret_id = _graph_with_secret_and_endpoints(tmp_path, manifest_factory, signing_keypair, n_endpoints=1)
    ledger = BudgetLedger(BudgetLimits(validation_attempts=10), config_source="test")

    with patch("kronos.validate.http_validator.validate_api_token") as mock_validate:
        mock_validate.return_value = ValidationOutcome(live=True, evidence=b"proof", detail="200", classification="live_discriminated", discriminated=True)
        run_validation_pass(graph, tmp_path, budget=ledger)

    path = write_ledger_snapshot(tmp_path, ledger)
    assert path.exists()
    parsed = json.loads(path.read_text())  # queryable/parseable
    assert parsed["stopped_reason"] is None
    n_entries_first_write = len(parsed["entries"])
    assert n_entries_first_write >= 1

    # append-only in-memory log: a second charge only ever grows it.
    ledger.charge("tool_invocations", 1, actor="test", detail="extra")
    write_ledger_snapshot(tmp_path, ledger)
    parsed2 = json.loads(path.read_text())
    assert len(parsed2["entries"]) == n_entries_first_write + 1
    assert parsed2["entries"][:n_entries_first_write] == parsed["entries"]  # prior entries never rewritten


def test_stopped_early_marker_present_only_when_tripped(tmp_path, manifest_factory, signing_keypair):
    graph, secret_id = _graph_with_secret_and_endpoints(tmp_path, manifest_factory, signing_keypair, n_endpoints=2)
    ledger = BudgetLedger(BudgetLimits(validation_attempts=1), config_source="test")

    with patch("kronos.validate.http_validator.validate_api_token") as mock_validate:
        mock_validate.return_value = ValidationOutcome(live=True, evidence=b"proof", detail="200", classification="live_discriminated", discriminated=True)
        with pytest.raises(BudgetExceeded):
            run_validation_pass(graph, tmp_path, budget=ledger)

    marker = stopped_early_marker(ledger.snapshot())
    assert marker == "stopped early: budget validation_attempts exhausted"


def test_config_fallback_reason_is_recorded_on_the_ledger_for_the_audit_trail(tmp_path):
    config_result = load_budget_limits(tmp_path)  # no budget.yaml -> fallback
    ledger = BudgetLedger(config_result.limits, config_source=config_result.source, config_reason=config_result.reason)
    snapshot = ledger.snapshot()
    assert snapshot.config_source == "default"
    assert snapshot.config_reason is not None and "not found" in snapshot.config_reason


# --- §4 test 8: guardrail diffs --------------------------------------------------

# Re-pinned from tests/test_reconcile.py's own guardrail-1 test — this
# brief must re-confirm scope_guard.py is STILL a zero-line diff, not
# just trust that an earlier brief's pin still holds.
_SCOPE_GUARD_SHA256 = "41e56781c2f05fa28b4071e616364223094804d8f6d99fe0985414787ae7bde0"


def test_scope_guard_still_has_zero_line_diff():
    scope_guard_path = Path(kronos.__file__).parent / "scope_guard.py"
    digest = hashlib.sha256(scope_guard_path.read_bytes()).hexdigest()
    assert digest == _SCOPE_GUARD_SHA256, "scope_guard.py changed — FORK-2 must stay untouched"


def test_budget_module_never_calls_advance_secret_status():
    """Budget enforcement wraps AROUND validation (guardrail 2) — it
    must never reach into the one forward-mutator chokepoint itself.
    `tests/test_reconcile.py::test_advance_secret_status_still_called_only_by_the_validation_runner`
    already re-walks the WHOLE `src/kronos` tree (this module included)
    and would fail if that ever changed; this is the budget-scoped
    version of the same proof, kept local to this brief's own tests."""
    root = Path(kronos.__file__).parent / "budget"
    for path in root.rglob("*.py"):
        assert "advance_secret_status(" not in path.read_text(), (
            f"{path} calls advance_secret_status — budget enforcement must only ever "
            "wrap around validation, never write status itself"
        )
