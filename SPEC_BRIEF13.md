# SPEC_BRIEF13 — S5.1 Web ingestion (OpenAPI JSON → WEB_ENDPOINT, PARAMETER)

**Stage:** S5 (research record v6 §6 — web ingestion → WEB_ENDPOINT, PARAMETER, seeded from S3).
**Goal:** G1 (breadth). **Depends on:** S3 infra ingestion (HOST/SERVICE), the S2 ingestion contract.
**Authorization:** maintainer §6-autonomy grant (SEQ 69). GATE-1 self-approved by Opus after validating
this brief against the researcher's cited findings. Input-format / scope_key / seeding decisions are
routine milestone-bounding (precedented by S3), resolved by Opus and recorded in SEQ 76.

## §1 — Problem

Schema, canonical keys, scope-guard contract, and edges for WEB_ENDPOINT/PARAMETER all exist but have
**zero production producer** (researcher: no `NodeUpsert("WEB_ENDPOINT"...)` anywhere). S5.1 adds the first:
an OpenAPI-JSON web source conforming to the S2 ingestion contract, mirroring the S3 infra parser.

Pre-existing (do NOT edit):
- `WEB_ENDPOINT(id, in_scope, created_at, source, url, method, merged_into)` — `schema.py:40-44`;
  `NODE_PROPS_ALWAYS["WEB_ENDPOINT"]={"source","url","method"}` (`schema.py:167`).
- `PARAMETER(id, in_scope, created_at, source, name, param_type, merged_into)` — `schema.py:45-49`;
  `NODE_PROPS_ALWAYS["PARAMETER"]={"source","name","param_type"}` (`schema.py:168`).
- `NODE_PROPS_FORBIDDEN={"id","in_scope","confidence","scope_note","merged_into"}` (`schema.py:212`) — never pass these.
- Edges `exposes` (`(HOST,WEB_ENDPOINT)`,`(SERVICE,WEB_ENDPOINT)`) and `has_param` (`(WEB_ENDPOINT,PARAMETER)`) — `schema.py:103-107`.
- `NODE_TYPE_SHAPES["WEB_ENDPOINT"]==frozenset()`, `["PARAMETER"]==frozenset()` (`scope_guard.py:226`): a URL/param id
  can NEVER self-gate — the ingester MUST pass a host-shaped `scope_key` or the node is denied in_scope
  (`scope_guard.py:981-983`, `graph.py:140-151`).

## §2 — Approach (mirror `src/kronos/ingest/infra/parser.py`, two faces on one core)

Add `src/kronos/ingest/web/parser.py`:
- `WEB_OPENAPI_SOURCE = SourceDescriptor(name="openapi", version="1")`.
- `_ingest_web_openapi_core(openapi_json, engagement) -> list[NodeUpsert | EdgeUpsert]`: parse an OpenAPI 3
  document with **stdlib `json`** (accept a JSON string or already-parsed dict; no new dependency). Determine
  the server base URL from `servers[0].url` (default `http://127.0.0.1` if absent). For each `paths.<path>.<method>`
  (methods in GET/POST/PUT/PATCH/DELETE):
  - `url = server_base.rstrip("/") + path`; `method = METHOD.upper()`; `host = urlsplit(url).hostname`.
  - `WEB_ENDPOINT` NodeUpsert: id = `f"web:{method}:{url}"`; props `{"source":"openapi","url":url,"method":method}`;
    `scope_key = host` (host/ip shape → scope_guard gates via the manifest).
  - For each parameter in the operation (and path-level `parameters`): `PARAMETER` NodeUpsert: id =
    `f"param:{endpoint_id}:{param_in}:{name}"`; props `{"source":"openapi","name":name,"param_type":param_in}`
    where `param_in` is the OpenAPI `in` value (`path`/`query`/`header`/`cookie`); `scope_key = host`.
    Plus `EdgeUpsert("has_param", endpoint_id, param_id)`.
  - **Seeded from S3 (best-effort):** compute `expected_sid = f"{host}:{port}/tcp"` where `port` is the URL port
    (or 80/443 by scheme). If `engagement.get_node("SERVICE", expected_sid) is not None`, emit
    `EdgeUpsert("exposes", expected_sid, endpoint_id)` (SERVICE→WEB_ENDPOINT). If no such SERVICE, emit no
    exposes edge (the WEB_ENDPOINT stands alone; do NOT create a SERVICE here).
  - Order every WEB_ENDPOINT NodeUpsert before its has_param/exposes edges (apply_upserts resolves edge
    endpoints by existing nodes). The source performs NO writes; it emits `emit(engagement_dir, "ingest_started"
    | "ingest_finished" | "ingest_declined", …)` and records unparseable input / missing fields as `DeclinedItem`.
- `ingest_web_openapi(openapi_json, engagement) -> list[...]` (bare-list face) and
  `ingest_web_openapi_plan(openapi_json, engagement) -> IngestPlan` (IngestionSource face; returns
  `IngestPlan(upserts=tuple(core(...)), report=build_report(WEB_OPENAPI_SOURCE, …, declined))`).
- **Hard constraint:** no `upsert_node`/`upsert_edge` calls in this module (writes go via apply_plan/apply_upserts).
  Reading the graph (`engagement.get_node`) for the seed check is allowed (read-only; infra's plan face already
  takes `engagement`).

Wire the dispatcher — `src/kronos/ingest/__init__.py`: add
`if tool_name == "web_openapi": from kronos.ingest.web.parser import ingest_web_openapi; return ingest_web_openapi(raw_tool_output, engagement)`
(local import). Unknown `tool_name` still raises `NotImplementedError`. Change nothing else.

## §2a — Seal brief 12's scope-audit test (convention)
`tests/test_infra_validator.py::test_J_scope_audit` is pinned to `BRIEF_BASE("19c9464")..HEAD` — a HEAD-relative
landmine for this and every later brief. SEAL it: add `BRIEF_MERGE = "079a76f"` (brief 12 merged, PR #20 squash)
and change the diff to `f"{BRIEF_BASE}..{BRIEF_MERGE}"`. `19c9464..079a76f` = brief 12's exact 5-file footprint
⊆ its SECTION_3. Change nothing else in that file. (S6 will seal brief 13's own audit the same way.)

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only 079a76f..HEAD` ⊆ this set)

1. `SPEC_BRIEF13.md`
2. `src/kronos/ingest/web/__init__.py`  (new; package marker)
3. `src/kronos/ingest/web/parser.py`  (new)
4. `src/kronos/ingest/__init__.py`  (edit: add the `web_openapi` dispatch branch only)
5. `tests/test_web_ingest.py`  (new)
6. `tests/fixtures/web/cybergym_openapi.json`  (new; CyberGym-range fixture)
7. `tests/test_infra_validator.py`  (edit: §2a SEAL ONLY — add `BRIEF_MERGE="079a76f"`, pin the diff)

Base = `origin/main` @ `079a76f`. Never `git add -A`; stage explicit paths only.
Do NOT edit `schema.py`, `scope_guard.py`, `canonical.py`, `events.py`, `contract.py`, `graph.py`,
`manifest.py`, `.github/`, or anything under `cybergym/`.

## §4 — Fixture `tests/fixtures/web/cybergym_openapi.json` (CyberGym only)

A minimal OpenAPI 3 doc for the CyberGym api, `servers:[{"url":"http://127.0.0.1:8091"}]`, documenting:
- `GET /health` (no params).
- `GET /items/{item_id}` with a path parameter `item_id` (`in:"path"`), and one `query` parameter (e.g. `verbose`).
Only `127.0.0.1` host. Do NOT include the hidden `/internal/...` route (it is `include_in_schema=False` — not in
the OpenAPI surface). Static test data; no live HTTP.

## §8 — Acceptance criteria (tests-as-rules; `tests/test_web_ingest.py`)

Decide PASS/FAIL from pytest's summary line, never `$?`. Expected values derive from this brief's prose.

A. **Contract** — `isinstance(ingest_web_openapi_plan, IngestionSource)` is True.
B. **Dispatcher** — `ingest(doc, "web_openapi", engagement)` returns a non-empty `list[NodeUpsert|EdgeUpsert]`;
   unknown `tool_name` still raises `NotImplementedError`.
C. **Endpoints** — applying the fixture yields WEB_ENDPOINT nodes for `GET http://127.0.0.1:8091/health` and
   `GET http://127.0.0.1:8091/items/{item_id}`, each with `url`, `method=="GET"`.
D. **Parameters + has_param** — a PARAMETER `item_id` (`param_type=="path"`) and the `query` param exist, each
   linked `WEB_ENDPOINT --has_param--> PARAMETER`.
E. **Scope-gating inherited** — with the manifest `127.0.0.1*`, every WEB_ENDPOINT/PARAMETER is `in_scope is True`
   (via host-shaped `scope_key`); a WEB_ENDPOINT built with no `scope_key` (or an out-of-scope host) is
   `in_scope is False` — proving the empty-shape type is gated only through `scope_key`.
F. **Seeded from S3** — after ingesting `tests/fixtures/infra/cybergym_nmap.xml` first (creating SERVICE
   `127.0.0.1:8091/tcp`), ingesting the OpenAPI doc adds `SERVICE 127.0.0.1:8091/tcp --exposes--> WEB_ENDPOINT`
   for each endpoint. Without the SERVICE present, NO exposes edge is created (and no error).
G. **Forbidden props** — no NodeUpsert carries `in_scope`/`confidence`/`scope_note`/`merged_into`; apply raises no
   `ValueError`.
H. **No live network** — the parser performs no socket I/O (monkeypatch `socket.socket` to raise); an unparseable
   JSON / missing `paths` is a `DeclinedItem`, never a raise escaping the plan face.
I. **Report** — `IngestReport.node_counts` has WEB_ENDPOINT/PARAMETER counts, `edge_counts` has `has_param`
   (and `exposes` when seeded).
J. **Idempotence** — applying the same plan twice creates no duplicate nodes/edges (deterministic ids + MERGE).
K. **Scope audit** — `git diff --name-only 079a76f..HEAD` ⊆ §3 (whole window).
L. **Brief-12 seal** — `tests/test_infra_validator.py::test_J_scope_audit` passes with its upper bound pinned to
   `079a76f` (§2a): `19c9464..079a76f` ⊆ brief 12's SECTION_3.

Full suite green (`0 failed`) under `.venv`; refresh the total as the final edit. Reviewer runs independently.

## §9 — Explicitly deferred (NOT in S5.1)
- Discovery of the hidden `/internal/...` endpoint (mobile-extracted; not in the OpenAPI surface).
- Web VALIDATION (that is S6).
- Any crawl/HAR input format beyond OpenAPI JSON.
