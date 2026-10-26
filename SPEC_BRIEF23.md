# SPEC_BRIEF23 S8 Agent layer — live Driver (LLM-backed intent proposer; hermetic tests, no live LLM here)

**Stage:** S8 agent layer, live-execution increment 2 of the option-B sequence (PROGRESS.md SEQ 133).
This brief adds the first concrete non-mock `Driver`: a `LiveDriver` that produces a structured
`reason()` payload from a `GraphSummary` by delegating to an **injected client** (the real client,
built at the later live-run step, calls the Anthropic-compatible endpoint for model
`claude-sonnet-5`). **This brief ships code + hermetic tests only — the unit tests inject a fake
client and make no real LLM call and open no network.** CyberGym only.

## §1 — Problem

`src/kronos/agent/drivers.py` defines the `Driver` Protocol (`reason(self, summary: GraphSummary) ->
dict`) with only `MockDriver` (scripted dicts). `planner.plan(summary, driver)` calls
`driver.reason(summary)` and validates the result through `validate_reason_payload`
(`contracts.py:29-59`). To drive the agent loop from a model, a concrete `Driver` must build a
request from the `GraphSummary`, obtain the model's response, and return a dict for the contract gate
to validate. No LLM-calling code, no Anthropic/HTTP client dependency, and no env-config pattern
exist in `src/kronos/` today (research SEQ 133).

## §2 — Approach

Add `LiveDriver` to a new module `src/kronos/agent/live_driver.py`, satisfying the existing `Driver`
Protocol. It makes **no network call itself** and imports **no new dependency**: the transport is an
**injected client callable**, so the LLM/HTTP specifics live in a thin wrapper constructed later at
the live-run step (that wrapper may use `requests`, already a pinned dependency — this brief adds
none).

**Design decisions (fix the values the repo leaves silent; expected test values derive from this
prose):**

- **D1 — injected client, constructor config.** `LiveDriver(client, *, model: str =
  "claude-sonnet-5")`. `client` is any callable `client(prompt: str) -> str` returning the model's
  raw text response. `model` is stored and included in the prompt/metadata. **No env var is read**
  (matches the repo's constructor-injection pattern); the endpoint/model wiring lives in the injected
  client, built outside this brief.
- **D2 — prompt from `GraphSummary`.** `reason(summary)` builds a prompt string embedding the three
  `GraphSummary` fields (`finding_count`, `secret_count`, `findings_by_status`) and an instruction to
  return a single JSON object of the `reason()` shape (`{"complete": bool, "intents": [{"kind",
  "target_id", "rationale"}, ...]}`). Only these counts are sent — never secrets or finding content.
- **D3 — JSON extraction, no silent repair.** From the client's text response, extract the first
  JSON object (tolerating a leading/trailing ```json … ``` fence and surrounding prose) and
  `json.loads` it. On no parseable JSON object, raise `ValueError("live driver: no JSON object in
  response")`. `reason()` returns the parsed dict **as-is** — it does **not** validate, truncate, or
  mutate it; `planner.plan`'s `validate_reason_payload` is the sole contract gate (so an
  over-`MAX_INTENTS` or malformed-but-parseable payload is rejected downstream, not hidden here).
- **D4 — budget deferred.** This increment wires **no** `BudgetLedger` into the Driver (exactly as
  SPEC_BRIEF22 deferred budget). The `llm_tokens`/`llm_cost_usd` charge and its operator `budget.yaml`
  opt-in (ceilings default to 0, `limits.py:58-59`) belong to the later live-run step and are **out
  of scope here**.

Export `LiveDriver` from `src/kronos/agent/__init__.py` alongside `Driver`/`MockDriver`.

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only 056f441..HEAD` ⊆ set)

1. `SPEC_BRIEF23.md`
2. `src/kronos/agent/live_driver.py` (new module: `LiveDriver`)
3. `src/kronos/agent/__init__.py` (edit: import + `__all__` entry for `LiveDriver`)
4. `tests/test_agent_live_driver.py` (new: §8 criteria)

Base = `origin/main` @ `056f441`. Never `git add -A`; stage explicit paths only.
Do **NOT** edit `contracts.py`, `planner.py`, `drivers.py`, `dispatcher.py`, `executor.py`,
`live_executor.py`, `reviewer.py`, `schema.py`, `query.py`, anything under `src/kronos/budget/` or
`src/kronos/validate/`, `requirements.txt`, `pyproject.toml`, `manifest.py`, `.github/`, or anything
under `cybergym/`. **Add no new dependency.** The frozen `test_L`/`test_M` audits in
`tests/test_agent_dispatcher.py` must stay untouched and green.

## §8 — Acceptance criteria (tests-as-rules; `tests/test_agent_live_driver.py`)

Decide PASS/FAIL from pytest's `SUMMARY:` line, never `$?` (CLAUDE.md §3). Expected values derive from
§2's prose (D1–D4), not observed behaviour. **Every test is hermetic:** inject a fake `client`
callable (no real model, no SDK); apply a `nonet`-style `socket`/`create_connection` patch so any
real network call fails; build any `GraphSummary` directly (it is a plain frozen dataclass).

A. **Contract-valid intents payload.** A fake client returning a JSON object with `complete=false`
   and ≤4 well-formed intents → `reason(summary)` returns that dict, and `validate_reason_payload`
   accepts it (returns a `ReasonResult` with the expected intents).
B. **Fenced JSON.** A fake client wrapping the JSON in a ```json … ``` fence with surrounding prose
   → `reason` extracts and returns the same dict (accepted by `validate_reason_payload`).
C. **Complete payload.** A fake client returning `{"complete": true, "intents": []}` → `reason`
   returns it and `validate_reason_payload` accepts (`ReasonResult(complete=True, intents=())`).
D. **No JSON → ValueError.** A fake client returning text with no JSON object → `reason` raises
   `ValueError`.
E. **Prompt carries the summary + is pass-through.** Assert the prompt the fake client received
   contains the `GraphSummary` numbers (`finding_count`, `secret_count`), and that `reason` returns
   the client's payload unmodified — e.g. a client returning 5 intents yields a dict whose `intents`
   has length 5 (no truncation), which `validate_reason_payload` then rejects with
   `ContractViolation` (proves the Driver defers to the contract gate, per D3).
K. **No network** — a `test_K`-style assertion proves `reason` opens no socket on every path above.
F2. **Scope audit (whole window)** — `git diff --name-only 056f441..HEAD` ⊆ the §3 set.
G2. **Suite green** — full `pytest` reports `0 failed` on the final commit (totals refreshed as the
   last edit); `test_L`/`test_M` in `test_agent_dispatcher.py` untouched and green.

## §9 — Done when

All of §8 holds, the whole-window scope audit is clean, `LiveDriver` satisfies the `Driver` Protocol,
reason() builds a summary-derived prompt and returns the client's JSON payload unmodified (raising on
unparseable output), no new dependency is added and no env var is read, no out-of-§3 path changed, no
live network or LLM call occurs in the test suite, and the full suite is green on the head commit.
The live agent run that constructs a real client and drives `LiveDriver` + `LiveExecutor` against the
CyberGym range — including the `budget.yaml` `llm_tokens` opt-in — remains a later, §6-gated step,
not part of this brief.
