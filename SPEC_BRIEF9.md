# SPEC_BRIEF9.md — Ingestion contract, canonical keys, owned event stream — S2

**Status:** build brief (stateless). Start from latest `main` (must contain the PR #10 merge —
check `src/kronos/validate/controls.py` exists). New branch, open a PR, **do NOT merge**. Cloud
build.
**Autonomy:** Balanced. Proceed on reversible calls. Escalate only the FORKs below
(FORK / OPTIONS / RECOMMENDATION / DEFAULT); every one carries a DEFAULT — if unattended, take it
and record which.
**Role separation (binding):** researcher wrote this; **builder** implements on a branch, opens a
PR, and never merges; **reviewer** reads the diff against §7 before merge. The review gate applies
to this PR and every PR after it — no merge without a reviewed diff.

**Standing gate, not this brief's work:** **FORK-2 (shape-aware scope matcher, GitHub #2) is
REQUIRED before S3 and before any live-target or Beast-mode use.** `scope_guard.py` keeps a
zero-line diff here, so this brief does not discharge it. Do not point KRONOS at a client target
or enable Beast mode until FORK-2 has landed and been reviewed.

---

## 0. Why this brief exists

S1 made validation honest. S2 makes *ingestion* honest, so S3 (infra) and S5 (web) plug into a
defined contract instead of each inventing one. Three deliverables, deliberately narrow.

**Verified in source on `main`:**

1. **The ingestion contract already exists implicitly and is a good shape.**
   `ingest_mobile_static(...) -> list[NodeUpsert | EdgeUpsert]` returns a *declarative plan*; it
   does not write the graph itself. That separation is worth keeping and formalizing, not
   redesigning. It is currently a convention held by exactly one ingester.
2. **`WEB_ENDPOINT`, `PARAMETER` and `SERVICE` have no `merged_into` column.** Only `HOST`,
   `API_ENDPOINT`, `MOBILE_APP`, `SECRET` and `FINDING` do. Reconciliation tombstones a loser by
   writing `merged_into`, so canonical keys for those three types would be **completely inert** —
   the key computes, no merge can ever complete. Shipping keys without the schema prerequisite
   recreates Brief #4's exact defect (a dedup path that looked wired and never ran), which review
   caught once already. The schema addition is therefore **part of this brief, not a follow-up.**
3. **No event stream exists** anywhere under `src/kronos/` (`git grep -i event` returns only an
   unrelated hit in `budget/limits.py`).

---

## 1. Hard guardrails

1. `src/kronos/scope_guard.py` MUST stay a **zero-line diff**. FORK-2 stays open; see the standing
   gate above.
2. `advance_secret_status` stays the only forward status mutator. `lifecycle.py` untouched.
   **An ingester never sets `status`, `confidence`, `scope_note`, `in_scope`, or `merged_into`.**
3. `NODE_PROPS_FORBIDDEN` keeps `merged_into` — adding the column to three tables must **not** make
   it caller-writable. Only the reconcile path writes it.
4. **Scope is decided by `scope_guard` via `upsert_node`, never by an ingester.** No ingester may
   compute or pass `in_scope`.
5. **Raw tool output never enters node properties.** It goes to the evidence store; nodes carry
   references. (The LLM queries the graph, never raw dumps.)
6. **Deterministic.** Same input → same node ids, same canonical keys, same event sequence (ids and
   keys; timestamps excepted). No LLM anywhere in this brief.
7. **Conservative bias, unchanged from Brief #4 guardrail 6:** an uncertain canonical key returns
   `None` and nothing merges. Never merge across identifier shapes.
8. No new runtime dependencies. No new network egress.
9. Do not weaken or delete any existing test. Baseline is **433 passed / 1 skipped** in `tests/`
   and **17 passed** in `cybergym/cloud/`.

---

## 2. File allowlist

**May change:**
- `src/kronos/ingest/contract.py` (new) — the formal source contract.
- `src/kronos/ingest/__init__.py`, `src/kronos/ingest/mobile/parser.py` — make the existing
  ingester conform (it already nearly does; adapt, do not rewrite).
- `src/kronos/events.py` (new) — the event-stream chokepoint.
- `src/kronos/schema.py` — **only** to add `merged_into STRING` to `WEB_ENDPOINT`, `PARAMETER`,
  `SERVICE` and the matching `NODE_PROPS_ALLOWED` entries. No other schema change.
- `src/kronos/reconcile/canonical.py` — the three new key functions.
- `src/kronos/reconcile/runner.py` — wire the new types in, with the ordering rule in §5.
- `src/kronos/ingest/README.md`, `src/kronos/reconcile/README.md`, `DECISIONS.md`.
- `tests/test_ingest_contract.py`, `tests/test_events.py`,
  `tests/test_canonical_keys_s2.py` (all new), plus additive edits to existing reconcile/ingest
  tests where the new wiring requires it.

**Must NOT change:** `scope_guard.py`, `lifecycle.py`, `validate/`, `budget/`, `cleanup/`,
`graph.py`, `manifest.py`, everything under `cybergym/`. If you believe one is required, **stop and
report** — that is what the brief-#8 contradiction proved the value of.

---

## 3. Deliverable 1 — the ingestion-source contract

Formalize what `ingest_mobile_static` already does, in `ingest/contract.py`:

- A `Protocol` (or ABC) an ingestion source satisfies: it takes its own input, and returns an
  **`IngestPlan`** — the existing `list[NodeUpsert | EdgeUpsert]` plus a report. It does **not**
  hold a graph handle and does **not** write.
- `SourceDescriptor`: a stable `name` and `version` string, written into each node's existing
  `source` column so provenance is queryable and two sources that disagree are distinguishable.
- `IngestReport`: counts of nodes/edges planned by type, plus a list of items the source
  *deliberately declined* to emit and why (unparseable input, missing required field). Declining is
  a first-class outcome, not silence.
- An `apply_plan(graph, plan)` helper that is the **only** thing that turns a plan into
  `upsert_node`/`upsert_edge` calls, so scope-gating and prop-allowlisting happen in exactly one
  place for every present and future source.

Then make the mobile ingester conform. It should be an adaptation, not a rewrite: if conforming
requires restructuring its logic, the contract is wrong — stop and report instead.

---

## 4. Deliverable 2 — canonical keys for the three types

### 4.0 Schema prerequisite (do this first)

Add `merged_into STRING` to `WEB_ENDPOINT`, `PARAMETER` and `SERVICE`, and add `merged_into` to
each of their `NODE_PROPS_ALLOWED` sets. `NODE_PROPS_FORBIDDEN` is unchanged, so the column stays
writable only by the reconcile path. Without this, everything below is inert.

### 4.1 `canonical_key_for_web_endpoint(method, url)`

Normalize and use the **exact** path: lowercase scheme and host, drop a default port (80/http,
443/https), strip a trailing slash, drop the query string and fragment entirely, uppercase the
method. Key shape: `web:{method}:{scheme}://{host}[:{port}]{path}`.

**No path templating** (FORK-N). The real duplicate case for a web page is the same URL found by
two sources (a crawler and a sitemap), not two ids under one route.

### 4.2 `canonical_key_for_parameter(name, param_type, parent_key)`

A parameter has no identity of its own — `?id=` on `/users` is not `?id=` on `/products`. The key
is **compound**: the parent endpoint's canonical key plus the normalized name and type. If
`parent_key` is `None`, return `None` (FORK-O: `None` propagates; an unreconcilable parent makes
its parameters unreconcilable).

### 4.3 `canonical_key_for_service(host_key, port, protocol)`

Also compound: port 443/tcp on host A is not port 443/tcp on host B. Normalize protocol to
lowercase; require a positive integer port. If `host_key` is `None`, return `None`.

---

## 5. Ordering rule (the subtle part)

`SERVICE` keys depend on `HOST` keys, and `PARAMETER` keys depend on their endpoint's key. So the
reconcile pass must merge **parents before children**, and child keys must be computed against the
**survivor's** id, never a tombstoned loser's.

Required order in `reconcile/runner.py`: `HOST` → `SERVICE`, and
`WEB_ENDPOINT`/`API_ENDPOINT` → `PARAMETER`. Assert this with a test that would fail under the
reverse order — not merely a comment. A child keyed off a loser is a silent mis-merge, and it is
exactly the class of defect that `merged_into`-inertness produced in Brief #4.

---

## 6. Deliverable 3 — the owned event stream

A deterministic, append-only record of what the run did, so an operator who stepped away can see
it and a reviewer can audit it. Keep it boring.

- `src/kronos/events.py` — one chokepoint, `emit(stream, kind, **fields)`, appending **JSONL** to
  `events.jsonl` in the engagement dir (FORK-Q). Append-only; never rewritten, never truncated.
- Event kinds for this brief, and no more: `ingest_started`, `ingest_finished` (with the
  `IngestReport` counts), `ingest_declined` (one per declined item, with the reason),
  `reconcile_merged` (node type, survivor id, loser ids), `reconcile_skipped_uncertain_key`.
  Validation and budget events are a later brief — do not add them speculatively.
- **No secret values, and no raw tool output, in any event.** Same rule as evidence blobs.
- Writing an event must never be able to fail the run: an unwritable stream degrades to a logged
  warning, because observability is not allowed to break the engagement. (Contrast with the budget
  ledger, which *is* load-bearing and fails closed.)

---

## 7. FORKs (pre-resolved)

**FORK-N — WEB_ENDPOINT path templating.** (1) exact normalized path, no templating;
(2) reuse `_path_template` as `API_ENDPOINT` does.
→ **DEFAULT: (1).** `/blog/post-1` and `/blog/post-2` are different pages with different content;
`/users/123` and `/users/456` are one API route. Templating pages would merge distinct attack
surface and *lose* findings. Guardrail 7: uncertain → no merge.

**FORK-O — compound-key `None` propagation.** (1) parent key `None` → child key `None`;
(2) fall back to a parent-independent child key.
→ **DEFAULT: (1).** Option 2 would merge parameters across unrelated endpoints — a cross-endpoint
mis-merge, the worst failure available here.

**FORK-P — the `merged_into` schema addition.** (1) add it in this brief, as the prerequisite;
(2) ship the keys now and add the column later.
→ **DEFAULT: (1).** Option 2 ships a dedup path that cannot complete — Brief #4's defect, knowingly
reintroduced.

**FORK-Q — event-stream format.** (1) append-only JSONL in the engagement dir; (2) a table in the
Kùzu graph.
→ **DEFAULT: (1).** The graph is the findings model; an operational log in it invites LLM queries
over run mechanics and couples observability to schema migrations. A file is also trivially
greppable and diffable.

**FORK-R — wire the new types into the reconcile runner now?** (1) yes, with real-duplicate tests
required; (2) land keys only, wire later.
→ **DEFAULT: (1).** Brief #4.1's lesson: a key whose merge path never executes is not proven. If it
is wired, it must be exercised on genuine duplicates.

---

## 8. Tests

1. **Contract conformance:** the mobile ingester satisfies the `Protocol`; it returns a plan and
   holds no graph handle. Assert it never emits `in_scope`, `status`, `confidence`, `scope_note`, or
   `merged_into` in any planned node's props.
2. **`apply_plan` is the only writer:** a grep-style guard asserting no module under
   `src/kronos/ingest/` calls `upsert_node`/`upsert_edge` directly except `apply_plan`. Mirror the
   budget-exemption guard in `tests/test_cleanup.py`, and **assert the scan was non-vacuous**
   (`scanned > 0`) — the §7.6 lesson.
3. **Declining is recorded:** malformed input produces an `IngestReport` with a declined entry and
   an `ingest_declined` event, not a silent drop and not a crash.
4. **Each new key:** positives, negatives, and the normalization cases named in §4
   (default-port drop, trailing slash, case, query-string removal, protocol lowercasing).
   `canonical_key_for_web_endpoint` must **not** collapse `/blog/post-1` and `/blog/post-2`.
5. **Compound-key `None` propagation:** parent `None` → child `None`, for both `PARAMETER` and
   `SERVICE`.
6. **Real duplicates merge (FORK-R):** genuine distinct-id duplicates of `WEB_ENDPOINT`,
   `PARAMETER` and `SERVICE` merge; the loser ends edgeless and tombstoned with `merged_into` set;
   the survivor holds the union; `find_paths` never returns a loser id. This is the test that proves
   §4.0 actually took effect.
7. **Ordering (§5):** a graph where both a host and its services are duplicated merges hosts first
   and keys services off the **survivor**. Write it so it would fail if the order were reversed.
8. **Idempotency:** a second reconcile pass over the now-non-empty graph returns an empty
   `MergeReport` and changes nothing.
9. **Event stream:** JSONL is append-only and parseable; the documented kinds appear with the right
   fields; no secret value or raw tool output in any event; an unwritable stream degrades to a
   warning and does **not** fail the run.
10. **Determinism:** same input twice → identical node ids, identical canonical keys, identical
    event kinds in identical order (timestamps excepted).
11. **Regression:** full suite green; report new totals.
12. **Live:** the CyberGym run still earns **X-score 3/3**, exit 0, and the mobile chain still
    ingests identically after conforming to the contract. §5.3-style live checks need an
    **unproxied** host — in a proxied cloud container, report **BLOCKED / INCOMPLETE** and do not
    present hermetic tests as satisfying it.

---

## 9. Acceptance criteria

1. `scope_guard.py` zero-line diff; `lifecycle.py` untouched; FORK-2 still open and still gating S3.
2. `schema.py` changed **only** by the §4.0 `merged_into` addition + matching allowlist entries;
   `NODE_PROPS_FORBIDDEN` unchanged.
3. The mobile ingester conforms to the contract by adaptation, not rewrite, and its planned nodes
   are byte-identical in id and props to before (prove it).
4. `apply_plan` is the sole graph writer under `ingest/`, proven by a non-vacuous guard.
5. All three canonical keys implemented per §4, with `None` on uncertainty.
6. Compound keys propagate `None` from an unreconcilable parent.
7. Parents merge before children, and child keys use survivor ids — proven by a test that fails
   under the reverse order.
8. Real distinct-id duplicates of all three new types actually merge and tombstone (not a no-op
   proof).
9. Event stream append-only, deterministic in order, carries no secret or raw output, and cannot
   fail the run.
10. Full suite green from a clean venv; totals reported.
11. Live X-score 3/3 exit 0 — or an explicit **BLOCKED / INCOMPLETE** naming the environment.
12. FORK choices N, O, P, Q, R recorded — DEFAULT or escalated, with reason.

---

## 10. Output expected back

- Branch + PR link (not merged); diff summary; suite totals before/after.
- Guardrail confirmation: `scope_guard.py` zero-line, `lifecycle.py` untouched, allowlist respected,
  `NODE_PROPS_FORBIDDEN` unchanged.
- FORK choices (N, O, P, Q, R).
- The three canonical key formats as implemented, with one worked example each.
- Proof that mobile ingestion output is unchanged post-conformance.
- The merge-ordering test, named, plus what it asserts.
- A sample of `events.jsonl` from a run (secret-free).
- Live X-score line and exit code, or the BLOCKED / INCOMPLETE report.
