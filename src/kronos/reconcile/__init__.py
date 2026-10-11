"""Reconciliation / dedup (SPEC_BRIEF4): collapses different node IDs
that denote the same real-world entity once a second ingestion source
starts feeding the graph, so validation never runs twice on the same
secret and a dead twin never leaks a `reachable` finding into a report.

Deterministic canonical keys only (`canonical.py`) — no LLM, no
similarity scoring. `run_reconciliation_pass` (`runner.py`) is the one
entry point other modules call; `merge.py` is its internal mechanics.
"""

from __future__ import annotations

from kronos.reconcile.merge import MergeRecord, MergeReport
from kronos.reconcile.runner import run_reconciliation_pass

__all__ = ["run_reconciliation_pass", "MergeReport", "MergeRecord"]
