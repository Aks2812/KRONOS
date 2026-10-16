# Reconciliation / Dedup (`kronos.reconcile`)

Collapses different node IDs that denote the same real-world entity once
a second ingestion source feeds the graph. `upsert_node` already dedups
on exact ID match; this is the layer above that — different IDs, same
entity.

## Pipeline placement

```
ingest -> reconcile -> enrich -> reconcile -> _assert_enrichment_did_not_shortcut_anyone -> validate
```

Before `validate` so twins are collapsed and validation runs once per
real entity. After `enrich` because enrichment creates nodes too.
Idempotent — safe to run in both slots, or any number of times; a
second run on an already-reconciled graph returns an empty `MergeReport`
and touches nothing.

## Modules

- **`canonical.py`** — pure canonical-key functions, one per mergeable
  node type (`SECRET`, `API_ENDPOINT`, `HOST`, `MOBILE_APP`, `FINDING`,
  and as of SPEC_BRIEF9: `WEB_ENDPOINT`, `PARAMETER`, `SERVICE`).
  No graph access. `None` means "can't produce a confident key" — that
  node is never merged (conservative bias: a missed merge is a cheap,
  self-correcting duplicate; a false merge can hide a real finding).
  Never collapses across identifier shapes (an FQDN and an IP get
  different canonical-key prefixes by construction, even if they're the
  same real host).

  `PARAMETER` and `SERVICE` are **compound**: their key embeds an
  identifier for their parent (`parent_key`/`host_key`). That identifier
  is the parent's own RAW node id, as `runner.py`'s grouping functions
  currently resolve it via the graph — deliberately NOT a freshly
  recomputed `canonical_key_for_*` on the parent. Those functions are
  pure (a function of the parent's own text alone), so two genuine
  parent duplicates always produce the same canonical key regardless of
  merge state — using one here would make SPEC_BRIEF9 §5's ordering
  rule untestable by construction (see `tests/test_reconcile.py`'s
  ordering test, which fails under the reverse merge order precisely
  because it uses the raw id instead).
- **`merge.py`** — the actual merge: picks a deterministic survivor
  (lexicographic `min()` of the group's ids), carries over every edge a
  loser participates in (every label/pair in `schema.EDGE_PAIRS`, via
  the same `graph.upsert_edge` every ingester uses — so de-dup is free),
  recomputes `SECRET` status from the survivor's now-merged evidence
  (never copies/maxes the input statuses — see
  `lifecycle.recompute_status_from_evidence`), **deletes every
  relationship still on each loser** (move-don't-copy — SPEC_BRIEF4.1
  §2; a tombstone that kept its original edges would still be fully
  live to `find_paths` and any other traversal), then tombstones each
  loser (`merged_into=<survivor_id>`, plus `status="merged"` for
  `SECRET`/`FINDING`, which already own a `status` column). A `FINDING`
  group of >=2 raises `NotImplementedError` (SPEC_BRIEF4.1 §3) — FINDING
  has no evidence-recompute path yet, so it must refuse rather than
  silently merge on an un-recomputed survivor.
- **`runner.py`** — `run_reconciliation_pass(graph, engagement_dir) ->
  MergeReport`, the one entry point other code calls. Groups every
  active (non-tombstoned) node of each mergeable type by its canonical
  key and merges every group with more than one member. As of
  SPEC_BRIEF9 §5, **parents merge strictly before children**: `HOST`
  fully merges before `SERVICE` is even grouped, and
  `WEB_ENDPOINT`/`API_ENDPOINT` fully merge before `PARAMETER` is —
  enforced by call order (each type's group-then-merge step runs to
  completion before the next grouping function is called), not by a
  comment. Also as of SPEC_BRIEF9 §6: every successful merge emits a
  `reconcile_merged` event, and every node whose canonical key resolved
  to `None` emits a `reconcile_skipped_uncertain_key` event
  (`kronos.events`), so a reviewer can audit why something didn't
  merge without re-deriving the key logic by hand.

## Why status can't be laundered through a merge

The single most important rule here: a merge's survivor status is
**recomputed from evidence**, never copied from an input label.
`lifecycle.recompute_status_from_evidence(carried_statuses, has_evidence)`
is the one pure function that decides it:

- `dead` is terminal and sticky — once any twin is proven dead, no
  amount of (possibly stale) evidence on another twin resurrects it.
- Otherwise, evidence is the only thing that earns `reachable`. A node
  merely *labelled* `reachable` with no evidence behind it is
  indistinguishable, post-merge, from a plain `extracted` secret.
- No evidence, no dead twin -> `extracted`.

`lifecycle.set_secret_status_from_evidence` is the write path — called
only by `merge.py`, after it has already carried every loser's
`evidences` edges onto the survivor. It is deliberately **not** a
forward mutator: it doesn't consult `SECRET_TRANSITIONS` at all, because
a merge recompute can legitimately move status backward (an evidenceless
`reachable` label collapsing to `extracted`), which the forward-only
transition table would reject. `advance_secret_status` remains the only
function that advances a SECRET forward, and remains called only by
`kronos.validate.runner`.

## What's deliberately NOT here

- **No LLM.** Every canonical key is a deterministic string function.
- **No cross-shape merging.** FQDN vs IP vs bundle-id are different
  identifiers; a same-real-host relationship across shapes is a
  `resolves_to` edge assertion, never a merge — and this brief skips
  even asserting that edge today (see `DECISIONS.md`'s Brief #4 entry):
  no ingester in this codebase produces DNS-resolution evidence yet, so
  there's nothing honest to assert it from.
- **No hard deletes of nodes.** Every merged-away node stays queryable
  (`merged_into` set) — authorized-engagement provenance needs every
  observed node to stay defensible and traceable. Its *relationships*
  are a different matter: those ARE deleted (move-don't-copy, above) so
  the tombstone is genuinely inert, not just labelled.
- **No FINDING reconciliation yet.** `canonical_key_for_finding` and the
  runner's `_group_findings` are wired in and correctly produce nothing
  today (FINDING's schema has no `location_sig`), but `merge_group`
  actively refuses a real FINDING group rather than silently merging —
  see `DECISIONS.md`'s Brief #4.1 entry.
