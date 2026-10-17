"""SPEC_BRIEF6 §4's acceptance tests for the engagement cleanup/teardown
registry: LIFO order, teardown-on-exception, teardown surviving a
BudgetExceeded (the key cross-module test), idempotence, partial
failure reporting, credential shredding, the docker-kind teardown
callables, and the guardrail diffs. (§4 test 7 — the live CyberGym
end-to-end confirmation — needs the real docker-backed range and is
exercised by actually running `cybergym/kronos_validation_run.py`, not
here; see the PR report.)
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import kronos
from kronos.budget import BudgetExceeded, BudgetLedger, BudgetLimits
from kronos.cleanup import CleanupRegistry, TeardownReport, write_teardown_report
from kronos.cleanup.kinds import (
    compose_down,
    remove_container,
    remove_file,
    shred_credential_file,
)


# --- §4 test 1: LIFO teardown ---------------------------------------------------

def test_lifo_teardown_order():
    order: list[str] = []
    registry = CleanupRegistry()
    registry.register("filesystem", "a", lambda: order.append("a"))
    registry.register("filesystem", "b", lambda: order.append("b"))
    registry.register("filesystem", "c", lambda: order.append("c"))

    report = registry.teardown_all()

    assert order == ["c", "b", "a"]  # reverse of registration order
    assert report.all_ok
    assert [item.outcome for item in report.items] == ["done", "done", "done"]


# --- §4 test 2: teardown on exception -------------------------------------------

def test_teardown_runs_on_exception_and_the_exception_still_propagates():
    disposed: list[str] = []
    registry = CleanupRegistry()

    with pytest.raises(ValueError, match="boom"):
        with registry:
            registry.register("filesystem", "f1", lambda: disposed.append("f1"))
            registry.register("filesystem", "f2", lambda: disposed.append("f2"))
            raise ValueError("boom")

    assert disposed == ["f2", "f1"]  # LIFO, and it ran despite the raise
    assert registry.last_report is not None
    assert registry.last_report.all_ok


# --- §4 test 3: teardown after budget exhaustion (key cross-module test) -------

def test_teardown_runs_even_when_budget_is_exhausted(tmp_path):
    """Guardrail 3, the key cross-module rule: a `BudgetExceeded`
    raised mid-engagement must still result in full teardown and a
    written `TeardownReport` — cleanup is NOT gated by budget. The
    `CleanupRegistry` context manager doesn't special-case
    `BudgetExceeded` at all; it's just "the body raised," which is
    exactly what makes this guardrail true without any budget-aware
    code inside `kronos.cleanup`."""
    disposed: list[str] = []
    registry = CleanupRegistry()
    registry.register("docker", "range-stack", lambda: disposed.append("range-stack"), detail="range-stack")

    ledger = BudgetLedger(BudgetLimits(tool_invocations=0), config_source="test")

    with pytest.raises(BudgetExceeded):
        with registry:
            registry.register("filesystem", "scratch-file", lambda: disposed.append("scratch-file"), detail="scratch-file")
            ledger.charge("tool_invocations", 1, actor="test")  # raises BudgetExceeded

    assert disposed == ["scratch-file", "range-stack"]  # teardown ran fully, LIFO
    assert registry.last_report is not None
    assert registry.last_report.all_ok

    path = write_teardown_report(tmp_path, registry.last_report)
    assert path.exists()


# --- §4 test 4: idempotent -------------------------------------------------------

def test_teardown_all_twice_is_safe_and_already_gone_is_not_a_failure(tmp_path):
    target = tmp_path / "scratch.txt"
    target.write_text("x")
    registry = CleanupRegistry()
    registry.register("filesystem", str(target), remove_file(target), detail=str(target))

    # Something else removed it before teardown ever ran -> already_gone,
    # not failed.
    target.unlink()
    report1 = registry.teardown_all()
    assert report1.all_ok
    assert report1.items[0].outcome == "already_gone"

    # A second teardown_all() call is a no-op: the registry itself
    # remembers the artifact is already disposed and never re-invokes
    # the (now-pointless) teardown callable.
    report2 = registry.teardown_all()
    assert report2.all_ok
    assert report2.items[0].outcome == "already_gone"


# --- §4 test 5: partial failure reported, not fatal -----------------------------

def test_partial_failure_is_reported_and_does_not_block_the_rest():
    disposed: list[str] = []

    def _boom() -> None:
        raise RuntimeError("disk gremlin")

    registry = CleanupRegistry()
    registry.register("filesystem", "a", lambda: disposed.append("a"))
    registry.register("docker", "broken-container", _boom, detail="broken-container")
    registry.register("filesystem", "b", lambda: disposed.append("b"))

    report = registry.teardown_all()  # must not raise

    assert disposed == ["b", "a"]  # the other two ran despite the middle one failing
    assert not report.all_ok
    assert len(report.failures) == 1
    assert report.failures[0].kind == "docker"
    assert report.failures[0].detail == "broken-container"
    assert "disk gremlin" in report.failures[0].error


# --- §4 test 6: credential shred -------------------------------------------------

def test_credential_file_is_actually_removed_from_disk(tmp_path):
    cred_path = tmp_path / "temp_cred.txt"
    cred_path.write_text("super-secret-value")
    registry = CleanupRegistry()
    registry.register("credential", str(cred_path), shred_credential_file(cred_path), detail=str(cred_path))

    report = registry.teardown_all()

    assert not cred_path.exists()  # not just logged -- genuinely gone
    assert report.items[0].outcome == "done"


def test_credential_shred_on_already_missing_file_is_already_gone(tmp_path):
    cred_path = tmp_path / "already_gone_cred.txt"
    registry = CleanupRegistry()
    registry.register("credential", str(cred_path), shred_credential_file(cred_path))

    report = registry.teardown_all()

    assert report.all_ok
    assert report.items[0].outcome == "already_gone"


# --- docker-kind teardown callables (support for §4 test 7's real integration) --

def test_remove_container_treats_no_such_container_as_already_gone():
    with patch("kronos.cleanup.kinds.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="Error: No such container: foo")
        outcome = remove_container("foo")()
    assert outcome == "already_gone"


def test_remove_container_raises_on_a_real_docker_failure():
    with patch("kronos.cleanup.kinds.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="permission denied")
        with pytest.raises(RuntimeError):
            remove_container("foo")()


def test_remove_container_success_reports_done():
    with patch("kronos.cleanup.kinds.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        outcome = remove_container("foo")()
    assert outcome is None


def test_compose_down_wraps_an_existing_compose_helper():
    calls: list[tuple] = []

    def fake_compose(*args: str) -> None:
        calls.append(args)

    outcome = compose_down(fake_compose)()

    assert calls == [("down", "-v")]
    assert outcome is None


# --- TeardownReport serialization ------------------------------------------------

def test_teardown_report_round_trips_through_json(tmp_path):
    import json

    registry = CleanupRegistry()
    registry.register("filesystem", "a", lambda: None, detail="a")
    report = registry.teardown_all()

    path = write_teardown_report(tmp_path, report)
    parsed = json.loads(path.read_text())
    assert parsed["all_ok"] is True
    assert parsed["items"][0]["kind"] == "filesystem"
    assert parsed["items"][0]["outcome"] == "done"


# --- §4 test 8: guardrail diffs --------------------------------------------------

# Re-pinned by SPEC_BRIEF10 (the dedicated FORK-2 brief) after its
# deliberate, in-scope rewrite of scope_guard.py; see tests/test_reconcile.py.
#
# Re-pinned again by SPEC_BRIEF10.1 (amends PR #12, pre-merge) after its
# own deliberate, in-scope trailing-glob boundary-rule rewrite of
# scope_guard.py; see tests/test_reconcile.py.
#
# Re-pinned again by SPEC_BRIEF10.2 (amends PR #12, pre-merge) after its
# own deliberate, in-scope fix routing scheme://host:port* URL patterns
# through a structural host/port comparison instead of raw-string
# prefix matching; see tests/test_reconcile.py.
_SCOPE_GUARD_SHA256 = "7bee515a261dbb5e88d9146596ccedb639cbef0c997b00754453e69f5eaccee3"


def test_scope_guard_still_has_zero_line_diff():
    scope_guard_path = Path(kronos.__file__).parent / "scope_guard.py"
    digest = hashlib.sha256(scope_guard_path.read_bytes()).hexdigest()
    assert digest == _SCOPE_GUARD_SHA256, "scope_guard.py changed — re-pin or get sign-off (SPEC_BRIEF10 already re-pinned once)"


def test_cleanup_module_never_calls_advance_secret_status():
    root = Path(kronos.__file__).parent / "cleanup"
    for path in root.rglob("*.py"):
        assert "advance_secret_status(" not in path.read_text(), (
            f"{path} calls advance_secret_status — cleanup must never touch the lifecycle mutator"
        )


def test_cleanup_module_is_budget_exempt_mechanically():
    """FORK-F's DEFAULT (exempt), proven mechanically rather than by
    convention: nothing under `src/kronos/cleanup/` actually IMPORTS
    `kronos.budget` or calls a `.charge(...)` method, so no teardown
    path can ever be blocked by `BudgetExceeded` (guardrail 3). Checks
    real import statements line-by-line (not a bare substring match)
    so this module's own docstrings are free to explain the exemption
    in prose without tripping the guardrail on themselves."""
    root = Path(kronos.__file__).parent / "cleanup"
    for path in root.rglob("*.py"):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            assert not stripped.startswith("import kronos.budget") and not stripped.startswith("from kronos.budget"), (
                f"{path}: {line!r} imports kronos.budget — cleanup must stay budget-exempt"
            )
            assert ".charge(" not in line, f"{path}: {line!r} calls .charge(...) — teardown must never be blockable by BudgetExceeded"
