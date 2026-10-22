# SPEC_BRIEF14 S6.1 Web validation (two-armed reachability → FINDING)
**Stage:** S6 (research record v6 §6 — web validation, two-armed + control disposition).
**Goal:** G1 (third real protocol family) + G3 (two-armed evidence, abstention on undiscriminated).
**Depends on:** S5 web ingestion (PR #21 / `33ab362`), S4 infra validation (PR #20 / `079a76f`), S1 differential engine.
**Authorization:** maintainer §6-autonomy grant (checkpoint SEQ 69, S4→S7) + architecture decisions
inherited from SEQ 70 (**FINDING via edge**, **reuse `Classification` enum**) now precedented by the
merged S4.1 infra validator. GATE-1 self-approved by Opus after validating the brief against the
researcher's cited findings (checkpoint SEQ 81).

## §1 — Problem
S5 writes `WEB_ENDPOINT`/`PARAMETER` nodes but nothing validates them. S6.1 adds the first web
validator: a two-armed reachability differential over in-scope `WEB_ENDPOINT` nodes, recording a
proven-reachable verdict as a `FINDING` linked `WEB_ENDPOINT --vulnerable_to--> FINDING`.
`WEB_ENDPOINT` has no status column (`schema.py:40-49`), so the verdict attaches to a `FINDING`,
which carries `status`/`confidence` (`schema.py:86-91`). Disposition reuses the existing
`Classification` enum (`controls.py:29-36`). The edge pair `("WEB_ENDPOINT","FINDING")` already
exists (`schema.py:125`).

This is the **exact HTTP mirror of the merged S4.1 infra validator**
(`src/kronos/validate/infra_validator.py`). It is **reachability only** — it does NOT attempt
authentication, authorization, or vulnerability validation, and does NOT target the deliberately
undocumented CyberGym route (`/internal/v1/admin/export`, `include_in_schema=False`), which is not
in the OpenAPI/WEB_ENDPOINT surface at all. No scope expansion.

## §2 — Approach
Add `src/kronos/validate/web_validator.py` (new), mirroring `infra_validator.py`:

- `validate_web_endpoint_reachable(canonical_probe: ArmResult, control_probe: ArmResult) -> ValidationOutcome`
  — PURE (no I/O, no graph writes). The caller supplies two already-probed arms, labelled exactly
  `A_canonical` and `B_negative_control`. Calls `run_differential([canonical_probe, control_probe],
  kind="http")` (`controls.py`) and returns `ValidationOutcome(live, evidence, detail, classification,
  control_outcome, discriminated)` mapped 1:1 from the `DifferentialResult`. `evidence` is a
  secret-free JSON summary of both arms (label/success/status_code only) and is non-empty, as the
  `ValidationOutcome` constructor invariant requires on a live outcome (`types.py:57-66`).
  **`kind="http"` already exists** (`controls.py`; used by `http_validator.py`) — do **NOT** edit
  `controls.py`.

- `record_web_finding(engagement, endpoint_id: str, outcome: ValidationOutcome) -> str`:
  - `finding_id = f"finding:web-reachable:{endpoint_id}"` (deterministic → idempotent MERGE).
  - `engagement.upsert_node("FINDING", finding_id, {"source": "web_validator", "title":
    f"Web endpoint {endpoint_id} reachable (two-armed differential)", "severity": "info",
    "status": "hypothesis"})`. NOTE: do **NOT** pass `confidence` or `in_scope` (both in
    `NODE_PROPS_FORBIDDEN`, `schema.py:212`); `status` is create-only (`schema.py:190`).
  - `engagement.upsert_edge("vulnerable_to", endpoint_id, "WEB_ENDPOINT", finding_id, "FINDING")`
    (edge pair `("WEB_ENDPOINT","FINDING")`, `schema.py:125`).
  - `advance_finding_status(engagement, finding_id, "reachable")` — the sole forward write path
    (`lifecycle.py`); `hypothesis → reachable` is a legal transition; lifecycle derives
    `confidence` (reachable-no-evidence → 7). Do **NOT** set `confidence` here. Guard the advance
    on the current status being `hypothesis`, exactly as `infra_validator.py:57`, so a re-run is
    idempotent.

- `run_web_validation_pass(engagement, *, probe: Callable[[str, str], ArmResult]) -> WebValidationReport`
  — writer/orchestrator over **in-scope `WEB_ENDPOINT` only**:
  - `MATCH (w:WEB_ENDPOINT) WHERE w.in_scope = true RETURN w.id, w.url, w.method ORDER BY w.id`
    (reads the already-stamped `in_scope` column — the validator never re-derives scope, mirroring
    `infra_validator.py:73`; WEB_ENDPOINT's scope-shape family is empty, `scope_guard.py:226`).
  - For each endpoint: `canonical = replace(probe(url, method), label="A_canonical")`; the
    negative-control is the **same origin, a guaranteed-absent path** (the HTTP analogue of S4's
    closed `CONTROL_PORT` on the same host): derive `control_url` from `url` via
    `urllib.parse.urlsplit` as `f"{scheme}://{netloc}{CONTROL_PATH}"`, then
    `control = replace(probe(control_url, method), label="B_negative_control")`.
  - Define a module constant `CONTROL_PATH` — a single improbable path that will not exist on a
    real target (e.g. `"/kronos-negative-control-probe"`).
  - `outcome = validate_web_endpoint_reachable(canonical, control)`; if `outcome.live`, append
    `record_web_finding(engagement, endpoint_id, outcome)` to `report.findings`; else append the
    endpoint id to `report.abstained`.
  - `WebValidationReport` dataclass: `findings: list[str]`, `abstained: list[str]` (mirror
    `InfraValidationReport`).

The module opens **no socket itself** — the only connection point is the caller-supplied `probe`
(as in `infra_validator.py`). The real caller's probe makes HTTP requests to CyberGym
`127.0.0.1:8091` **only**; tests inject a fake probe. **No new dependency** (`urllib.parse` is
stdlib; do NOT import `requests` in this module). **No event emission** (`events.py` untouched,
mirroring S4). **No live network in the module or the tests.**

## §2a — Seal the brief-13 scope-audit (cross-brief landmine, per SEQ 72)
`tests/test_web_ingest.py::test_K_scope_audit` currently diffs `f"{BRIEF_BASE}..HEAD"` with
`BRIEF_BASE = "079a76f"` (`tests/test_web_ingest.py:21,233`). On this S6 branch `HEAD` includes the
S6 files, so that audit would see out-of-brief-13 paths and FAIL. Seal it to brief-13's own merged
footprint, **seal-only** (no other change to that file):
- add `BRIEF_MERGE = "33ab362"  # brief 13 merged to main (PR #21 squash); seals this audit to brief 13's footprint`
- change the diff range `f"{BRIEF_BASE}..HEAD"` → `f"{BRIEF_BASE}..{BRIEF_MERGE}"`.

(`079a76f..33ab362` is exactly brief-13's five merged paths; the audit stays green and pinned.)

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only 33ab362..HEAD` ⊆ set)
1. `SPEC_BRIEF14.md`
2. `src/kronos/validate/web_validator.py` (new)
3. `tests/test_web_validator.py` (new)
4. `tests/test_web_ingest.py` (edit: §2a seal ONLY — add `BRIEF_MERGE` and pin the diff upper bound; no other change)

Base = `origin/main` @ `33ab362`. Never `git add -A`; stage explicit paths only.
Do **NOT** edit `controls.py`, `schema.py`, `lifecycle.py`, `types.py`, `events.py`, `runner.py`,
`registry.py`, `http_validator.py`, `infra_validator.py`, `candidates.py`, `manifest.py`,
`.github/`, or anything under `cybergym/`. Reuse the existing fixture
`tests/fixtures/web/cybergym_openapi.json` READ-ONLY (ingest it via
`kronos.ingest.web.parser.ingest_web_openapi_plan` to build `WEB_ENDPOINT` nodes); do not modify it.

## §8 — Acceptance criteria (tests-as-rules; `tests/test_web_validator.py`)
Decide PASS/FAIL from pytest's `SUMMARY:` line, never `$?` (CLAUDE.md §3). Expected values derive
from this brief's prose, not from observed behaviour.

A. **Differential kind=http** — `run_differential([A_canonical(success=True),
   B_negative_control(success=False)], kind="http")` → `classification=="live_discriminated"`,
   `live is True`, `discriminated is True`. Control also success → `"indiscriminate_target"`,
   `live is False`. Canonical fail → `"not_live"`, `live is False`.
B. **Outcome invariant** — `validate_web_endpoint_reachable` returns a `ValidationOutcome`; a `live`
   outcome has `discriminated is True` and `classification=="live_discriminated"` (constructor
   invariant holds; no path yields `live=True` otherwise). Both arms transport-error →
   `classification=="inconclusive"`, `live is False`.
C. **In-scope only** — with an in-scope manifest (`127.0.0.1*`), ingest the fixture (in-scope
   `127.0.0.1:8091` endpoints) plus at least one out-of-scope `WEB_ENDPOINT` (e.g. ingest a
   `10.0.0.1:8091` server variant); `run_web_validation_pass` calls `probe` only for in-scope
   endpoints (host `127.0.0.1`), **never** for the out-of-scope `10.0.0.1` endpoint.
D. **FINDING on live** — for each in-scope endpoint a live outcome creates a `FINDING`
   `finding:web-reachable:<endpoint_id>` with `status=="reachable"` and `confidence==7`, and exactly
   one `WEB_ENDPOINT --vulnerable_to--> FINDING` edge. The out-of-scope endpoint has **no** FINDING.
E. **Abstention** — canonical fail → no FINDING, no edge; both arms success (indiscriminate) → no
   FINDING, no edge; both arms transport-error (inconclusive) → no FINDING, no edge.
F. **No leak** — `outcome.evidence.decode() + detail + control_outcome` contains both arm labels
   (`a_canonical`, `b_negative_control`) and none of `password`, `secret`, `token`, `authorization`,
   `bearer`; `outcome.evidence` is non-empty on a live outcome.
G. **No live network** — monkeypatch both `socket.socket` and `socket.create_connection` to raise;
   `run_web_validation_pass` with an injected probe still runs and records the in-scope FINDING;
   assert no socket was used.
H. **Control is same origin, different path** — the control URL passed to `probe` has the same
   `scheme://netloc` as its canonical URL, a **different** path, and that path is not equal to any
   real ingested endpoint path (it is `CONTROL_PATH`).
I. **Idempotent** — running the pass twice leaves the FINDING count and the `vulnerable_to` edge
   count unchanged, and the status still `reachable`.
J. **Scope audit (whole window)** — `git diff --name-only 33ab362..HEAD` ⊆ the §3 set (audit the
   whole window, not just expected files).
K. **No forbidden columns** — assert `web_validator.py` never passes `confidence`, `in_scope`, or
   `merged_into` to `upsert_node`, and sets `status` only at create (structural/source assertion).
L. **Brief-13 seal** — `tests/test_web_ingest.py` contains `BRIEF_MERGE = "33ab362"` and uses
   `f"{BRIEF_BASE}..{BRIEF_MERGE}"` (the §2a seal landed, seal-only).

## §9 — Done when
All of A–L pass under the project suite with 0 failed (totals refreshed as the final edit, after the
last suite run, per CLAUDE.md §4), the whole-window scope audit holds, and the change is additive
(a new standalone validator pass plus its tests plus the brief-13 seal; no edit to any schema,
engine, lifecycle, runner, or other validator). CyberGym-only, hermetic.
