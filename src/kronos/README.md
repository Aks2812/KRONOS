# `kronos` — Findings Graph Core

This package is Brief #1: a signed-manifest-authorized, scope-enforced
Kùzu findings graph with an evidence-gated validation lifecycle. No
agents, no LLM calls, no real parsers beyond one worked example — see
`SPEC.md` at the repo root for the full brief and `DECISIONS.md` for
every autonomous call made while building it.

## Module map

| Module | What it is | Deeper docs |
|---|---|---|
| `manifest.py` | Signed engagement scope manifest: load, verify, sign | [`README_graph.md`](./README_graph.md)¹ |
| `scope_guard.py` | `scope_guard(target, manifest)` — the only scope mechanism | [`README_graph.md`](./README_graph.md)¹ |
| `schema.py` | Kùzu DDL for all 14 node types / 14 edge labels | [`README_graph.md`](./README_graph.md) |
| `graph.py` | `EngagementGraph` — the only write path into the DB | [`README_graph.md`](./README_graph.md) |
| `lifecycle.py` | SECRET/FINDING status machines, derived confidence | [`README_lifecycle.md`](./README_lifecycle.md) |
| `evidence.py` | Hash-addressed, immutable evidence blobs | (see its own docstring) |
| `query.py` | The only read surface: `query_graph`/`find_paths`/`list_findings`/`list_secrets`/`get_evidence` | [`README_query.md`](./README_query.md) |
| `ingest.py` | Upsert contract + the one reference ingester (mobile secret → `leaks`) | [`README_ingest.md`](./README_ingest.md) |

¹ `manifest.py`/`scope_guard.py` are one trust boundary; their design
notes live alongside `graph.py`'s because that's where `ScopeGuard`
actually gets wired in (`EngagementGraph.__init__`). See
`README_graph.md`'s "Why `in_scope` is never caller-settable" section.

## The one path through the system

```
load_and_verify(yaml, pubkey)        -> ScopeManifest           (manifest.py)
EngagementGraph.init_engagement(...)  -> EngagementGraph         (graph.py, using scope_guard.py)
ingest(raw, tool_name, engagement)    -> [NodeUpsert|EdgeUpsert]  (ingest.py)
apply_upserts(engagement, upserts)    -> writes via upsert_node/upsert_edge
advance_secret_status / advance_finding_status -> enforced status+confidence (lifecycle.py)
attach_evidence(...)                  -> EVIDENCE node + evidences edge (evidence.py)
query_graph / find_paths / list_findings / list_secrets / get_evidence -> the only reads (query.py)
```

Every arrow above is the *only* way to do that step — there is no second,
lower-level path that skips scope stamping, skips the lifecycle gate, or
writes a freeform confidence value. That's deliberate: SPEC.md's safety
invariants only hold if there's exactly one door into each of them.

## Running the tests

```bash
pip install -r requirements.txt   # or: pip install -e .
python3 -m pytest -v
```

`tests/test_invariants.py` holds the explicit safety-invariant tests
(SPEC.md Deliverables #4): no-evidence finding can't be reported,
out-of-scope secret can't anchor a finding, confidence can't exceed its
status cap, expired/unsigned manifest is rejected, and `find_paths`
finds a seeded mobile→cloud chain (both directly and via the real
reference ingester end-to-end).
