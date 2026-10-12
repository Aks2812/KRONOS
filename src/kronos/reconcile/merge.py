"""The merge operation (SPEC_BRIEF4 §3.2, hardened by SPEC_BRIEF4.1) —
the FP-critical part of reconciliation. Given a set of >=2 node ids of
the same type sharing a canonical key, folds the "losers" into one
deterministic "survivor":

  1. Carry over every edge (incoming and outgoing, every label a loser
     participates in) from each loser onto the survivor, de-duped by
     Kùzu's own `MERGE` semantics (same `upsert_edge` every ingester uses).
  2. For SECRET specifically: recompute status from the survivor's
     now-merged evidence (`lifecycle.set_secret_status_from_evidence`) —
     NEVER copy/max the input statuses. This is guardrail 3, the single
     most important rule in SPEC_BRIEF4.
  3. Move-don't-copy (SPEC_BRIEF4.1 §2 / FORK-C DEFAULT): delete every
     relationship still on each loser, now that the survivor holds the
     union. A tombstone that keeps its original edges is still fully
     live to `find_paths` and any other traversal — this is what makes
     it genuinely inert, localized here rather than as a `merged_into`
     filter every current and future reader has to remember.
  4. Tombstone each loser (FORK-A's DEFAULT: never hard-delete). SECRET
     and FINDING already own a `status` column, so they also get
     `status="merged"` per FORK-A's literal wording; every mergeable type
     gets `merged_into=<survivor_id>` (SPEC_BRIEF4 schema touch — see
     DECISIONS.md and the PR description for why this column was added).
  5. Return a `MergeRecord` for the audit trail (`MergeReport`).

Status-bearing types are the only ones with special-cased status
handling; HOST/API_ENDPOINT/MOBILE_APP have no status column at all and
are tombstoned via `merged_into` alone. FINDING additionally has no
evidence-recompute path yet (see `merge_group`'s guard below) — it is
not a mergeable type in practice until that lands.
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


def _delete_loser_edges(graph: "EngagementGraph", node_type: str, loser_id: str) -> None:
    """SPEC_BRIEF4.1 §2 Fix #1 / FORK-C DEFAULT (move-don't-copy): once
    `_carry_over_edges` has re-created every one of the loser's edges on
    the survivor, delete the loser's own relationships so it becomes a
    genuinely edgeless tombstone — inert to `find_paths` and any other
    traversal, not just to a consumer that remembers to filter
    `merged_into`. Confirmed empirically that this Kùzu build supports
    `DELETE` on a matched relationship pattern without touching the
    node itself (see PR discussion); same `EDGE_PAIRS` walk as the
    carry-over, both directions, so every label/pair this node type can
    participate in is covered."""
    for label, pairs in EDGE_PAIRS.items():
        for frm, to in pairs:
            if frm == node_type:
                graph.execute(
                    f"MATCH (a:{frm} {{id: $id}})-[r:{label}]->(b:{to}) DELETE r",
                    {"id": loser_id},
                )
            if to == node_type:
                graph.execute(
                    f"MATCH (a:{frm})-[r:{label}]->(b:{to} {{id: $id}}) DELETE r",
                    {"id": loser_id},
                )


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

    if node_type == "FINDING":
        # SPEC_BRIEF4.1 §3 Fix #2: a real FINDING group must never
        # silently settle on the arbitrary min-id survivor's status with
        # no evidence recompute behind it — that's a false-negative
        # landmine (a real `exploited` finding quietly downgraded) that
        # would only ever fire once a later brief populates
        # `location_sig` and nobody revisits this function. Loud refusal
        # now, by construction, until FINDING gets its own
        # evidence-recompute path (its `exploited`->`reported` rules
        # differ from SECRET's). `canonical_key_for_finding` and
        # `runner._group_findings` stay wired in — they correctly yield
        # nothing today; this is the backstop for the day they don't.
        raise NotImplementedError(
            "FINDING reconciliation has no evidence-recompute path yet — see "
            "SPEC_BRIEF4.1 §3. A >=2 FINDING group must not merge until that lands."
        )

    # Deterministic survivor (SPEC_BRIEF4 §3.2: "lowest/oldest ID, so
    # merges are reproducible") — plain lexicographic min on the id
    # string, same determinism guarantee regardless of insertion order.
    survivor_id = min(member_ids)
    losers = sorted(mid for mid in member_ids if mid != survivor_id)

    carried_statuses: list[str] | None = None
    if node_type == "SECRET":
        carried_statuses = [graph.get_node(node_type, mid)["status"] for mid in member_ids]

    # Carry over every loser's edges BEFORE deleting any of them (not
    # interleaved per-loser): a 3+-way merge can have edges between two
    # losers, and carrying all of them over first — even a transient,
    # spurious survivor<->loser edge along the way — guarantees every
    # real external edge reaches the survivor exactly once, with the
    # cleanup (below) removing anything left dangling on a loser
    # regardless of which order the losers were processed in.
    for loser_id in losers:
        _carry_over_edges(graph, node_type, loser_id, survivor_id)

    if node_type == "SECRET":
        # Guardrail 3: recompute from the NOW-merged evidence, never copy
        # the carried statuses directly. Must run AFTER edge carry-over
        # (so it sees the survivor's union of `evidences` edges) and
        # BEFORE the losers' edges are deleted below — deleting a
        # loser's edges afterward doesn't change what the survivor
        # already carries, so recomputing first vs. after makes no
        # difference here, but SPEC_BRIEF4.1 §2 pins this order anyway.
        set_secret_status_from_evidence(graph, survivor_id, carried_statuses)

    # SPEC_BRIEF4.1 §2 Fix #1 / FORK-C DEFAULT: move-don't-copy. Every
    # loser's own relationships are deleted now that the survivor holds
    # the union — this is what makes a tombstone genuinely inert to
    # `find_paths` and any other traversal, localized here rather than
    # as a `merged_into` filter scattered across every reader.
    for loser_id in losers:
        _delete_loser_edges(graph, node_type, loser_id)

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
