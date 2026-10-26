# SPEC_BRIEF22 S8 Agent layer — live Executor (agent intents → real validators; hermetic tests, no live run here)

**Stage:** S8 agent layer, live-execution increment 1 of the option-B sequence (PROGRESS.md SEQ 129).
This brief adds the **first concrete, non-mock `Executor`**: a `LiveExecutor` that turns an agent
`Intent` into a real validation against the existing KRONOS validators, producing the evidence the
dispatcher promotes on. **This brief ships code + hermetic tests only — it performs no live run and
opens no network.** The §6-gated live agent run is a later step. CyberGym only; no live targets in
this brief; the executor's actual network use happens only later under the SEQ 126 §6 grant.

## §1 — Problem

`src/kronos/agent/executor.py` defines the `Executor` Protocol and `ExecutionOutcome`, but the only
implementation is `MockExecutor` (`executor.py:24-34`) returning scripted outcomes — its docstring
states "No concrete live executor". The dispatcher's promotion path is ready
(`dispatcher.py:94-107`: `executor.execute(intent)` → if `outcome.succeeded and outcome.evidence is
not None`, `attach_evidence(..., kind=EVIDENCE_KIND, ...)` then `advance_finding_status(...,
"reachable")`), and the real validators already exist and are non-mock
(`src/kronos/validate/http_validator.py` `validate_api_token`,
`src/kronos/validate/cloud_validator.py` `validate_cloud_credential`, resolved via
`src/kronos/validate/registry.py` `classify_validator_kind`/`get_validator` and
`src/kronos/validate/candidates.py` `find_candidate_targets_for_secret`). What is missing is the
`Executor` implementation that connects an `Intent` to that machinery.

## §2 — Approach

Add `LiveExecutor` to a new module `src/kronos/agent/live_executor.py`, satisfying the existing
`Executor` Protocol (`execute(self, intent: Intent) -> ExecutionOutcome`) by **reusing the existing
public validation helpers** — it mirrors the per-secret resolution block of `run_validation_pass`
(`src/kronos/validate/runner.py:159-196`) for a single secret. It adds **no** change to any file
under `src/kronos/validate/`.

**Design decisions (these fix the values the repo leaves silent; expected test values derive from
this prose):**

- **D1 — `intent.target_id` is a `SECRET` id.** A `"validate"` intent names the secret to validate.
  The executor reuses the existing secret→target direction
  (`find_candidate_targets_for_secret(graph, secret_id)`); it does **not** require any new
  target→secret reverse lookup. This is coherent with `dispatcher._commit`, which adds a
  `derived_from FINDING→SECRET` edge when `verdict.target_type == "SECRET"` (`dispatcher.py:58-60`).
- **D2 — recognized `intent.kind` is exactly `"validate"`.** Any other `kind` returns
  `ExecutionOutcome(succeeded=False, evidence=None, detail="unhandled intent kind: <kind>")` and
  makes no validator call. The executor never raises on an unrecognized kind.
- **D3 — one intent resolves one secret against its in-scope candidates.** The executor iterates
  `find_candidate_targets_for_secret(graph, secret_id)` exactly as the runner does: it filters to
  the candidate `type` matching the secret's classified validator kind
  (`"CLOUD_RESOURCE"` iff `classify_validator_kind == "cloud_credential_pair"`, else
  `"API_ENDPOINT"`), skips out-of-scope candidates (`candidate.in_scope is False`) **before** any
  call, and skips `CLOUD_RESOURCE` candidates when `cloud_proxy_endpoint is None`. It calls the
  validator on each surviving candidate and returns the **first** live outcome; if none is live, it
  returns a non-succeeded outcome.
- **D4 — construction config is passed in, not read from the graph.** `LiveExecutor(graph,
  engagement_dir, *, cloud_proxy_endpoint: str | None = None, http_hints: dict[str, dict] | None =
  None)` — the same two inputs `run_validation_pass` takes (`runner.py:122-129`), since the proxy
  endpoint and per-endpoint HTTP hints live nowhere in the graph. **The site that constructs
  `LiveExecutor` for a real run is out of scope here** (it belongs to the later live-run step);
  this brief only defines the class. Budget charging is **not** added in this increment (deferred to
  the live-run step).

**Resolution flow of `execute(intent)`:**

1. If `intent.kind != "validate"` → return the D2 unhandled outcome.
2. `secret = graph.get_node("SECRET", intent.target_id)`; if absent → `ExecutionOutcome(False,
   None, detail=...)`.
3. Decode the value: `value_ref` is `"sha256:<hash>"`; read bytes via
   `kronos.evidence.get_evidence(engagement_dir, sha256)` and `.decode("utf-8")`. A missing or
   non-UTF-8 blob degrades to `""` (never crashes), mirroring `runner._decode_secret_value`.
4. `kind = classify_validator_kind(decoded_value)`; `validator = get_validator(kind)`; if `validator
   is None` (e.g. `"unknown"`) → non-succeeded outcome.
5. Iterate candidates per D3; call `validator(decoded_value, candidate.id, **hint)` for
   `API_ENDPOINT` (`hint = http_hints.get(candidate.id, {})`) or
   `validator(decoded_value, candidate.id, cloud_proxy_endpoint)` for `CLOUD_RESOURCE`.
6. **Map `ValidationOutcome` → `ExecutionOutcome`:** `succeeded = outcome.live`;
   `evidence = outcome.evidence or None` (empty `b""` → `None`, so a non-live arm never trips the
   dispatcher's `evidence is not None` promotion gate); `detail = outcome.detail`. Return on the
   first live outcome; otherwise return the last non-live outcome's mapping, or a
   `succeeded=False, evidence=None` outcome if no candidate was eligible.

Export `LiveExecutor` from `src/kronos/agent/__init__.py` alongside `Executor`/`MockExecutor`.

**Accepted minor duplication:** the ~15-line resolution loop mirrors `runner.py:159-196` rather than
refactoring a shared helper out of the load-bearing validation core. This keeps §3 off
`src/kronos/validate/` (surgical, least-risk); §8-G below guards the mapping. A future increment may
DRY this if it earns its keep.

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only 1405ed7..HEAD` ⊆ set)

1. `SPEC_BRIEF22.md`
2. `src/kronos/agent/live_executor.py` (new module: `LiveExecutor`)
3. `src/kronos/agent/__init__.py` (edit: import + `__all__` entry for `LiveExecutor`)
4. `tests/test_agent_live_executor.py` (new: §8 criteria)

Base = `origin/main` @ `1405ed7`. Never `git add -A`; stage explicit paths only.
Do **NOT** edit anything under `src/kronos/validate/`, nor `dispatcher.py`, `executor.py`,
`planner.py`, `reviewer.py`, `contracts.py`, `drivers.py`, `schema.py`, `query.py`, `manifest.py`,
`.github/`, or anything under `cybergym/`. The frozen `test_L`/`test_M` audits in
`tests/test_agent_dispatcher.py` must stay untouched and green.

## §8 — Acceptance criteria (tests-as-rules; `tests/test_agent_live_executor.py`)

Decide PASS/FAIL from pytest's `SUMMARY:` line, never `$?` (CLAUDE.md §3). All expected values derive
from §2's prose (D1–D4 + the mapping rule), not from observed behaviour. **Every test is hermetic:**
build the graph with a `tmp_path` engagement fixture (the existing `conftest.py` pattern) seeded
with `SECRET`/`API_ENDPOINT`/`CLOUD_RESOURCE` nodes and `leaks`/`references` edges via existing
helpers READ-ONLY; inject validator results by monkeypatching
`kronos.validate.http_validator.validate_api_token` and
`kronos.validate.cloud_validator.validate_cloud_credential` (the registry resolves late, so patching
the module attribute is the project's hermetic pattern); and apply a `nonet`-style
`socket`/`create_connection` patch so a real network call would fail the test.

A. **API live → promotable outcome.** A `"validate"` intent whose `target_id` is a seeded SECRET that
   `classify_validator_kind` maps to the api kind, with an in-scope `API_ENDPOINT` candidate and the
   injected `validate_api_token` returning a live `ValidationOutcome` (live=True, non-empty
   evidence) → `execute` returns `ExecutionOutcome(succeeded=True, evidence=<those exact bytes>,
   detail=<outcome.detail>)`.
B. **Cloud live → promotable outcome.** Same for a cloud-kind SECRET with an in-scope
   `CLOUD_RESOURCE` candidate, `cloud_proxy_endpoint` supplied, injected `validate_cloud_credential`
   live → `succeeded=True`, evidence passed through.
C. **Not live → not promotable.** Injected validator returns `live=False, evidence=b""` →
   `ExecutionOutcome(succeeded=False, evidence=None)` (the `b"" → None` mapping, so the dispatcher
   gate would not promote).
D. **Unrecognized kind → no call, no raise.** An intent with `kind="probe"` →
   `ExecutionOutcome(succeeded=False, evidence=None)` and the injected validators are asserted
   **not called**.
E. **Out-of-scope candidate → validator never called.** The only candidate has `in_scope=False` →
   `succeeded=False` and the injected validator is asserted **not called** (scope-gated before any
   call); the `nonet` patch corroborates no network.
F. **Undecodable / no-validator secret → graceful non-success.** A SECRET whose `value_ref` points
   at a missing blob (decodes to `""` → `classify_validator_kind("")` → no validator) →
   `ExecutionOutcome(succeeded=False, evidence=None)`, no raise.
G. **Mapping is exact.** Assert the three-field mapping (`succeeded=outcome.live`,
   `evidence=outcome.evidence or None`, `detail=outcome.detail`) against an injected outcome with
   known fields — a change detector for the §2 mapping rule.
K. **No network** — a `test_K`-style assertion proves `execute` opens no socket on every path above.
F2. **Scope audit (whole window)** — `git diff --name-only 1405ed7..HEAD` ⊆ the §3 set.
G2. **Suite green** — full `pytest` reports `0 failed` on the final commit (totals refreshed as the
   last edit); `test_L`/`test_M` in `test_agent_dispatcher.py` untouched and green.

## §9 — Done when

All of §8 holds, the whole-window scope audit is clean, `LiveExecutor` satisfies the `Executor`
Protocol and maps `ValidationOutcome→ExecutionOutcome` per §2, no file under `src/kronos/validate/`
or any other out-of-§3 path changed, no live network occurs in the test suite, and the full suite is
green on the head commit. The live agent run that actually constructs and drives `LiveExecutor`
against the CyberGym range remains a later, §6-gated step — not part of this brief.
