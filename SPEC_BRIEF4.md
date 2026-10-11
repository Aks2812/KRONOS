# SPEC_BRIEF4.md — Reconciliation / Dedup Pass

**Status:** build brief (stateless). Paste into a Claude Code session on the KRONOS repo (cloud or Kali).
**Autonomy:** Balanced. Proceed on reversible calls. Escalate only the FORKs below using
`FORK / OPTIONS / RECOMMENDATION / DEFAULT`; both FORKs already carry a DEFAULT, so if
unattended, take the DEFAULT and record it in the output.

---

## 0. Why this brief exists (read before coding)

Validation is live. The moment a **second** source feeds the graph (MobSF + the regex
light-extractor today; network/infra and cloud scanners soon), the same real-world entity
gets created under **different node IDs**. `upsert_node` already dedups on *exact ID match* —
reconciliation handles the layer above that: **different IDs that denote the same entity.**

This is **not cosmetic.** It is a correctness requirement for KRONOS's false-positive moat:

- If a SECRET exists as two nodes, the validation lifecycle runs per-duplicate. One twin can be
  `reachable` while the other sits `extracted` — the "no evidence, no report" invariant is now
  ambiguous, and a **dead twin can leak into a report** while its live twin is what was proven.
- One real finding counted as two inflates the report and the X-score denominator.
- Validation work is done twice on the same entity (cost + latency).

So reconciliation is the thing that keeps the FP rate honest once ingestion fans out. That is
why it is the first quick win after validation, ahead of EPSS/KEV, budget, and cleanup.

---

## 1. Hard guardrails (do not cross — these protect decisions already locked)

1. **`src/kronos/scope_guard.py` MUST have a zero-line diff.** FORK-2 (shape-aware matcher,
   GitHub #2) stays open and is *not* touched or worked around here.
2. **Do not weaken the validation lifecycle.** `advance_secret_status` stays the only
   *forward mutator* of secret status, still called only by the validation runner.
   Reconciliation never writes `status` directly.
3. **Status is recomputed from evidence on merge, never copied.** A merge may not carry a
   status label across unless the **EVIDENCE that justifies it carries across too.** This is the
   single most important rule in the brief — see §3.2.
4. **No LLM in identity resolution.** Deterministic canonical keys only. (An LLM tie-breaker for
   genuinely ambiguous near-matches is a documented *future* escalation slot, not in scope here.)
5. **Never auto-merge across identifier shapes.** FQDN vs IP vs bundle-id are different
   identifiers → assert a relationship edge, never a merge (same discipline that keeps FORK-2
   honest).
6. **Conservative bias.** When a canonical-key match is uncertain, **do not merge.** A false
   merge (collapsing two distinct real findings) can *hide* a real finding and is strictly worse
   than a missed merge (a duplicate), which is caught on the next pass or flagged. Prefer leaving
   two nodes separate.
7. **The enrichment-shortcut assertion must still hold.** After reconciliation is inserted into
   the pipeline, `_assert_enrichment_did_not_shortcut_anyone` must still pass, and reconciliation
   must not become a *new* laundering path for status. Add a test that proves it (§4).

---

## 2. Pipeline placement

Reconciliation runs after **any node-creating pass**, and **before validation**:

```
ingest  →  reconcile  →  enrich  →  reconcile  →  _assert_enrichment_did_not_shortcut_anyone  →  validate
```

- Before `validate` so twins are collapsed and validation runs once on the canonical node.
- After `enrich` because enrichment creates nodes (the CyberGym enrichment secrets).
- Idempotent, so running it in both slots (or twice) is safe and the second run is a no-op.

---

## 3. Design

New module `src/kronos/reconcile/`:

- `canonical.py` — pure canonical-key functions, one per node type. No graph access.
- `merge.py` — the merge operation (edge/evidence carry-over + status recomputation + tombstone).
- `runner.py` — `run_reconciliation_pass(graph) -> MergeReport`. Idempotent.

### 3.1 Canonical keys (deterministic; `canonical.py`)

A canonical key is a stable string. Two nodes of the same type with the same key are the same
entity. If a node can't produce a confident key, it gets **no** key and is never merged (guardrail 6).

| Node type      | Canonical key | Normalization notes |
|----------------|---------------|---------------------|
| `SECRET`       | `f"{kind}:{sha256(normalized_material)}"` | Normalize material: strip whitespace, strip surrounding quotes. Hash so the key is storable without re-exposing the secret. Same material + kind = same secret regardless of extractor. |
| `API_ENDPOINT` | `f"{method}:{scheme}://{host_lc}{path_template}"` | `host_lc` lowercased. `path_template`: replace path segments that are numeric or UUID/hex with a placeholder (`/users/123` → `/users/{id}`), **conservatively** — only clearly-variable segments; if unsure, keep the literal segment (a missed merge is fine). |
| `HOST` / `ASSET` | `shape:value` where shape ∈ {fqdn, ipv4, ipv6, bundle_id} | fqdn lowercased, trailing dot stripped. **Never** collapse across shapes (guardrail 5). |
| `FINDING`      | `f"{finding_class}:{affected_asset_id}:{location_sig}"` | `location_sig` = a stable signature of *where* (e.g. endpoint id + param, or file:line for mobile). Only produce a key when all three parts are present; otherwise no key — findings are the highest-cost false merge. |

> Keep the exact set of node types you key to whatever actually exists in `schema.py`. Do not
> invent keys for node types where identity is already globally unique by construction.

### 3.2 Merge operation (`merge.py`) — the FP-critical part

Given a set of nodes sharing a canonical key, pick a **survivor** (deterministic: lowest/oldest
ID, so merges are reproducible) and fold the rest in:

1. **Carry over all edges** (incoming and outgoing) from the losers to the survivor, de-duping
   edges by `(label, other_id, other_type)`. This includes `has_evidence` / EVIDENCE links.
2. **Recompute status from the survivor's now-merged evidence.** Do **not** take the max of the
   input statuses. Call a single pure function (see FORK-B) that answers: *given this node's
   linked evidence, what status is justified?* The merged status is whatever that function
   returns. Consequences, by construction:
   - A `reachable` twin that carried real EVIDENCE confers `reachable` — because the evidence
     moved to the survivor and recomputation re-derives it.
   - A node *labelled* `reachable` with **no** evidence confers **nothing** — recomputation
     sees no evidence and returns `extracted`. Status cannot be laundered through a merge.
   - `dead` is terminal: if any input is `dead` *and* no live evidence exists on the survivor,
     the survivor is `dead`. (A dead twin cannot be resurrected by merging it with an
     evidenceless optimistic twin.)
3. **Tombstone the losers** (see FORK-A / DEFAULT): set `status="merged"`,
   `merged_into=<survivor_id>`, keep the node queryable, strip nothing. Never hard-delete.
4. **Record** the merge in the `MergeReport`: survivor id, each merged id, the canonical key that
   matched, the pass name, timestamp.

### 3.3 Cross-shape relationships (not merges)

When two keyed HOST/ASSET nodes are the same real host across shapes (an FQDN and the IP it
resolves to) and you have evidence of the resolution, assert a `resolves_to` edge between them.
Do **not** merge. If `resolves_to` is not already an allowed edge pair in `EDGE_PAIRS`, this is a
schema touch — treat it the same way the Brief #2 `exported` extension was treated: a scoped,
documented, architect-grade addition, called out explicitly in the output, not a silent change.
If in doubt, skip the edge for now and note it — the merge discipline is what matters here.

---

## 4. Acceptance tests (all must pass; add to the suite)

1. **SECRET dedup:** two SECRET nodes, same normalized material, different `source`/ID → one
   survivor, evidence from both carried, one tombstone with `merged_into` set.
2. **API_ENDPOINT template merge:** two endpoints, same method+host, paths `/users/123` and
   `/users/456` → merged. Two with genuinely different paths (`/users/1` vs `/admin/1`) → **not**
   merged.
3. **No cross-shape merge:** an FQDN node and an IPv4 node for the same host → **not** merged;
   `resolves_to` asserted (or skipped-and-noted per §3.3), both nodes still present.
4. **Idempotency:** run the pass twice. Second run returns an **empty** `MergeReport` and leaves
   the graph unchanged.
5. **Status cannot be laundered (the core FP test):**
   - (a) `reachable` secret *with* EVIDENCE + `extracted` twin → survivor `reachable`,
     and the test asserts the survivor has the carried EVIDENCE node.
   - (b) evidenceless node *labelled* `reachable` + a real `extracted` node (no evidence on
     either) → survivor is `extracted`, **not** `reachable`.
   - (c) `dead` twin + evidenceless optimistic twin, no live evidence → survivor `dead`.
6. **Pipeline invariant:** after inserting reconcile into the pipeline,
   `_assert_enrichment_did_not_shortcut_anyone` still passes, and the full CyberGym run still
   yields the same earned **X-score 3/3** (reconciliation must not change the proven result —
   it should collapse any duplicates *without* altering which chains are genuinely reachable).
7. **Audit:** `MergeReport` lists every merged pair with its canonical key and reason; tombstones
   are queryable via `query_graph`.
8. **Guardrail diff check:** `src/kronos/scope_guard.py` zero-line diff;
   `advance_secret_status` still called only by the validation runner (grep-assert in test or
   state it in the output).

---

## 5. FORKs (pre-resolved; take DEFAULT if unattended)

**FORK-A — merged-away nodes: tombstone vs hard-delete**
- OPTIONS: (1) tombstone: `status="merged"`, `merged_into`, node stays. (2) hard-delete loser,
  keep `merged_from=[...]` list on survivor.
- RECOMMENDATION / **DEFAULT: tombstone.** Authorized-engagement provenance needs every observed
  node to stay defensible and traceable; a tombstone is cheap and auditable.

**FORK-B — where status-from-evidence recomputation lives**
- OPTIONS: (1) add a pure `recompute_status_from_evidence(node, evidence)` to `lifecycle.py` that
  reconcile calls (and that `advance_secret_status` *could* be refactored onto later).
  (2) implement the recompute inside `reconcile/merge.py`.
- RECOMMENDATION / **DEFAULT: option 1 — put it in `lifecycle.py` as a pure function.**
  Status-from-evidence logic must exist in exactly **one** place; duplicating it in reconcile is
  itself the FP risk this brief is trying to remove. Adding a *pure, read-only* derivation
  function to `lifecycle.py` does not change the locked mutation semantics (`advance_secret_status`
  stays the only forward mutator) — flag it in the output as a scoped lifecycle addition, not a
  rewrite.

---

## 6. Output expected back in the review chat

- Branch + PR link, diff summary, test results (full suite count).
- Confirmation of both guardrail diffs (scope_guard zero-line; lifecycle mutator unchanged).
- Which FORK options were taken (DEFAULT or escalated).
- Explicit confirmation that the CyberGym run still earns **X-score 3/3** after reconciliation,
  and the `MergeReport` from that run (how many duplicates, if any, were collapsed).
- Any schema touch (`resolves_to`) called out explicitly if made.
