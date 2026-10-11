# SPEC_BRIEF4.1.md — Reconciliation fixes (amends PR #6, pre-merge)

**Status:** build brief (stateless). Continue on the SAME branch as PR #6
(`claude/youthful-rubin-j1qtqw`) and push to that PR. Do NOT open a new PR, do NOT merge.
**Autonomy:** Balanced. Proceed on reversible calls. Escalate only the FORK below
(FORK / OPTIONS / RECOMMENDATION / DEFAULT); it carries a DEFAULT, so if unattended take it
and record it.

---

## 0. Why this brief exists

PR #6 built reconciliation well, but review found the dedup is only half-wired and the live
3/3 was a **no-op proof** — the CyberGym fixture contains no true duplicates, so `merge_group`
never actually ran. Two latent defects must be closed before merge, plus the missing test that
would have caught them. Nothing in PR #6 is reverted; this is additive hardening on the same
branch.

Everything review confirmed as correct stays as-is: scope_guard zero-diff, the lifecycle split
(`recompute_status_from_evidence` / `set_secret_status_from_evidence`), the SECRET evidence-
recompute rule, the conservative canonical keys, the `merged_into`-forbidden-in-upsert lock, and
the post-enrichment re-assertion of `_assert_enrichment_did_not_shortcut_anyone` on the survivor.
Do not touch those.

---

## 1. Guardrails (unchanged from Brief #4 — still binding)

1. `src/kronos/scope_guard.py` MUST stay a zero-line diff (FORK-2 / GitHub #2 untouched).
2. `advance_secret_status` stays the only *forward* mutator, called only by the validation
   runner. Reconciliation still writes status only via `set_secret_status_from_evidence` →
   `recompute_status_from_evidence`.
3. SECRET merge status is recomputed from carried evidence, never copied. (Already correct —
   don't regress it.)
4. No LLM in identity resolution.
5. Never merge across identifier shapes.
6. Conservative bias: uncertain key → no merge.
7. The enrichment-shortcut assertion must still pass, on the survivor id.

---

## 2. Fix #1 (REQUIRED) — tombstoned losers must become inert to traversal

**Problem:** `_carry_over_edges` *copies* a loser's edges onto the survivor but never removes
them, and nothing outside `reconcile/runner.py` filters `merged_into`. So the first time a real
duplicate is merged, the loser stays fully live in the graph with all its original edges —
`find_paths` and non-SECRET candidate enumeration still traverse it. The duplicate is added as a
superset survivor, not removed. (SECRET escapes this only incidentally, via the validation
runner's `status='extracted'` filter.)

**Fix:** after the survivor holds the union of edges, **remove every relationship on each loser**,
so the loser is left as an edgeless tombstone node (its `merged_into`, and `status='merged'` for
the status-bearing types, stay for audit). Implement inside `reconcile/merge.py` — the fix must
localize there, not spread `merged_into` filters across consumers (that is the same
forget-to-filter trap in a new place).

- Move-don't-copy: for each loser, after `upsert_edge` has recreated its edges on the survivor,
  `DELETE` the loser's own relationships (iterate `EDGE_PAIRS` by label/pair the same way the
  carry-over does, both directions; delete the matched relationships on the loser). Order stays:
  carry over → (SECRET) `set_secret_status_from_evidence` → delete loser edges → tombstone node.
  The SECRET status recompute still runs on the survivor's post-carry-over evidence, so deleting
  the loser's edges afterward does not affect it.
- The tombstone node itself is NOT deleted (FORK-A DEFAULT, audit). Only its edges go.

**Acceptance (add to tests):** after merging a real duplicate, the loser node still exists, has
`merged_into` set, and participates in **zero** relationships; the survivor carries the union; a
`find_paths` query over the affected domain returns a path through the **survivor only**, never
through the loser.

---

## 3. Fix #2 (REQUIRED, lower risk) — FINDING merge path must not silently activate

**Problem:** `merge_group` collects `carried_statuses` for FINDING but never recomputes the
survivor's status from evidence (only SECRET does). It is unreachable today only because
`canonical_key_for_finding` always returns `None` (no `location_sig` in schema, nothing populates
it). canonical.py is deliberately pre-wired to switch on "for free" when that data is added — at
which point FINDING merge would keep the arbitrary min-id survivor's status without recomputing,
a silent false-negative (a real exploited finding downgraded) that activates with nobody
revisiting `merge.py`.

**Fix (make it loud, don't half-build it):** in `merge_group`, if `node_type == "FINDING"` and a
group of ≥2 ever forms, `raise NotImplementedError` with a message pointing to this brief —
"FINDING reconciliation needs an evidence-recompute path (see SPEC_BRIEF4.1 §3); complete it
before populating finding_class/location_sig." Remove the now-dead `carried_statuses` collection
for FINDING (keep it for SECRET). Leave `canonical_key_for_finding` and the runner's
`_group_findings` in place (they correctly yield nothing today) — the guard is the backstop for
the day they don't.

> Rationale: full FINDING reconciliation (its exploited→reported rules, its own evidence gating)
> belongs in the brief where findings are actually produced — likely alongside the agent layer.
> A loud refusal now is correct-by-construction and costs three lines; a half-built path is a
> landmine.

---

## 4. The missing test (REQUIRED) — turn the no-op proof into a real one

Add tests that inject **genuine** duplicates (distinct ids, same canonical key) and exercise
`merge_group` for real. Use the types that can actually produce distinct-id duplicates:

- **SECRET:** two SECRET nodes, distinct ids, same `kind` + same decoded material, each with its
  own edges — one carrying an EVIDENCE (`evidences`) node, one not; one `leaks`-linked from an
  app, one `authenticates_to` a cloud resource. After the pass: one survivor, loser edgeless +
  tombstoned (`status='merged'`, `merged_into` set), survivor holds the union of edges, and
  survivor status = `recompute_status_from_evidence` of the union (e.g. `reachable` iff the
  carried evidence justifies it; the evidenceless-`reachable`-label case still collapses to
  `extracted`).
- **API_ENDPOINT:** two endpoints, distinct ids, paths `/users/123` and `/users/456`, same method
  + host → same template key → merged; a third with a genuinely different path stays separate.
  After the pass, a `find_paths` traversal that reaches the endpoint domain returns the survivor
  only.
- **Inertness assertion (the Fix #1 proof):** explicitly assert each loser participates in zero
  relationships post-merge, and that `find_paths` never returns a loser id.
- **Idempotency still holds** on this now-non-empty graph: a second `run_reconciliation_pass`
  returns an empty `MergeReport` and changes nothing.
- **FINDING guard:** a unit test that constructs a ≥2 FINDING group and asserts `merge_group`
  raises `NotImplementedError` (bypassing the None-key runner path, calling `merge_group`
  directly) — proves Fix #2's backstop fires.

Keep the existing 13 tests green. The full CyberGym end-to-end run must still earn **X-score 3/3**
(it will still report 0 real merges for that fixture — that's fine; the new unit/graph tests are
what prove the merge mechanics now).

---

## 5. FORK (pre-resolved)

**FORK-C — how losers are made inert**
- OPTIONS: (1) move-don't-copy edges: delete each loser's relationships after carry-over, leaving
  an edgeless tombstone node. (2) enforce `merged_into IS NULL` at the graph read chokepoints
  (`find_paths` + candidate enumeration + any future reporting reader) via one shared helper.
- RECOMMENDATION / **DEFAULT: option 1 (move edges).** It localizes the fix to `merge.py` and
  makes the loser inert for *every* current and future consumer with no per-reader discipline to
  remember — option 2 recreates the exact forget-to-filter trap this brief is closing, one reader
  at a time. Only fall back to option 2 if this Kùzu version genuinely cannot delete relationships
  by pattern; if so, say so explicitly and route every path/candidate read through one filtered
  helper, not scattered `WHERE` clauses.

---

## 6. Output expected back

- Same branch / same PR (#6) updated; diff summary; full test-suite count (existing + new).
- Confirmation: scope_guard still zero-diff; lifecycle forward-mutator rule intact.
- Which FORK-C option was taken (DEFAULT or the documented fallback, with reason).
- The new tests' results, naming the inertness assertion and the FINDING-guard assertion.
- Confirmation the CyberGym run still earns X-score 3/3, with its MergeReport.
