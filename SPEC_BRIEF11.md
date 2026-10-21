# SPEC_BRIEF11 — S3.1 Infra ingestion (nmap XML → HOST, SERVICE)

**Stage:** S3 (research record v6 §6 sequencing table — the first NEW ingestion domain;
S1/PR #10 and S2/PR #11 foundations merged, FORK-2 pre-S3 blocker closed at PR #18).
**Goal:** G1 (STRONGER — cross-domain breadth; web/infra before the agent layer).
**Authorization:** maintainer file `/home/void/context.md` (2026-10-21) authorizes one bounded
milestone in the recorded web/infra direction. GATE-1 self-approved by Opus (checkpoint SEQ 55
authority model) after validating this brief against `02-research/findings.md` evidence.

## §1 — Problem

Every downstream mechanism for infra nodes already exists and is tested, but **no ingestion
source produces `HOST`/`SERVICE` `NodeUpsert`s** — all such upserts in the tree are test-only
(researcher: zero production call sites). This brief adds the first producer: an nmap-XML infra
source conforming to the S2 ingestion contract.

Already present (do NOT re-implement, do NOT edit):
- `HOST`/`SERVICE` DDL — `src/kronos/schema.py:30-39`; `NODE_COLUMNS` `:223-224`.
  `HOST(id, in_scope, created_at, source, merged_into)`; `SERVICE(… , port INT64, protocol STRING, …)`.
  Neither table has a `status` column — so infra `NodeUpsert` props carry NO `status`.
- Canonical keys — `canonical_key_for_host` `src/kronos/reconcile/canonical.py:103-109`,
  `canonical_key_for_service` `:198-218` (reconciler computes these; the source does not).
- `hosts` edge pair `(HOST, SERVICE)` — `src/kronos/schema.py:102-134` `EDGE_PAIRS`.
- scope_guard HOST/SERVICE shapes — `src/kronos/scope_guard.py:223-236`
  (`"HOST"`/`"SERVICE"` → `{host, ip, host_port, ip_port}`); gating runs inside
  `EngagementGraph.upsert_node`, inherited for free.

## §2 — Approach (mirror `mobile/parser.py`, two faces on one core)

Add `src/kronos/ingest/infra/parser.py`:
- `INFRA_NMAP_SOURCE = SourceDescriptor(name="nmap", version="1")` (contract.py:34-47).
- A shared core `_ingest_infra_nmap_core(nmap_xml, engagement) -> list[NodeUpsert | EdgeUpsert]`
  that parses nmap XML with **stdlib `xml.etree.ElementTree` only** (no new dependency), emits
  one `HOST` per `<host>` and one `SERVICE` per **open** `<port>` (`<state state="open"/>`),
  plus a `hosts` `EdgeUpsert` from the HOST to each of its SERVICEs.
  - `HOST`: id = address string (e.g. `127.0.0.1`); props `{"source": "nmap"}`;
    `scope_key` = the address (ip/host shape).
  - `SERVICE`: id = `f"{host_id}:{portid}/{protocol}"`; props
    `{"port": int(portid), "protocol": protocol, "source": "nmap"}`; `scope_key` = `f"{host_id}:{portid}"` (ip_port/host_port shape).
  - Non-open ports: NOT emitted; recorded as `DeclinedItem` (contract.py:50-58).
  - Unparseable XML / missing address: `DeclinedItem`, never a raw-input leak, never a raise that escapes the plan face.
  - Events via `kronos.events.emit(engagement_dir, "ingest_started" | "ingest_finished" | "ingest_declined", …)` (events.py:42-77; mirror mobile `parser.py:136`, `:158-166`).
- `ingest_infra_nmap(nmap_xml, engagement) -> list[NodeUpsert | EdgeUpsert]` — bare-list face
  (wired into the dispatcher).
- `ingest_infra_nmap_plan(nmap_xml, engagement) -> IngestPlan` — `IngestionSource`-conforming
  face; returns `IngestPlan(upserts=tuple(core(...)), report=build_report(INFRA_NMAP_SOURCE, …, declined))`.
- **Hard constraint:** `infra/parser.py` contains NO `upsert_node`/`upsert_edge` calls — writes go
  only through `apply_plan`/`apply_upserts` (contract.py:118-127; `test_ingest_contract.py`'s
  non-vacuous guard exempts exactly those two names under `ingest/`).

Wire the dispatcher — `src/kronos/ingest/__init__.py:62-78`: add one branch
`if tool_name == "infra_nmap": from kronos.ingest.infra.parser import ingest_infra_nmap; return ingest_infra_nmap(raw_tool_output, engagement)`
(local import, same circular-import reason as mobile). Unknown `tool_name` still raises
`NotImplementedError`. Change nothing else in this file.

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only <base>..HEAD` must be a subset)

1. `SPEC_BRIEF11.md` (this brief)
2. `src/kronos/ingest/infra/__init__.py` (new; package marker)
3. `src/kronos/ingest/infra/parser.py` (new; the source)
4. `src/kronos/ingest/__init__.py` (edit; add ONLY the `infra_nmap` dispatch branch)
5. `tests/test_infra_ingest.py` (new)
6. `tests/fixtures/infra/cybergym_nmap.xml` (new; CyberGym-range fixture)

Base = `origin/main` @ `a2feba3`. Never `git add -A`; stage these explicit paths only.
Do NOT edit `schema.py`, `scope_guard.py`, `canonical.py`, `events.py`, `contract.py`,
`manifest.py`, `.github/`, or anything under `cybergym/`.

## §4 — Fixture `tests/fixtures/infra/cybergym_nmap.xml` (CyberGym only)

A minimal nmap XML. All in-scope addresses are `127.0.0.1` (CyberGym docker range,
`cybergym/scope_manifest.yaml` in-scope `127.0.0.1*`). Must contain:
- host `127.0.0.1` with open tcp ports `4566`, `4567`, `8091`, and one **closed** tcp port `9999`.
- a second host `10.0.0.1` (OUT of the CyberGym scope) with one open tcp port, to drive the
  scope-gating test.
No other addresses. No live scan — this is static test data; assert no socket I/O at ingest.

## §8 — Acceptance criteria (tests-as-rules; `tests/test_infra_ingest.py`)

Decide PASS/FAIL from pytest's `SUMMARY:` line (or raw pytest), never `$?` (CLAUDE.md §3).
Expected values below derive from THIS brief's prose, not observed behaviour.

A. **Contract conformance** — `isinstance(ingest_infra_nmap_plan, IngestionSource)` is `True`
   (mirror `test_ingest_contract.py:31-32`).
B. **Dispatcher** — `ingest(xml, "infra_nmap", engagement)` returns a non-empty
   `list[NodeUpsert|EdgeUpsert]`; an unknown `tool_name` still raises `NotImplementedError`.
C. **Nodes** — applying the fixture plan via `apply_plan` yields `HOST` `127.0.0.1` and three
   `SERVICE`s (`4566`,`4567`,`8091`), each with `port` as `int` and `protocol == "tcp"`
   (`engagement.get_node("HOST"/"SERVICE", id)`).
D. **Edges** — a `hosts` edge from `HOST 127.0.0.1` to each of the three in-scope SERVICEs.
E. **Open-only** — the closed port `9999` produces NO `SERVICE` and is recorded as a
   `DeclinedItem` in the report.
F. **Forbidden props** — no `NodeUpsert` carries `in_scope`/`confidence`/`scope_note`/
   `merged_into` and none carries `status`; `apply_plan` raises no `ValueError`
   (`schema.py:212` `NODE_PROPS_FORBIDDEN`).
G. **Scope-gating inherited** — the out-of-scope host `10.0.0.1` is applied with
   `in_scope is False` (decided by `scope_guard` inside `upsert_node`), while `127.0.0.1` is
   `in_scope is True` — proving infra ids route through `NODE_TYPE_SHAPES` and the manifest.
H. **No live network / XXE-safe** — the parser performs no socket I/O (assert, e.g., by
   monkeypatching `socket.socket` to raise); an nmap XML whose DOCTYPE declares an external
   entity does NOT resolve it (stdlib ElementTree default) — the source emits nothing from the
   entity, never fetches.
I. **Report** — `IngestReport.node_counts` has `HOST`/`SERVICE` counts, `edge_counts` has
   `hosts`, `declined` is non-empty (the closed port).
J. **Idempotence** — applying the same plan twice creates no duplicate HOST/SERVICE/edge (MERGE).
K. **Scope audit** — `git diff --name-only a2feba3..HEAD` is a subset of §3 (whole-window).

Full suite must be green (`0 failed`) under `.venv`; refresh the total count as the final edit
(CLAUDE.md §4). Reviewer runs independently against this brief and the diff.
