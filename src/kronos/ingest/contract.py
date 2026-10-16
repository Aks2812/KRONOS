"""The formal ingestion-source contract (SPEC_BRIEF9 §3): what any
present or future source must satisfy. Formalizes a shape
`ingest_mobile_static` already holds by convention — the goal is a
named, importable contract, not a redesign.

An ingestion source takes its own input (a file path, an API response,
whatever is natural for it) and returns an `IngestPlan`: a declarative
list of `NodeUpsert`/`EdgeUpsert` plus an `IngestReport`. It never holds
a graph handle for writing and never calls `upsert_node`/`upsert_edge`
itself — `apply_plan` below is the only thing that does, so scope-
gating (`EngagementGraph.upsert_node`'s `ScopeGuard` call) and prop-
allowlisting (`schema.py`'s `NODE_PROPS_*` sets) happen in exactly one
place for every source, present and future.

Guardrail 4 (SPEC_BRIEF9 §1): scope is decided by `scope_guard` via
`upsert_node`, never by an ingestion source — no `NodeUpsert` built by a
conforming source may carry `in_scope` and no source may compute it;
`apply_plan`/`apply_upserts` never accept it either (schema.py's
`NODE_PROPS_FORBIDDEN`, enforced inside `EngagementGraph.upsert_node`
itself — the same backstop Brief #1 already relies on).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from kronos.ingest import EdgeUpsert, NodeUpsert, apply_upserts

if TYPE_CHECKING:  # pragma: no cover
    from kronos.graph import EngagementGraph


@dataclass(frozen=True)
class SourceDescriptor:
    """A stable identity for one ingestion source, written into each
    planned node's existing `source` column (so provenance is queryable
    and two sources that disagree on the same id are distinguishable) —
    see each source's own docstring for exactly what it writes there.
    `version` is reported alongside the plan (in `IngestReport`/events),
    not necessarily folded into the `source` string itself: a source
    adapting an already-shipped node-prop contract keeps that column's
    existing value exactly as it was (see `mobile/parser.py`'s
    `MOBILE_STATIC_SOURCE` for the worked example)."""

    name: str
    version: str


@dataclass(frozen=True)
class DeclinedItem:
    """One input item a source deliberately chose not to emit anything
    for (SPEC_BRIEF9 §3: "declining is a first-class outcome, not
    silence") — e.g. unparseable input, a required field missing.
    `detail` is a short, secret-free description, never raw input."""

    reason: str
    detail: str = ""


@dataclass(frozen=True)
class IngestReport:
    """Counts of what a plan contains, by node/edge type, plus every
    item the source declined and why. Never carries raw tool output or
    secret material — counts and reasons only."""

    source: SourceDescriptor
    node_counts: dict[str, int] = field(default_factory=dict)
    edge_counts: dict[str, int] = field(default_factory=dict)
    declined: tuple[DeclinedItem, ...] = ()


@dataclass(frozen=True)
class IngestPlan:
    """What a conforming source returns: the plan itself (unchanged
    shape from Brief #1 — `NodeUpsert`/`EdgeUpsert`) plus the report
    describing it. A source never writes; `apply_plan` is the only
    thing that turns this into graph calls."""

    upserts: tuple[NodeUpsert | EdgeUpsert, ...]
    report: IngestReport


@runtime_checkable
class IngestionSource(Protocol):
    """Structural contract: a conforming source is simply a callable
    that, given whatever input is natural for it, returns an
    `IngestPlan`. Deliberately loose on the input side (SPEC_BRIEF9 §3:
    "it takes its own input") — a mobile-static source takes an APK
    path, a future HTTP-traffic source would take a capture file, and
    neither shape should be forced to match the other's."""

    def __call__(self, *args: Any, **kwargs: Any) -> IngestPlan: ...


def build_report(
    source: SourceDescriptor,
    upserts: list[NodeUpsert | EdgeUpsert],
    declined: list[DeclinedItem] | None = None,
) -> IngestReport:
    """Count a plan's upserts by type — the one place this counting
    logic lives, so every conforming source reports consistently."""
    node_counts: dict[str, int] = {}
    edge_counts: dict[str, int] = {}
    for item in upserts:
        if isinstance(item, NodeUpsert):
            node_counts[item.type] = node_counts.get(item.type, 0) + 1
        elif isinstance(item, EdgeUpsert):
            edge_counts[item.label] = edge_counts.get(item.label, 0) + 1
    return IngestReport(
        source=source,
        node_counts=node_counts,
        edge_counts=edge_counts,
        declined=tuple(declined or ()),
    )


def apply_plan(graph: "EngagementGraph", plan: IngestPlan) -> None:
    """The only thing that turns an `IngestPlan` into graph writes —
    delegates to `kronos.ingest.apply_upserts`, which remains the
    underlying write path so every pre-existing caller (including the
    `ingest()` dispatcher's legacy bare-list contract, still depended on
    by `cybergym/kronos_validation_run.py`, out of this brief's
    allowlist) keeps working unchanged. `apply_plan` and `apply_upserts`
    are jointly the sole graph-writing chokepoint under `ingest/` —
    see `tests/test_ingest_contract.py`'s non-vacuous guard, which
    exempts exactly these two names and nothing else."""
    apply_upserts(graph, list(plan.upserts))
