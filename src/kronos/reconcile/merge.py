"""The merge operation (SPEC_BRIEF4 §3.2) — the FP-critical part of
reconciliation. Given a set of >=2 node ids of the same type sharing a
canonical key, folds the "losers" into one deterministic "survivor":

  1. Carry over every edge (incoming and outgoing, every label a loser
     participates in) from each loser onto the survivor, de-duped by
     Kùzu's own `MERGE` semantics (same `upsert_edge` every ingester uses).
  2. For SECRET specifically: recompute status from the survivor's
     now-merged evidence (`lifecycle.set_secret_status_from_evidence`) —
     NEVER copy/max the input statuses. This is guardrail 3, the single
     most important rule in SPEC_BRIEF4.
  3. Tombstone each loser (FORK-A's DEFAULT: never hard-delete). SECRET
     and FINDING already own a `status` column, so they also get
     `status="merged"` per FORK-A's literal wording; every mergeable type
     gets `merged_into=<survivor_id>` (SPEC_BRIEF4 schema touch — see
     DECISIONS.md and the PR description for why this column was added).
  4. Return a `MergeRecord` for the audit trail (`MergeReport`).

Status-bearing types are the only ones with special-cased status
handling; HOST/API_ENDPOINT/MOBILE_APP have no status column at all and
are tombstoned via `merged_into` alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from kronos.lifecycle import set_secret_status_from_evidence
from kronos.schema import EDGE_PAIRS

if TYPE_CHECKING:  # pragma: no cover
    from kronos.graph import EngagementGraph

# Node types whose schema (schema.py) already carries a `status` column —
# FORK-A's tombstone sets `status="merged"` on these IN ADDITION TO
# `merged_into`; every other mergeable type (no status column) is
# tombstoned via `merged_into` alone.
_STATUS_BEARING_TYPES = {"SECRET", "FINDING"}


@dataclass(frozen=True)
class MergeRecord:
    """One audit-trail entry (SPEC_BRIEF4 §3.2 point 4 / §4 test 7):
    survivor id, every id merged into it, the canonical key that matched,
    which reconciliation pass produced it, and when."""

    node_type: str
    canonical_key: str
    survivor_id: str
    merged_ids: tuple[str, ...]
    pass_name: str
    timestamp: str


@dataclass(frozen=True)
class MergeReport:
    """`run_reconciliation_pass`'s return value. Idempotent passes
    produce an empty `merges` list (SPEC_BRIEF4 §4 test 4)."""

    merges: list[MergeRecord]

    def is_empty(self) -> bool:
        return not self.merges


def _rows(result) -> list[tuple]:
    out = []
    while result.has_next():
        out.append(tuple(result.get_next()))
    return out


def _carry_over_edges(graph: "EngagementGraph", node_type: str, loser_id: str, survivor_id: str) -> None:
    """Every edge label/pair this node type participates in, either end,
    re-pointed from `loser_id` to `survivor_id`. `graph.upsert_edge` MERGEs,
    so an edge the survivor already has (e.g. both members leaked from the
    same app) is a no-op, not a duplicate — the de-dup SPEC_BRIEF4 §3.2
    point 1 asks for comes straight from that existing, already-idempotent
    write path, not from new bookkeeping here."""
    for label, pairs in EDGE_PAIRS.items():
        for frm, to in pairs:
            if frm == node_type:
                result = graph.execute(
                    f"MATCH (a:{frm} {{id: $id}})-[:{label}]->(b:{to}) RETURN b.id",
                    {"id": loser_id},
                )
                for (other_id,) in _rows(result):
                    if other_id == survivor_id:
                        continue
                    graph.upsert_edge(label, survivor_id, frm, other_id, to)
            if to == node_type:
                result = graph.execute(
                    f"MATCH (a:{frm})-[:{label}]->(b:{to} {{id: $id}}) RETURN a.id",
                    {"id": loser_id},
                )
                for (other_id,) in _rows(result):
                    if other_id == survivor_id:
                        continue
                    graph.upsert_edge(label, other_id, frm, survivor_id, to)


def _tombstone(graph: "EngagementGraph", node_type: str, loser_id: str, survivor_id: str) -> None:
    if node_type in _STATUS_BEARING_TYPES:
        graph.execute(
            f"MATCH (n:{node_type} {{id: $id}}) SET n.status = 'merged', n.merged_into = $survivor",
            {"id": loser_id, "survivor": survivor_id},
        )
    else:
        graph.execute(
            f"MATCH (n:{node_type} {{id: $id}}) SET n.merged_into = $survivor",
            {"id": loser_id, "survivor": survivor_id},
        )


def merge_group(
    graph: "EngagementGraph",
    node_type: str,
    member_ids: list[str],
    canonical_key: str,
    pass_name: str,
) -> MergeRecord | None:
    """Merge one canonical-key group of a single node type. Returns
    `None` (no-op, no record) for a singleton group — reconciliation only
    ever touches a node that actually has a duplicate; an untouched node's
    status/evidence is never re-derived just because a pass ran."""
    if len(member_ids) < 2:
        return None

    # Deterministic survivor (SPEC_BRIEF4 §3.2: "lowest/oldest ID, so
    # merges are reproducible") — plain lexicographic min on the id
    # string, same determinism guarantee regardless of insertion order.
    survivor_id = min(member_ids)
    losers = sorted(mid for mid in member_ids if mid != survivor_id)

    carried_statuses: list[str] | None = None
    if node_type in _STATUS_BEARING_TYPES:
        carried_statuses = [graph.get_node(node_type, mid)["status"] for mid in member_ids]

    for loser_id in losers:
        _carry_over_edges(graph, node_type, loser_id, survivor_id)

    if node_type == "SECRET":
        # Guardrail 3: recompute from the NOW-merged evidence, never copy
        # the carried statuses directly. Must run AFTER edge carry-over so
        # it sees the survivor's union of `evidences` edges.
        set_secret_status_from_evidence(graph, survivor_id, carried_statuses)

    for loser_id in losers:
        _tombstone(graph, node_type, loser_id, survivor_id)

    return MergeRecord(
        node_type=node_type,
        canonical_key=canonical_key,
        survivor_id=survivor_id,
        merged_ids=tuple(losers),
        pass_name=pass_name,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
