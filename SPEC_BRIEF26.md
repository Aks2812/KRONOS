# SPEC_BRIEF26 — DNS-resolution producer: tool-neutral records → `resolves_to` (hermetic)

Global rails are canonical, not restated: project `CLAUDE.md` §4 (Hard boundaries) +
`docs/loop/KRONOS_LOOP_ARCHITECTURE_v7.md`. Maintainer authorization: `/home/void/context.md`
(2026-10-31, checkpoint SEQ 156) — DNS-resolution producer as a bounded hermetic increment; the
source-format PAUSE-DECISION is lifted **for this rung only**; hermetic/mock fixtures only; no §6,
live network, external target, LLM, budget, or IDENTITY/TECHNOLOGY work. This brief states in full
only its own scope, permitted files, format, behaviour, negative cases, acceptance, and exit.

## §1 — Problem

The `resolves_to` edge exists in the schema (`src/kronos/schema.py:129`:
`"resolves_to": [("HOST","HOST"),("API_ENDPOINT","HOST"),("WEB_ENDPOINT","HOST")]`) but has **no
producer and no consumer** in `src/kronos` (`src/kronos/reconcile/README.md:100-105`;
`DECISIONS.md:846-856` records the deliberate Brief #4 skip). This brief adds the first producer: an
ingestion source that turns DNS-resolution evidence into `HOST` nodes and `HOST --resolves_to--> HOST`
edges, following the existing ingest contract. It adds **no consumer** (out of scope) and **no schema
change** (`resolves_to` already exists; editing `schema.py` is forbidden by `CLAUDE.md` §4).

## §2 — Approach (the format is fixed here; expected test values derive from this prose)

**Canonical source format — tool-neutral (chosen per `context.md`'s stated preference; repo evidence
shows no coupling requirement).** The producer parses a JSON document that is a **list of resolution
records**, each an object:

```
{"name": <str FQDN>, "type": "A" | "AAAA" | "CNAME", "value": <str IPv4 | IPv6 | FQDN>}
```

No tool-specific grammar (not BIND zone text, not `dig`/`dnsx` output). This mirrors how
`web/parser.py` consumes stdlib-`json` and `infra/parser.py` consumes stdlib ElementTree, and keeps
the KRONOS contract decoupled from any one resolver tool: any upstream adapter (dig, dnsx, zone file)
normalizes to this record list before KRONOS sees it. The `NodeUpsert`/`EdgeUpsert`/`IngestPlan`
triplet (`src/kronos/ingest/__init__.py`, `contract.py`) is the only normalization layer, exactly as
for the two shipped parsers — no second internal record schema is introduced.

D1. **Module + two faces (mirror `infra/parser.py`).** New package `src/kronos/ingest/dns/` with
    `parser.py`. A module-level `DNS_SOURCE = SourceDescriptor(name="dns", version="1")` (exactly the
    shape of `INFRA_NMAP_SOURCE`). A private core `_ingest_dns_records_core(raw, engagement) ->
    tuple[list[NodeUpsert|EdgeUpsert], list[DeclinedItem]]`, and two faces:
    - `ingest_dns_records(raw, engagement) -> list[NodeUpsert | EdgeUpsert]` (dispatcher-facing).
    - `ingest_dns_records_plan(raw, engagement) -> IngestPlan` =
      `IngestPlan(upserts=tuple(upserts), report=build_report(DNS_SOURCE, upserts, declined))`.
    The core **never** writes the graph (no `upsert_*`/`apply_*` call) — `apply_plan`/`apply_upserts`
    remain the only writers (`contract.py:1-21`).

D2. **Parse, fail-closed (mirror `web/parser.py:42-52`).** Use stdlib `json` only; open no socket.
    If `raw` is missing, not valid JSON, or not a JSON **list** → decline the whole input
    (`DeclinedItem(reason="unparseable_dns_json", detail="DNS input is missing, unparseable, or not a
    JSON list")`) and return an empty upsert list. A malformed input never raises past the core.

D3. **Per-record normalization + validation (deterministic, fail-closed, abstention first-class).**
    For each element, in input order, decline (and emit nothing for it) with a short secret-free
    `detail`, never raw input, on any of:
    - not an object, or missing/`non-str` `name`/`type`/`value` → `reason="missing_field"`.
    - `type` not in `{"A","AAAA","CNAME"}` → `reason="unsupported_record_type"`.
    - `name` not a valid FQDN (after normalization) → `reason="malformed_fqdn"`.
    - `type=="A"` and `value` not a valid IPv4 (`ipaddress.IPv4Address`) → `reason="malformed_address"`.
    - `type=="AAAA"` and `value` not a valid IPv6 (`ipaddress.IPv6Address`) → `reason="malformed_address"`.
    - `type=="CNAME"` and `value` not a valid FQDN → `reason="malformed_fqdn"`.
    **Normalization (deterministic):** FQDNs (`name`, and `value` for CNAME) are lowercased and have a
    single trailing dot stripped, matching `reconcile/canonical.py:84-100` `_host_shape`. IP values are
    validated but kept in their input text form. A declined record contributes **no** node or edge
    (abstention when evidence is insufficient).

D4. **Emit (per valid record).** Two `HOST` nodes then the edge, in this order so both endpoints
    pre-exist before the edge (required by `apply_upserts`/`_resolve_node_type`,
    `src/kronos/ingest/__init__.py:91-120`):
    - `NodeUpsert("HOST", <norm name>, {"source": DNS_SOURCE.name}, scope_key=<norm name>)`
    - `NodeUpsert("HOST", <norm value>, {"source": DNS_SOURCE.name}, scope_key=<norm value>)`
    (`DNS_SOURCE.name == "dns"` — the literal written to the node `source` column, as `infra` writes
    `"nmap"`.)
    - `EdgeUpsert("resolves_to", <norm name>, <norm value>)`
    `scope_key` on each HOST drives the existing `scope_guard` HOST shapes
    (`scope_guard.py:223-236` — `host`/`ip`/`host_port`/`ip_port`), so `in_scope` is enforced by the
    guard, not decided here — mirroring `infra/parser.py:56`. Nodes are emitted idempotently (re-applying
    an identical record list creates no duplicate — MERGE semantics of `apply_upserts`).

D5. **Deterministic output order.** The core emits records in input order; within a record, the two
    nodes precede the edge. (No sort needed; determinism is: same input list → identical upsert list.)

D6. **Dispatch wiring.** Add one branch to `ingest()` in `src/kronos/ingest/__init__.py`, mirroring
    `infra_nmap`/`web_openapi` exactly (local import to avoid the circular import):
    `if tool_name == "dns_records": from kronos.ingest.dns.parser import ingest_dns_records; return
    ingest_dns_records(raw_tool_output, engagement)`. No other edit to that file.

D7. **No lifecycle events, no new dependency, no env var, no network, no §6, no budget, no consumer,
    no schema/scope_guard edit, no IDENTITY/TECHNOLOGY work.** The producer returns plans/reports only
    (unlike `infra`/`web`, it emits **no** `ingest_started`/`ingest_completed` events — keeping it to
    the minimum this rung needs; provenance rides the node `source` column, not events). Imports are
    stdlib (`json`, `ipaddress`) + existing `kronos.ingest.contract` / `kronos.ingest.__init__` symbols
    only.

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only 4ff38f4..HEAD` ⊆ set)

1. `SPEC_BRIEF26.md`
2. `src/kronos/ingest/dns/__init__.py` (new; package marker, may be empty)
3. `src/kronos/ingest/dns/parser.py` (new; the producer per §2 D1–D5)
4. `src/kronos/ingest/__init__.py` (edit: add **only** the `dns_records` dispatch branch per §2 D6;
   do not touch `NodeUpsert`/`EdgeUpsert`/`apply_upserts`/`_resolve_node_type` or any other branch)
5. `tests/test_dns_ingest.py` (new; §8 tests, mirroring `tests/test_infra_ingest.py` /
   `tests/test_web_ingest.py`)

Base = `origin/main` @ `4ff38f4`. Never `git add -A`; stage explicit paths only. **Add no new
dependency.** Do **NOT** edit `src/kronos/schema.py`, `scope_guard.py`, `reconcile/*`, `canonical.py`,
`contract.py`, any other `ingest/*` parser (`infra`, `web`, `mobile`), `query.py`, the agent layer,
`requirements.txt`, `pyproject.toml`, `manifest.py`, `.github/`, or anything under `cybergym/`. All
pre-existing tests and the brief22/23/24/25 seals stay untouched and green.

## §8 — Acceptance criteria (tests-as-rules; expected values from §2 prose, not observed behaviour)

Decide PASS/FAIL from pytest's `SUMMARY:` line, never `$?` (`CLAUDE.md` §3). Every test is hermetic:
an in-memory engagement graph (mirror `tests/test_infra_ingest.py`'s fixture), stdlib parsing only, a
`nonet`-style socket assertion on the parse/plan path. New tests in `tests/test_dns_ingest.py`.

A. **A record → nodes + edge.** `[{"name":"host.example.com","type":"A","value":"1.2.3.4"}]` applied
   to the graph (via `ingest_dns_records` + `apply_upserts`, or `ingest_dns_records_plan` + `apply_plan`)
   yields `HOST` nodes `host.example.com` and `1.2.3.4` and a `HOST --resolves_to--> HOST` edge between
   them; re-applying the identical input creates no duplicate node or edge (idempotent).
B. **AAAA record** → `HOST` value node is the IPv6 string; edge asserted.
C. **CNAME record** → value `HOST` is the normalized FQDN; `name`/`value` lowercased and trailing dot
   stripped (e.g. input `"Host.Example.com."` → id `host.example.com`), asserted deterministically.
D. **Deterministic output.** The same multi-record input list yields an identical `upserts` tuple on
   repeat calls, with each record's two nodes emitted before its edge (assert the exact ordered tuple).
E. **Unparseable input → whole-input decline, no nodes.** `raw` that is not JSON, and a JSON object
   (not a list), each → empty upserts and a `DeclinedItem(reason="unparseable_dns_json")` in the plan's
   report; non-vacuity: assert a valid control input in the same test does emit nodes.
F. **Per-record declines (fail-closed, partial-parse safe).** A single input list mixing one valid A
   record with records that are: not an object; missing `value`; `type":"MX"`; `type":"A"` with
   `value":"not-an-ip"`; `type":"AAAA"` with an IPv4 value; `type":"CNAME"` with `value":"1.2.3.4"`;
   `name":"not a host"` — yields the valid record's nodes+edge **and** one `DeclinedItem` per bad
   record with the §2 D3 `reason`, and emits nothing for the bad records. (Asserts each `reason`.)
G. **Provenance.** Each emitted `HOST` node's `source` prop equals `DNS_SOURCE.name` (`"dns"`).
H. **Scope enforcement.** With a scoped engagement (mirror the infra test's scope fixture), a record
   whose host is in scope yields `in_scope=True` on its `HOST` node, and an out-of-scope host yields
   `in_scope=False` — driven by `scope_key`, decided by `scope_guard`, not by the producer.
I. **No network.** A `nonet`-style socket assertion proves the parse + plan path opens no socket (the
   producer is stdlib `json`/`ipaddress` only).
J. **Scope audit (whole window).** `git diff --name-only 4ff38f4..HEAD` ⊆ the §3 set, asserted with a
   distinct base constant `B26_BASE = "4ff38f4"` and window `f"{B26_BASE}..HEAD"` (never
   `f"{BRIEF_BASE}..HEAD"`, so the frozen brief seals stay green).
K. **Suite green.** Full `pytest` reports `0 failed` on the final commit (totals refreshed as the last
   edit); all pre-existing tests and the brief22/23/24/25 seals untouched and green.

## §9 — Done when

All of §8 holds; a DNS-resolution producer parses the tool-neutral JSON record list fail-closed,
normalizes deterministically, retains provenance on the `source` column, emits `HOST`+`HOST`+
`resolves_to` upserts with scope enforced by the existing guard, declines (abstains on) malformed or
unsupported records as first-class `DeclinedItem`s emitting nothing, and is reachable via
`ingest(tool_name="dns_records")`; no consumer, no schema or scope_guard change, no new dependency, no
env var, no out-of-§3 path changed; no live network or LLM call occurs; and the full suite is green on
the head commit. No §6 capability, no budget wiring, no IDENTITY/TECHNOLOGY work is part of this brief.
