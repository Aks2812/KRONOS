# SPEC_BRIEF28 — DNS hygiene rung: docstring + meaningful assertion + FQDN length limits (hermetic)

Policy: this brief binds under `CLAUDE.md` §4 Hard boundaries and the v7 contract (canonical
reference; not restated). Correctness and test-hardening only — **no** new capability, schema change,
live DNS/network, §6 work, or unrelated refactor. Base = `origin/main` @ `a5373b4`.
Maintainer-authorized: `context.md` 2026-10-31.

## §1 — Problem
Three recorded LOW items on the merged DNS producer/consumer:
1. `query.resolve_host` docstring (`query.py:150`) says cycle-safety is "via a visited set"; the real
   mechanism is a DFS back-edge pass (`visited` only dedups expansion). Stale documented claim.
2. `test_dns_ingest.py:135` (`test_F_per_record_declines`) asserts on a non-existent `id` field of
   `EdgeUpsert` → vacuously true; it proves nothing about the producer.
3. `parser._norm_fqdn` enforces DNS syntax but **no** label (≤63) or total-name (≤253) length limit;
   an arbitrarily long syntactically-valid name is accepted.

## §2 — Approach (contract fixed here; expected test values derive from this prose)
- **D1 (docstring, query.py).** Rewrite the `resolve_host` docstring's cycle clause to state: traversal
  is BFS; the `visited` set **dedups expansion only**; cycle detection is a separate **DFS back-edge**
  check (a back-edge to an FQDN already on the current DFS path), and a diamond is **not** a cycle.
  Behaviour unchanged — docstring text only. No code logic change in this file.
- **D2 (meaningful assertion, test_dns_ingest.py).** In `test_F_per_record_declines`, replace the
  vacuous line-135 `getattr(u,"id",...)` assertion with a behavioral assertion on the producer output:
  the single accepted record (`host.example.com → 1.2.3.4`) yields an `EdgeUpsert` with
  `label=="resolves_to"`, `from_id=="host.example.com"`, `to_id=="1.2.3.4"`; and the declined
  (malformed) records contribute **no** `resolves_to` `EdgeUpsert`. Do not weaken the test's existing
  decline-count checks. Assert on `EdgeUpsert` fields that exist (`label`/`from_id`/`to_id`), never `id`.
- **D3 (FQDN length limits, parser._norm_fqdn).** After the existing lowercase + trailing-dot strip +
  regex + IP-literal checks, enforce, on the normalized candidate: every dot-separated label length in
  `1..=63` and total length `≤253`. On violation return `None` (so the caller declines with the
  existing `"malformed_fqdn"` reason — **fail-closed**, same path as a regex miss). No new decline
  reason, no new field, no signature change. Apply to both the `name` and CNAME `value` paths
  (unchanged call sites `parser.py:72,78`). All currently-accepted valid inputs (labels ≤63, total
  ≤253) keep resolving exactly as before.

No new dependency. Read/parse stays in-process; hermetic. No producer/consumer behaviour changes other
than D3's stricter decline of over-length names.

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only a5373b4..HEAD` ⊆ set)
1. `SPEC_BRIEF28.md`
2. `src/kronos/query.py` (**docstring of `resolve_host` only** per D1; do **not** change any code/logic
   in this file).
3. `src/kronos/ingest/dns/parser.py` (`_norm_fqdn` length checks per D3 only; do **not** touch
   `_FQDN_RE`, the record loop, decline reasons, or edge/node emission).
4. `tests/test_dns_ingest.py` (D2 assertion replacement in `test_F_per_record_declines`; add the §8
   FQDN-length tests; **seal nothing else** — its `test_J_scope_audit` is already pinned).
5. `tests/test_query.py` (**seal-only + additive**: pin `test_B27_J_scope_audit` by adding
   `B27_MERGE = "a5373b4"` and changing **that one test's** window from `f"{B27_BASE}..HEAD"` to
   `f"{B27_BASE}..{B27_MERGE}"`; add the §8 J-brief28 whole-window scope audit and the §8 docstring
   guard. Do not alter any other existing test.)

Base = `a5373b4`. Never `git add -A`; stage explicit paths. **Add no dependency.** Do **NOT** edit
`src/kronos/schema.py`, `scope_guard.py`, `reconcile/*`, `canonical.py`, `contract.py`, any other
`ingest/*` parser, the agent layer, `graph.py`, `requirements.txt`, `pyproject.toml`, `manifest.py`,
`.github/`, or anything under `cybergym/`. All pre-existing tests and the brief22–27 seals stay green.

## §8 — Acceptance criteria (tests-as-rules; expected values from §2 prose, not observed behaviour)
Decide PASS/FAIL from pytest's `SUMMARY:` line, never `$?` (`CLAUDE.md` §3). All tests hermetic (no
live network; a socket-raise guard where a parse path is exercised, per the file's `test_H` pattern).

A. **Docstring guard (D1).** A test in `tests/test_query.py` asserts `resolve_host.__doc__` does **not**
   contain the substring `"via a visited set"` and **does** mention a DFS back-edge cycle check
   (e.g. contains `"DFS"` and `"back-edge"`). Pins the corrected claim.
B. **Meaningful producer assertion (D2).** `test_F_per_record_declines` asserts the accepted record
   produces exactly one `resolves_to` `EdgeUpsert` with `from_id=="host.example.com"`,
   `to_id=="1.2.3.4"`, `label=="resolves_to"`, and that no `EdgeUpsert` arises from any malformed
   record (edge count == 1). The former vacuous `id` assertion is gone.
C. **Label length boundary (D3).** A record whose name has a label of exactly **63** chars (total ≤253,
   otherwise valid) is **accepted** (produces the HOST nodes + `resolves_to` edge); the same name with a
   **64**-char label is **declined** with reason `"malformed_fqdn"` and yields no `resolves_to` edge.
D. **Total length boundary (D3).** A syntactically valid name (all labels ≤63) of total length exactly
   **253** is **accepted**; a valid name of total length **254** is **declined** (`"malformed_fqdn"`),
   no edge. Expected accept/decline derive from the ≤63 / ≤253 rule in D3.
E. **Compatibility.** An ordinary short valid name (e.g. `host.example.com`) still resolves/produces its
   edge exactly as before D3 (a currently-passing valid case stays passing).
J. **Scope audit (whole window).** A test in `tests/test_query.py` asserts
   `git diff --name-only a5373b4..HEAD` ⊆ the §3 set, with a distinct base constant
   `B28_BASE = "a5373b4"` and window `f"{B28_BASE}..HEAD"`.
S. **brief27 audit sealed (§3 item 5).** `tests/test_query.py::test_B27_J_scope_audit` uses window
   `f"{B27_BASE}..{B27_MERGE}"` with `B27_MERGE = "a5373b4"` (not `..HEAD`), pinning it to brief27's
   footprint so it passes on this and later branches; all other tests/constants in that file unchanged.
K. **Suite green.** Full `pytest` reports `0 failed` on the final commit (totals refreshed as the last
   edit); all pre-existing tests and the brief22–27 seals untouched and green.

## §9 — Done
All §8 hold; the docstring matches the shipped DFS mechanism; the brief26 ingest test asserts real
producer behaviour; `_norm_fqdn` enforces 63/253 fail-closed with positive-boundary and negative tests;
scope whole-window ⊆ §3 with brief27's audit sealed to `a5373b4`; no schema/scope_guard/reconcile/
producer-behaviour (beyond D3 decline)/dependency change; no out-of-§3 path changed; no live network and
no §6.
