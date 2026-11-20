# SPEC_BRIEF R10 — IMPLEMENTATION (BE-G3-5 committed evaluation evidence)

Successor to `SPEC_BRIEF_R10_preflight.md` (merged PR #63, squash `391c938`).
Roadmap item R10 (`docs/roadmap/KRONOS_ROADMAP.md:28`): committed evaluation
evidence for the five-domain CyberGym run. DoD predicate BE-G3-5
(`docs/governance/KRONOS_DONE.md:50`): one authorized, manifest-bounded
CyberGym/lab run output committed in-repo. Maps G3 (validation evidence). R12
(BE-G2-6) stays BLOCKED until R10 passes (`KRONOS_ROADMAP.md:34`).

**Scope of THIS brief: DEFINITION of the KRONOS-owned evidence wrapper and the
`run_summary.schema.json` contract.** It authorizes building that wrapper and
schema in a subsequent GATE-approved build step, and — separately again — a
single bounded run under §6/§8. This brief authorizes **no** live execution,
**no** network, **no** credentials, **no** `§6/§8` activation, and builds **no**
wrapper code and **no** schema file. Per the GATE-1 authorization
(2026-11-20): *brief only; no build, run, or §6/§8 activation.*

**Maintainer decisions carried forward (binding):**
1. `§3` evidence path and `§4` schema from the preflight brief are ACCEPTED.
2. `cybergym/**` stays NEVER-edit. Output redirection is done by a KRONOS-owned
   wrapper outside `cybergym/`; the lab target is never modified.

## §0 Feasibility finding (reuse-by-import, GATE-1 required resolution)

The GATE-1 authorization required resolving reuse-by-import feasibility and a
STOP-to-GATE-1 if a needed step is not reusable without editing `cybergym/**`.

**Finding: FEASIBLE without editing `cybergym/**`. STOP clause NOT triggered.**
Evidence (read-only, `cybergym/kronos_validation_run.py` unless noted):

- The pipeline entry points are importable module-level callables (column-0
  `def`, not nested): `_run_pipeline(engagement_dir: Path) -> int` (`:201`),
  `_assert_enrichment_did_not_shortcut_anyone(graph, secret_id) -> None`
  (`:168`), `main() -> int` (`:354`). No `__all__` restricts import.
- `main()` builds its own ephemeral engagement dir via
  `TemporaryDirectory(prefix="kronos-cybergym-run-")` (`:366`) and calls
  `_run_pipeline(engagement_dir)` (`:384`). It takes no output-path argument;
  its only CLI args are `--no-teardown` / `--no-standup` (`:355-358`).
- `_run_pipeline` returns an `int` status and communicates results by `print`
  (e.g. `X-SCORE: {x_score}/3`, `:333-334`) and by side-effect writers
  (`store_evidence`, `write_ledger_snapshot`, `write_teardown_report`) into the
  engagement dir — **not** by a serializable return object.
- Importing the module transitively imports `cybergym/selftest.py`, whose only
  import-time executable side effect is a filesystem read at
  `cybergym/selftest.py:44` (`strings.xml`); `compose` (`:262`) and
  `wait_for_services` (`:266`) are function defs, so `docker`/`requests` run
  only when called. No network, no `docker`, and no private key at import;
  `kronos_validation_run.py:140` loads only the PUBLIC key
  `scope_manifest_pubkey.pem`. The private key `cybergym/.keys/` is never
  referenced by this module.

**Consequence for the wrapper design (binding on the build step):** because
`_run_pipeline` does not return a serializable result, the KRONOS-owned wrapper
MUST obtain the committed-evidence data WITHOUT editing `cybergym/**` by:
(a) owning the `engagement_dir` it passes to the pipeline and pointing it at the
`§3` committed path; (b) reusing the same stand-up/tear-down and writer
primitives the pipeline uses (`cybergym.selftest.compose`/`wait_for_services`,
and `kronos.evidence` / `kronos.budget` / `kronos.cleanup` writers); and
(c) reading the pipeline's own side-effect artifacts plus its integer exit code
and captured `X-SCORE:` stdout line to assemble `run_summary.json`. If, at build
time, assembling a faithful `run_summary.json` is found to require any edit to
`cybergym/**` or a fork of its logic, the build STOPS and returns to GATE-1.

The CYBERGYM-ONLY enrichment no-shortcut guardrail
(`cybergym/kronos_validation_run.py:10-25` docstring; mechanically enforced by
`_assert_enrichment_did_not_shortcut_anyone` at `:168`, which raises
`AssertionError` unless the enrichment-created `SECRET` node's `status` is still
exactly `"extracted"`) MUST NOT be weakened, bypassed, or duplicated in a
weakened form by the wrapper. The wrapper runs the real pipeline, so this
assertion continues to execute unchanged inside it.

## §1 Deliverables of the subsequent BUILD step (defined here, not built here)

1. **KRONOS-owned wrapper** — new code under `src/kronos/eval/` (e.g.
   `src/kronos/eval/cybergym_x_score.py`) and/or a repo-root entry script
   outside `cybergym/`. `src/kronos/eval/` does not yet exist and is created by
   the build step. No file under `cybergym/**` is created, edited, moved, or
   deleted.
2. **`evaluation_evidence/cybergym-x-score/run_summary.schema.json`** — the JSON
   Schema the wrapper's `run_summary.json` validates against (fields per `§2`).
3. The wrapper's own unit tests (hermetic: no live run, no network) asserting
   it directs `engagement_dir` to the `§3` path, assembles a schema-valid
   `run_summary.json` from fixture pipeline outputs, and preserves the `:168`
   no-shortcut assertion.

## §2 `run_summary.json` schema contract (fields, ACCEPTED path)

Schema file: `evaluation_evidence/cybergym-x-score/run_summary.schema.json`
(JSON Schema draft 2020-12). `run_summary.json` fields (unchanged from preflight
`§4.1`, restated as the authoritative contract):

- `run_id` (string), `instrument` (const `"cybergym-x-score-v1"`), `k` (int,
  const 3), `x_score` (int, 0..k) — chains discovered AND validated end-to-end.
- `manifest_id` (string `sha256:...` from `compute_manifest_id`),
  `manifest_engagement_id` (const `"cybergym-x-instrument-v1"`).
- `lab`: `{ "localstack_image": "localstack/localstack:3.0", "services":
  ["localstack","sigv4-proxy","api"], "bound_host": "127.0.0.1" }`.
- `chains`: list of `{ "id", "discovered": bool, "validated_end_to_end": bool,
  "finding_id"|null, "verdict_tier"|null, "control_disposition"|null }` — tiers
  read from the persisted FINDING node (R9 path-A persistence,
  `src/kronos/schema.py` FINDING columns), not a validator return.
- `started_at`, `ended_at` (UTC ISO 8601), `kronos_commit` (repo HEAD SHA the
  run executed at).
- `budget`: `BudgetSnapshot.to_dict()` (`src/kronos/budget/ledger.py:73-95`).
- `teardown`: `TeardownReport.to_dict()` (`src/kronos/cleanup/registry.py:68-81`);
  `all_ok` MUST be `true`.

All fields `required`; `additionalProperties: false` at the top level and on
`lab`. The schema is authored in the build step, not in this brief.

## §3 Committed-evidence location (ACCEPTED, unchanged)

```
evaluation_evidence/cybergym-x-score/<run_id>/
```

`<run_id>` = `cybergym-x-score-v1_<UTC-ISO8601-compact>`. One additive directory
per authorized run; never overwritten. Contents when the run is later
authorized: `run_summary.json`, `evidence/` content-addressed blobs,
`budget_ledger.json`, `teardown_report.json`.

## §4 Redaction invariant (hard, unchanged)

No committed artifact may contain the private signing key, raw secret VALUES
from `ground_truth.yaml`, or any credential. Evidence blobs are the lab's own
mocked `127.0.0.1` request/response bytes; the SECRET node's value is never
written to committed evidence (only its presence/finding). Mirrors the §8
checkpoint rule "no credentials, targets, client identifiers, or manifest
contents" (`KRONOS_RND_CONTRACT.md:101-103`).

## §5 Hard boundaries (this brief and its build step)

- `cybergym/**` NEVER-edit (reaffirmed); `.claude/**`, `.github/**`,
  `docs/governance/**`, and the signed manifest are off-limits.
- No network, no `docker compose up`, no `boto3`/`requests` call, no reading or
  use of `cybergym/.keys/` private key.
- The bounded RUN that produces real committed evidence is a SEPARATE, later
  `§6/§8` step requiring its own explicit maintainer authorization ("stop
  before running"). It is NOT authorized by this brief.

## §6 Seal-tax (`tests/test_commit_authority.py`)

Whole-window seal tax, surgical, weakening no other assertion:

1. Seal the R10 preflight window to its merge SHA: add
   `R10_MERGE = "391c938"` (squash merge of PR #63) and change the scope-audit
   assertion `set(names(f"{R10_BASE}..HEAD")) <= R10_SECTION_10` to
   `set(names(f"{R10_BASE}..{R10_MERGE}")) <= R10_SECTION_10`.
2. Open the R10-implementation window: add `R10I_BASE = "391c938"` and
   `R10I_SECTION_10 = {"SPEC_BRIEF_R10_impl.md", "tests/test_commit_authority.py"}`,
   and assertion `set(names(f"{R10I_BASE}..HEAD")) <= R10I_SECTION_10`.

## §7 Acceptance (§8)

Acceptance of THIS brief:
- Exactly two files on branch `kronos/r10-impl-brief`: `SPEC_BRIEF_R10_impl.md`
  and the `tests/test_commit_authority.py` seal edit. Nothing else; no
  `cybergym/**`, `src/kronos/**`, `.claude/**`, `.github/**`, or governance file
  touched.
- Full canonical suite 0 failed via
  `TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" rtk test .venv/bin/python -m pytest -q`,
  decided on the runner SUMMARY line, never `$?`.
- The `§0` reuse-by-import feasibility finding is recorded and the STOP-to-GATE-1
  clause is not triggered.
- No live run, no network, no credentials, no wrapper code, no schema file.

## §8 Risks

- (a) `_run_pipeline` returns only an `int`; the wrapper assembles
  `run_summary.json` from side-effect artifacts and captured stdout rather than a
  structured return. RESOLVED-by-design in `§0(c)`; if faithful assembly needs a
  `cybergym/**` edit at build time, STOP to GATE-1.
- (b) Importing `cybergym.kronos_validation_run` reads
  `cybergym/mobile/apk_src/res/values/strings.xml` at import
  (`cybergym/selftest.py:44`). The build step's hermetic unit tests must import
  through the real repo tree (file present) or inject the pipeline callables, and
  MUST NOT delete or edit that file.

## §9 Non-goals

The wrapper code, `run_summary.schema.json` itself, any live run or real X-score
measurement, any `cybergym/**` edit, R12 (BE-G2-6), and any other `src/kronos/**`
change are OUT of scope for this brief. They belong to the subsequent
GATE-approved build step and the separately authorized `§6/§8` run.
