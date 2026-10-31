# SPEC_BRIEF27 — `resolves_to` consumer: read-only `query.resolve_host` (hermetic)

Global rails are canonical, not restated: project `CLAUDE.md` §4 (Hard boundaries) +
`docs/loop/KRONOS_LOOP_ARCHITECTURE_v7.md`. Maintainer authorization: `/home/void/context.md`
(2026-10-31, checkpoint SEQ 162) — the FIRST consumer of the `resolves_to` edge as a bounded hermetic
increment; the design/scope PAUSE-DECISION is lifted **for this rung only**; Opus selected the design
from repository evidence (SEQ 163). Stored-graph + hermetic/mock fixtures only; **no** §6, live DNS,
live network, external target, LLM, budget, or unrelated capability. This brief states in full only
its own scope, permitted files, contract, invariants, negative cases, acceptance, and exit.

## §1 — Problem

`resolves_to` (`src/kronos/schema.py:129`: `[("HOST","HOST"),("API_ENDPOINT","HOST"),("WEB_ENDPOINT","HOST")]`)
now has a producer (SPEC_BRIEF26, `ingest/dns/parser.py`, merged `31ca3b5`) but **no consumer**: a
repo-wide grep for `resolves_to` finds only the schema definition, the producer, and the producer's
tests. The edge is written and never read. This brief adds the first consumer: a **read-only query**
that, given an FQDN `HOST`, returns the IP-address `HOST`s it resolves to (following CNAME chains),
scope-gated, deterministic, abstaining explicitly where evidence is insufficient. It advances G1
(name → infrastructure is now a queryable cross-domain primitive) without weakening G3 (it asserts no
resolution it cannot prove from stored edges, and never approves or expands scope).

## §2 — Approach (contract fixed here; expected test values derive from this prose)

**A single new read function in the existing read surface `src/kronos/query.py`.** No new module, no
new framework, no new dependency. Plain-dict return, exactly as `query_graph`/`find_paths` return plain
lists/dicts (there is no query-side "decline" dataclass in the repo and this brief introduces none —
abstention is carried in an explicit `status` field, not a new type).

D1. **Signature.**
    `resolve_host(graph: "EngagementGraph", name: str, only_in_scope: bool = True) -> dict[str, Any]`.
    Read-only: it calls **only** `graph.execute(...)` (and stdlib `ipaddress`); it never calls
    `upsert_node`/`upsert_edge`/`apply_upserts`/`apply_plan` or any writer, never sets `in_scope`,
    never creates a `FINDING`/`SECRET`. Opens no socket.

D2. **Input normalization (deterministic, mirror the producer / `reconcile/canonical.py:84-100`).**
    Lowercase `name` and strip a single trailing dot. This matches HOST id convention (a HOST node's
    id **is** its hostname/IP — `reconcile/canonical.py:103-109`), so the normalized string is the id
    to look up.

D3. **Terminal vs. intermediate classification.** A reached `HOST` id that parses as an IP
    (`ipaddress.ip_address(id)` succeeds — IPv4 or IPv6) is a **terminal**. A reached `HOST` id that is
    not an IP is an intermediate (a CNAME target) whose own `resolves_to` out-edges are followed. The
    input `name`, if it is itself an IP literal, has no FQDN to resolve → `status="unresolved"`,
    `terminals=[]` (an IP does not resolve further here).

D4. **Traversal (BFS, deterministic, cycle-safe).** Breadth-first from the normalized `name` over
    `resolves_to` out-edges, one hop per step via
    `graph.execute("MATCH (a:HOST {id:$id})-[:resolves_to]->(b:HOST) RETURN b.id AS id, b.in_scope AS in_scope", {"id": <id>})`.
    Maintain a `visited` set of FQDN ids already expanded. Collect every reached **terminal** IP id.
    - **Scope gate (mirror `find_paths`' always-on endpoint check).** When `only_in_scope=True`
      (default): the start `name` node must be present **and** `in_scope`, or the result is
      `status="unknown_host"` (absent) / `status="unresolved"` with `excluded_out_of_scope=True` (present
      but out of scope); a CNAME intermediate is expanded only if `in_scope`; a terminal IP is kept only
      if `in_scope`, and any terminal dropped for being out of scope sets `excluded_out_of_scope=True`.
      When `only_in_scope=False`: intermediates and terminals are not scope-filtered (diagnostic use);
      `excluded_out_of_scope` is `False`.
    - **Cycle.** The `visited` set bounds the traversal by never re-expanding an FQDN already
      expanded: a **diamond** — two CNAME paths converging on one intermediate FQDN — is expanded once
      and is **not** a cycle (it resolves normally; the shared IP de-duplicates per D5). A **cycle** is
      a `resolves_to` edge back to an FQDN already on the *current branch's path* (an ancestor), e.g.
      `a→b→a`: set `status="cycle_detected"` and stop expanding that branch; terminals already
      collected from acyclic branches are still returned. (A finite graph with a visited-set
      terminates; no `max_hops` knob is introduced.)

D5. **Deterministic result.** `terminals` is the **sorted, de-duplicated** list of kept terminal IP id
    strings (MERGE semantics mean the same IP reached by two paths appears once; the sort makes output
    order input-order-independent). Same stored graph → identical dict.

D6. **Status (abstention first-class; evidence, not authorization).** Exactly one of:
    - `"unknown_host"` — the normalized `name` HOST node does not exist in the graph (no evidence).
    - `"unresolved"` — `name` exists (and, under `only_in_scope`, is in scope) but no in-scope IP
      terminal is reachable; `terminals=[]`. Also used when `name` is an IP literal (D3), or is present
      but out of scope under `only_in_scope` (with `excluded_out_of_scope=True`).
    - `"cycle_detected"` — a `resolves_to` cycle was reached (D4); `terminals` holds any acyclic-branch
      IPs found.
    - `"resolved"` — ≥1 in-scope IP terminal; `terminals` is that sorted non-empty list.
    Many IPs for one name is **normal** DNS (round-robin / multi-record), **not** an error: all are
    returned under `"resolved"`. "Conflicting" A-records are indistinguishable from legitimate multi-IP
    resolution from stored edges alone, so the consumer returns all and picks none (no false
    resolution). **Staleness is not representable**: `resolves_to` carries no timestamp (the producer
    emits no edge props — `ingest/dns/parser.py:94`), so the consumer makes **no** freshness claim and
    this brief adds no staleness field; this is acknowledged, not silently ignored.

D7. **Return shape.**
    `{"name": <normalized name>, "status": <one of D6>, "terminals": <sorted list[str]>, "excluded_out_of_scope": <bool>}`.

D8. **Nothing else.** No edit to `query_graph`/`find_paths`/`list_findings`/`list_secrets` or any other
    function; no schema, scope_guard, reconcile, producer, agent, or dependency change; no lifecycle
    event; no env var; no network; no §6; no budget; no reconciliation/merge (the FQDN↔IP pair stays
    two distinct HOST nodes by `canonical.py:103-109`'s guardrail — this consumer only reads them).

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only 31ca3b5..HEAD` ⊆ set)

1. `SPEC_BRIEF27.md`
2. `src/kronos/query.py` (edit: add `resolve_host` per §2 D1–D7, and `import ipaddress` if not present;
   do **not** touch `query_graph`/`find_paths`/`list_findings`/`list_secrets`/`_strip_alias` or the
   `_FIND_PATHS_INVALID_ENDPOINT_TYPES` constant)
3. `tests/test_query.py` (edit: add §8 `resolve_host` tests and the §8 J brief27 whole-window scope
   audit; do not alter existing tests)
4. **`tests/test_dns_ingest.py` (seal-only edit):** brief26's `test_J_scope_audit`
   (`tests/test_dns_ingest.py:159`) uses the unsealed window `f"{B26_BASE}..HEAD"`
   (`B26_BASE="4ff38f4"`), which trips on this branch (brief27 adds its own files). Add
   `B26_MERGE = "31ca3b5"` (brief26's PR #34 squash merge on `main`, SEQ 161) and change **that one
   test's** window to `f"{B26_BASE}..{B26_MERGE}"`, pinning the audit to brief26's footprint — exactly
   as brief26 §3 item 6 sealed brief25. **No other change to this file**; no other test or constant
   changes. Mechanically required for suite-green (§8 K).

Base = `origin/main` @ `31ca3b5`. Never `git add -A`; stage explicit paths only. **Add no new
dependency.** Do **NOT** edit `src/kronos/schema.py`, `scope_guard.py`, `reconcile/*`, `canonical.py`,
`contract.py`, any `ingest/*` parser, the agent layer, `graph.py`, `requirements.txt`,
`pyproject.toml`, `manifest.py`, `.github/`, or anything under `cybergym/`. All pre-existing tests and
the brief22/23/24/25/26 seals stay untouched and green.

## §8 — Acceptance criteria (tests-as-rules; expected values from §2 prose, not observed behaviour)

Decide PASS/FAIL from pytest's `SUMMARY:` line, never `$?` (`CLAUDE.md` §3). Every test is hermetic:
seed an in-memory engagement graph with `HOST` nodes + `resolves_to` edges via `graph.upsert_node`/
`graph.upsert_edge` (the `tests/conftest.py` `engagement_graph` + `manifest_factory` fixtures and the
seeding pattern in `tests/test_query.py`), call `resolve_host`, assert. A `nonet`-style socket
assertion covers the query path. New tests in `tests/test_query.py`.

A. **Direct A resolution.** FQDN `host.example.com` with `resolves_to` → `1.2.3.4` (both in scope) →
   `{"name":"host.example.com","status":"resolved","terminals":["1.2.3.4"],"excluded_out_of_scope":False}`.
B. **Input normalization.** `resolve_host(graph,"Host.Example.com.")` resolves the same as
   `host.example.com` (lowercased, trailing dot stripped); the returned `name` is `host.example.com`.
C. **CNAME chain.** `a.example.com --resolves_to--> b.example.com --resolves_to--> 1.2.3.4` (all in
   scope) → `status="resolved"`, `terminals==["1.2.3.4"]` (chain followed to the IP terminal; the
   intermediate FQDN is not in `terminals`).
D. **Many IPs (normal, not error).** One FQDN with `resolves_to` to `1.2.3.4` **and** `5.6.7.8` (both in
   scope) → `status="resolved"`, `terminals==["1.2.3.4","5.6.7.8"]` (sorted, both present, none
   dropped). Re-call yields the identical dict (determinism).
E. **De-duplication.** An IP reachable by two CNAME paths appears **once** in `terminals`.
F. **Unknown host.** A `name` with no HOST node → `status="unknown_host"`, `terminals==[]`.
G. **Unresolved.** An in-scope FQDN HOST that exists but has no `resolves_to` path to any IP →
   `status="unresolved"`, `terminals==[]`. An IP-literal `name` (e.g. `"1.2.3.4"`) → `status="unresolved"`,
   `terminals==[]`.
H. **Out-of-scope terminal excluded.** FQDN (in scope) resolving to one in-scope IP and one
   out-of-scope IP, `only_in_scope=True` → `terminals` holds only the in-scope IP and
   `excluded_out_of_scope==True`. With `only_in_scope=False` the out-of-scope IP is included and
   `excluded_out_of_scope==False`. (Asserts the edge-is-evidence-not-authorization invariant: an
   out-of-scope IP is never promoted into an in-scope result.)
I. **Out-of-scope start.** An FQDN present but `in_scope=False`, `only_in_scope=True` →
   `status="unresolved"`, `terminals==[]`, `excluded_out_of_scope==True` (the query never surfaces a
   resolution rooted at an out-of-scope host).
J2. **Cycle abstention.** `a.example.com → b.example.com → a.example.com` (a `resolves_to` cycle, no IP
   terminal) → `status="cycle_detected"`, `terminals==[]` (traversal terminates; no fabricated
   resolution). A cycle with one acyclic branch to `1.2.3.4` → `status="cycle_detected"`,
   `terminals==["1.2.3.4"]`.
J3. **Multi-path cycle (per-path detection).** A graph where a cycle closes only on a branch reached
   after the cycle's node was first expanded via another branch — e.g. `a→b`, `a→c`, `c→b`, `b→c` (all
   in-scope FQDNs, no IP terminal) — → `status="cycle_detected"` (the `b↔c` cycle is on the
   `a→c→b→c` / `a→b→c→b` branch). Asserts D4's rule that a cycle is a back-edge to an FQDN on the
   **current branch's path**, checked on every edge and not suppressed by the `visited` expansion-dedup;
   abstention must not degrade to `unresolved` when a real cycle exists.
R. **Read-only / no authorization side effect.** After `resolve_host`, the graph is unchanged: node
   count and edge count equal the pre-call counts, no new `HOST`/`FINDING`/`SECRET` node exists, and no
   node's `in_scope` changed. (Asserts the consumer neither writes nor approves.)
N. **No network.** A `nonet`-style socket assertion proves `resolve_host` opens no socket.
J. **Scope audit (whole window).** `git diff --name-only 31ca3b5..HEAD` ⊆ the §3 set, asserted with a
   distinct base constant `B27_BASE = "31ca3b5"` and window `f"{B27_BASE}..HEAD"` (never
   `f"{BRIEF_BASE}..HEAD"`, so the frozen brief seals stay green).
L. **brief26 audit sealed (§3 item 4).** `tests/test_dns_ingest.py::test_J_scope_audit` uses window
   `f"{B26_BASE}..{B26_MERGE}"` with `B26_MERGE = "31ca3b5"`, **not** `..HEAD`, so it is pinned to
   brief26's footprint and passes on this and later branches; all other tests/constants in that file
   are unchanged.
K. **Suite green.** Full `pytest` reports `0 failed` on the final commit (totals refreshed as the last
   edit); all pre-existing tests and the brief22/23/24/25/26 seals untouched and green.

## §9 — Done when

All of §8 holds; `query.resolve_host` reads stored `resolves_to` edges to return an FQDN's in-scope IP
terminals (CNAME chains followed), deterministically and de-duplicated, scope-gated with
`excluded_out_of_scope` surfaced, abstaining via explicit `status` (`unknown_host`/`unresolved`/
`cycle_detected`) when evidence is insufficient and making no freshness claim; the consumer is
read-only (no write, no `in_scope` change, no `FINDING`/`SECRET`, no scope expansion, no host
auto-approval); no schema/scope_guard/reconcile/producer/dependency change, no out-of-§3 path changed;
no live network or LLM call occurs; and the full suite is green on the head commit. No §6 capability,
no budget wiring, no reconciliation/merge, no IDENTITY/TECHNOLOGY work is part of this brief.
