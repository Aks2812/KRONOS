"""The owned event stream (SPEC_BRIEF9 §6 / FORK-Q): a deterministic,
append-only record of what a run did, so an operator who stepped away
can see it and a reviewer can audit it.

One chokepoint, `emit`, appends one JSON object per line to
`events.jsonl` in the engagement directory (FORK-Q DEFAULT: a plain
file, not a Kùzu table — the graph is the findings model, not an
operational log, and a file is trivially greppable/diffable). Append-
only: opened in append mode, never truncated or rewritten.

Event kinds for SPEC_BRIEF9, and no more (validation/budget events are
a later brief, not added speculatively here):
`ingest_started`, `ingest_finished`, `ingest_declined`,
`reconcile_merged`, `reconcile_skipped_uncertain_key`.

Same rule as evidence blobs (kronos.evidence): no secret value and no
raw tool output in any event — callers pass counts/ids/reasons, never
material.

Writing an event must never be able to fail the run: an unwritable
stream (permission error, missing directory, non-serializable field)
degrades to a logged warning. Contrast the budget ledger
(kronos.budget), which IS load-bearing and fails closed by design —
observability is not allowed to break the engagement the same way.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EVENTS_FILENAME = "events.jsonl"

# The only kinds this brief defines. `emit` rejects anything else by
# construction, so a future brief's validation/budget events can't
# accidentally slip in here before they have their own section.
ALLOWED_KINDS: frozenset[str] = frozenset(
    {
        "ingest_started",
        "ingest_finished",
        "ingest_declined",
        "reconcile_merged",
        "reconcile_skipped_uncertain_key",
    }
)


def emit(stream: str | Path, kind: str, **fields: Any) -> None:
    """Append one event to `events.jsonl` under the engagement directory
    named by `stream`. Never raises: a bad `kind` is a caller bug (raised
    immediately, same as any other programming error), but every
    environmental failure after that point — an unwritable path, a
    non-JSON-serializable field — degrades to a logged warning and the
    run continues."""
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"unknown event kind {kind!r}; see events.ALLOWED_KINDS")

    record: dict[str, Any] = {"kind": kind, "timestamp": datetime.now(timezone.utc).isoformat(), **fields}

    try:
        line = json.dumps(record, sort_keys=True)
    except (TypeError, ValueError) as exc:
        logger.warning("events: could not serialize %s event: %s", kind, exc)
        return

    path = Path(stream) / _EVENTS_FILENAME
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        logger.warning("events: could not write %s event to %s: %s", kind, path, exc)
