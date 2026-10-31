# SPEC_BRIEF25 — S8 Agent layer: executor `probe_service` / `probe_web` intents (hermetic/mock)

Global rails are the canonical policy, not restated here: project `CLAUDE.md` §4 (Hard
boundaries) + `docs/loop/KRONOS_LOOP_ARCHITECTURE_v7.md`. This brief states in full only its own
scope, permitted files, behaviour, negative cases, acceptance criteria, and exit conditions.

## §1 — Problem

`src/kronos/agent/live_executor.py` (`LiveExecutor.execute`, line 44-46) handles **only**
`intent.kind == "validate"` (secret validation); every other kind returns
`ExecutionOutcome(succeeded=False, evidence=None, detail=f"unhandled intent kind: {intent.kind}")`.
Meanwhile two built, tested, two-armed reachability validators exist with **zero** callers from the
agent layer:

- `src/kronos/validate/infra_validator.py` — `validate_service_reachable(canonical, control)` (pure,
  line 28) + `record_infra_finding(engagement, service_id, outcome)` (line 43); `CONTROL_PORT = 9999`.
- `src/kronos/validate/web_validator.py` — `validate_web_endpoint_reachable(canonical, control)` (pure,
  line 29) + `record_web_finding(engagement, endpoint_id, outcome)` (line 44);
  `CONTROL_PATH = "/kronos-negative-control-probe"`.

The autonomous agent therefore cannot invoke infra or web reachability at all. This brief closes that
gap for a **single target** per intent, mirroring the existing single-`Intent`/single-target secret
path — **hermetic only**: the probe is an injected callable, exactly as `infra_validator`/`web_validator`
take a caller-supplied `probe` and open no socket themselves. No live network, no §6 run, no budget.

## §2 — Approach (fixes the values the repo leaves silent; expected test values derive from this prose)

Extend `LiveExecutor` with two injected probe callables and two new intent kinds. Design is fixed by
the existing single-target `execute` pattern (SPEC_BRIEF22) — not a new architecture.

D1. **Injected probes (constructor).** `LiveExecutor.__init__` gains two keyword-only optional params,
    default `None`, alongside the existing `cloud_proxy_endpoint`/`http_hints`:
    - `service_probe: Callable[[str, int], ArmResult] | None = None`
    - `web_probe: Callable[[str, str], ArmResult] | None = None`
    `ArmResult` is `kronos.validate.controls.ArmResult`. The executor opens **no socket**; all network
    (if any, in a future live run) is the injected probe's. Existing params and the `"validate"` path
    are unchanged.

D2. **`probe_service` intent.** `execute` on `intent.kind == "probe_service"`:
    - `target_id` is a `SERVICE` node id. Look it up: `self._graph.get_node("SERVICE", intent.target_id)`.
      Missing → `ExecutionOutcome(False, None, detail=f"no SERVICE node: {intent.target_id}")`.
    - If `service_probe is None` → `ExecutionOutcome(False, None, detail="no service probe configured")`
      (mirrors the `cloud_proxy_endpoint is None` guard, line 66).
    - **Scope gate (G3/manifest; fail-closed):** if the SERVICE node's `in_scope` is not `True` →
      `ExecutionOutcome(False, None, detail=f"SERVICE out of scope: {intent.target_id}")`. No probe call.
    - Else build the two-armed differential exactly as `run_infra_validation_pass` does per node
      (infra_validator.py:74-81): `host = intent.target_id.rsplit(":", 1)[0]`, `port = int(node["port"])`;
      `canonical = replace(service_probe(host, port), label="A_canonical")`,
      `control = replace(service_probe(host, CONTROL_PORT), label="B_negative_control")`;
      `outcome = validate_service_reachable(canonical, control)`.
    - If `outcome.live`: `finding_id = record_infra_finding(engagement, intent.target_id, outcome)` then
      `ExecutionOutcome(succeeded=True, evidence=None, detail=finding_id)`. Else (abstention):
      `ExecutionOutcome(succeeded=False, evidence=None, detail="abstained")`.

D3. **`probe_web` intent.** `execute` on `intent.kind == "probe_web"`, analogous to D2 with the WEB
    validator (web_validator.py:74-82): `target_id` is a `WEB_ENDPOINT` node id; look up
    `get_node("WEB_ENDPOINT", target_id)`; `web_probe is None` → `detail="no web probe configured"`;
    out-of-scope → `detail=f"WEB_ENDPOINT out of scope: {target_id}"`; else read `url`/`method` from the
    node, `parts = urlsplit(url)`, `control_url = f"{parts.scheme}://{parts.netloc}{CONTROL_PATH}"`,
    `canonical = replace(web_probe(url, method), label="A_canonical")`,
    `control = replace(web_probe(control_url, method), label="B_negative_control")`,
    `outcome = validate_web_endpoint_reachable(canonical, control)`; live → `record_web_finding` →
    `detail=finding_id`; else `detail="abstained"`.

D4. **Backward compatibility (fixed).** `intent.kind == "validate"` behaviour is byte-for-byte
    unchanged; any other kind (not in {`validate`, `probe_service`, `probe_web`}) still returns the
    existing `f"unhandled intent kind: {intent.kind}"`. No contract change: `intent.kind` is a free
    string (`contracts.py` does not enumerate kinds), so no edit to `contracts.py`/`__init__.py`/schema.

D5. **No new dependency, no env var, no budget wiring, no live run.** Imports added to
    `live_executor.py` are only from existing modules (`kronos.validate.infra_validator`,
    `kronos.validate.web_validator`, `kronos.validate.controls`, `dataclasses.replace`,
    `urllib.parse.urlsplit`). `record_infra_finding`/`record_web_finding` are imported and called, not
    reimplemented.

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only 98636e5..HEAD` ⊆ set)

1. `SPEC_BRIEF25.md`
2. `src/kronos/agent/live_executor.py` (edit: add `service_probe`/`web_probe` constructor params and the
   `probe_service`/`probe_web` branches in `execute` per §2 D1-D4; import the named helpers from the two
   validator modules and `controls`; do **not** touch the existing `"validate"` path or `_decode_secret_value`).
3. `tests/test_agent_live_executor.py` (append §8 tests after the existing tests; do **not** modify or
   delete any existing test or constant — brief22's tests stay frozen and green).

Base = `origin/main` @ `98636e5`. Never `git add -A`; stage explicit paths only. **Add no new
dependency.** Do **NOT** edit `src/kronos/validate/*` (import only), `contracts.py`, `dispatcher.py`,
`__init__.py`, `schema.py`, `planner.py`, `drivers.py`, `live_driver.py`, `executor.py`, `reviewer.py`,
anything under `src/kronos/budget/`, `requirements.txt`, `pyproject.toml`, `manifest.py`, `.github/`,
or anything under `cybergym/`. The frozen brief22 `LiveExecutor` tests must stay untouched and green.

## §8 — Acceptance criteria (tests-as-rules; expected values from §2 prose, not observed behaviour)

Decide PASS/FAIL from pytest's `SUMMARY:` line, never `$?` (`CLAUDE.md` §3). Every test is hermetic:
in-memory engagement graph, a **mock probe** returning canned `ArmResult`s, and a `nonet`-style socket
assertion on every path that calls `execute`. New tests appended in `tests/test_agent_live_executor.py`.

A. **`probe_service` live → finding.** In-scope `SERVICE` node; mock `service_probe` returns a
   canonical arm that succeeds and a negative-control arm that fails (so the differential is `live`) →
   `execute` returns `succeeded=True` and `detail` == the id returned by `record_infra_finding`; assert a
   `SERVICE --vulnerable_to--> FINDING` row now exists for that service (graph node count rises by the
   finding).
B. **`probe_service` abstention → no finding.** Same node, mock probe where canonical and control are
   indistinguishable (not `live`) → `succeeded=False`, `detail="abstained"`, and **no** FINDING created
   (assert finding count before == after; non-vacuity: assert the SERVICE existed before).
C. **`probe_service` out of scope → fail-closed, no probe.** SERVICE node with `in_scope=False` →
   `succeeded=False`, `detail` starts `"SERVICE out of scope:"`, the mock probe is **never called**
   (assert a call counter stays 0), and no FINDING created.
D. **`probe_service` missing node.** `target_id` with no SERVICE node → `succeeded=False`,
   `detail=f"no SERVICE node: {target_id}"`; probe not called.
E. **`probe_service` probe not configured.** `LiveExecutor` built with `service_probe=None` and a
   `probe_service` intent for an in-scope node → `succeeded=False`, `detail="no service probe configured"`.
F. **`probe_web` live / abstain / out-of-scope / missing / unconfigured** — the five `probe_web`
   analogues of A–E, using `web_probe`, a `WEB_ENDPOINT` node (`url`, `method`), `CONTROL_PATH`, and
   `web_validator`; live case asserts `detail` == `record_web_finding` id and a
   `WEB_ENDPOINT --vulnerable_to--> FINDING` row; out-of-scope uses the `"WEB_ENDPOINT out of scope:"`
   detail and asserts the web probe is never called.
G. **Backward-compat — `validate` unchanged.** A `kind="validate"` intent still routes to the secret
   path (assert an existing brief22 behaviour still holds, e.g. a no-SECRET target returns
   `detail=f"no SECRET node: {target_id}"`); the brief22 tests remain green and unmodified.
H. **Unknown kind unchanged.** A `kind` not in {`validate`,`probe_service`,`probe_web`} →
   `succeeded=False`, `detail=f"unhandled intent kind: {kind}"`.
I. **No network** — a `nonet`-style socket assertion proves `execute` opens no socket on every path
   in A–H (the only connection point is the injected mock probe, which opens nothing).
J. **Scope audit (whole window)** — `git diff --name-only 98636e5..HEAD` ⊆ the §3 set, asserted in a
   test using a distinct base constant `B25_BASE = "98636e5"` and window `f"{B25_BASE}..HEAD"` (never
   `f"{BRIEF_BASE}..HEAD"`, so the frozen brief22/23 seal tests stay green).
K. **Suite green** — full `pytest` reports `0 failed` on the final commit (totals refreshed as the last
   edit); all pre-existing tests, including brief22 `LiveExecutor` tests and the brief22/23/24 seals,
   untouched and green.

## §9 — Done when

All of §8 holds; `LiveExecutor` dispatches `probe_service`/`probe_web` for a single in-scope target via
the existing pure two-armed validators with an injected probe, records a FINDING only on a `live`
differential and abstains otherwise, fail-closes on an out-of-scope or missing target and on a missing
probe, and leaves the `"validate"` path and all other kinds byte-for-byte unchanged; no new dependency,
no env var, no out-of-§3 path changed; no live network or LLM call occurs; and the full suite is green
on the head commit. No live run, no §6 capability, no budget wiring is part of this brief.
