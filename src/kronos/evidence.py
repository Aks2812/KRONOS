"""Hash-addressed, immutable evidence blobs (SPEC.md "EVIDENCE" node).

`store_evidence`/`get_evidence` manage the on-disk blob by its sha256;
`attach_evidence` wires that blob into the graph as an EVIDENCE node with
an `evidences` edge to the FINDING or SECRET it supports. Evidence is the
only thing that lets `lifecycle.py` move a FINDING to `reported` — "no
evidence, no report."
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:  # pragma: no cover - avoids a runtime import cycle with graph.py
    from kronos.graph import EngagementGraph


def _evidence_path(engagement_dir: str | Path, sha256: str) -> Path:
    return Path(engagement_dir) / "evidence" / sha256


def store_evidence(engagement_dir: str | Path, blob: bytes, kind: str) -> dict[str, Any]:
    """Write `blob` content-addressed by its sha256. Idempotent and immutable:
    writing the same content twice is a no-op; writing different content
    under a hash that's already on disk (which should be impossible given
    content-addressing) raises ValueError rather than silently overwriting.
    """
    sha256 = hashlib.sha256(blob).hexdigest()
    path = _evidence_path(engagement_dir, sha256)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        existing = path.read_bytes()
        if existing != blob:
            raise ValueError(f"evidence blob at {path} does not match its own hash {sha256}")
    else:
        path.write_bytes(blob)

    return {
        "sha256": sha256,
        "blob_path": str(path),
        "kind": kind,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def get_evidence(engagement_dir: str | Path, sha256: str) -> bytes:
    path = _evidence_path(engagement_dir, sha256)
    if not path.exists():
        raise FileNotFoundError(f"no evidence blob for sha256 {sha256!r}")
    return path.read_bytes()


def attach_evidence(
    graph: "EngagementGraph",
    engagement_dir: str | Path,
    blob: bytes,
    kind: str,
    target_type: Literal["finding", "secret"],
    target_id: str,
) -> str:
    """Store `blob`, create its EVIDENCE node, and link it to the target
    FINDING/SECRET via `evidences`. Returns the blob's sha256.
    """
    info = store_evidence(engagement_dir, blob, kind)
    graph.upsert_node(
        "EVIDENCE",
        info["sha256"],
        {
            "sha256": info["sha256"],
            "blob_path": info["blob_path"],
            "kind": kind,
            "created_at": info["created_at"],
        },
    )
    target_table = "FINDING" if target_type == "finding" else "SECRET"
    graph.upsert_edge("evidences", info["sha256"], "EVIDENCE", target_id, target_table)
    return info["sha256"]
