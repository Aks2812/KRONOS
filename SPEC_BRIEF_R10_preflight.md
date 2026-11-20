# SPEC_BRIEF R10 — PREFLIGHT ONLY (BE-G3-5 committed evaluation evidence)

Roadmap item R10 (`docs/roadmap/KRONOS_ROADMAP.md:28`: committed evaluation
evidence for the five-domain run). DoD predicate BE-G3-5
(`docs/governance/KRONOS_DONE.md:50`): one authorized, manifest-bounded
CyberGym/lab run output committed in-repo; exact path and schema are
maintainer-defined and did not exist. Maps G3 (validation evidence). R12
(BE-G2-6) is BLOCKED until R10 passes (D9, `KRONOS_ROADMAP.md:34`).

**This brief is PREFLIGHT DEFINITION ONLY.** It defines the manifest, the
authorized local target, the committed-evidence path and schema, the safety
limits, and the rollback. It authorizes **no** live execution, **no** network
action, **no** credentials, and **no** §6/§8 activation. The run itself is a
separate, later GATE-step requiring explicit maintainer authorization.

**Maintainer decisions (2026-11-20), binding on the implementation brief:**
1. The §3 evidence path and §4 schema are **ACCEPTED** as proposed.
2. `cybergym/**` **stays NEVER-edit**. Output redirection (§4a) MUST be done
   by a **KRONOS-owned wrapper** outside `cybergym/`; the lab target is never
   modified.

## §0 Preflight scope boundary (hard)

- This brief delivers exactly two files on branch `kronos/r10-preflight`:
  `SPEC_BRIEF_R10_preflight.md` (this file) and the seal-tax edit in
  `tests/test_commit_authority.py` (§7). Nothing else.
- NO run of `cybergym/kronos_validation_run.py`, NO `docker compose up`, NO
  `.venv/bin/python cybergym/...`, NO network, NO boto3/requests call, NO
  reading or use of `cybergym/.keys/` private key.
- The implementation that makes a run's output committable (§4/§4a) is NOT
  built here. It is scoped for a subsequent GATE-1-approved brief and MUST be
  a KRONOS-owned wrapper (§4a); `cybergym/kronos_validation_run.py` and all of
  `cybergym/**` stay unmodified (loop NEVER-edit set, reaffirmed by maintainer
  2026-11-20).

## §1 Authorized local target (manifest-bounded)

The sole authorized target is the **fully local** CyberGym three-tier lab —
not a public or live target (`cybergym/README.md:1-7,34-36`):

- Stack (`cybergym/docker-compose.yml`): `localstack` (image pinned
  `localstack/localstack:3.0`, `SERVICES=s3`, bound `127.0.0.1:4566`),
  `init-buckets`, `sigv4-proxy` (bound `127.0.0.1:4567`), `api` (bound
  `127.0.0.1:8091`). Every service bound to `127.0.0.1` only; LocalStack
  community tier, entirely mocked; no real cloud account, no real credentials.
- K=3 planted cross-domain attack chains, graded against
  `cybergym/ground_truth.yaml` (`instrument: cybergym-x-score-v1`, `k: 3`).
- Entrypoint `cybergym/kronos_validation_run.py`: stands the lab up and tears
  it down itself (`docker compose up` not required); runs real mobile ingestion
  on the planted APK, a CYBERGYM-ONLY enrichment step (mechanically asserted
  not to short-cut validation), then the real generic
  `kronos.validate.run_validation_pass`, and checks the result against
  `ground_truth.yaml`. Invocation (for the LATER authorized run, not now):
  `PYTHONPATH=. .venv/bin/python cybergym/kronos_validation_run.py`.

## §2 Manifest (reuse the existing signed manifest)

No new manifest is created. The run is bounded by the already-committed,
Ed25519-signed scope manifest `cybergym/scope_manifest.yaml`:

- `engagement.id: cybergym-x-instrument-v1`; `authorized_by: KRONOS project
  maintainer (Aks2812)`; `client: KRONOS self-test`; `destructive_allowed:
  false`; window `2026-01-01` → `2125-12-08` (deliberate standing-lab window,
  `cybergym/generate_scope_manifest.py:37-39`).
- `scope.in_scope`: `com.kronos.cybergym.*`, `localhost*`, `127.0.0.1*`,
  `http://localhost*`, `http://127.0.0.1*`, `kronos-cybergym-*`,
  `arn:aws:s3:::kronos-cybergym-*`. `scope.excluded: []`.
- Verified only via `kronos.manifest.load_and_verify` against the committed
  public key `cybergym/scope_manifest_pubkey.pem`. The private signing key
  stays gitignored at `cybergym/.keys/cybergym_signing_key.pem`; the preflight
  and the later run both consume the ALREADY-SIGNED manifest and never touch
  the private key.
- Authorization object: per `src/kronos/manifest.py:1-8`, the signed manifest
  is the ONLY authorization object; `run_validation_pass` scope-gates every
  candidate on the pre-computed `in_scope` flag BEFORE any network/boto3 call
  (`src/kronos/validate/runner.py:168-174`).

## §3 Committed-evidence location (maintainer-ACCEPTED 2026-11-20)

In-repo path (ACCEPTED):

```
evaluation_evidence/cybergym-x-score/<run_id>/
```

where `<run_id>` is `cybergym-x-score-v1_<UTC-ISO8601-compact>` (e.g.
`cybergym-x-score-v1_20261120T120000Z`). One directory per authorized run;
runs are additive and never overwritten. Rationale: a new top-level
`evaluation_evidence/` tree keeps committed run evidence out of `docs/`,
`src/kronos/`, and `cybergym/` (the lab target), and is plainly revertible.

## §4 Committed-evidence schema (maintainer-ACCEPTED 2026-11-20)

Each `<run_id>/` directory holds exactly these artifacts. All are derived from
structures that ALREADY exist; none requires new evidence machinery. The
output is placed at the committed path by the KRONOS-owned wrapper (§4a), NOT
by editing `cybergym/`.

1. `run_summary.json` — the authoritative result record. Schema (new JSON
   Schema file `evaluation_evidence/cybergym-x-score/run_summary.schema.json`,
   to be authored in the IMPLEMENTATION brief, not here):
   - `run_id` (string), `instrument` (`"cybergym-x-score-v1"`), `k` (int, 3),
     `x_score` (int, 0..k) — end-to-end chains discovered AND validated.
   - `manifest_id` (string, `sha256:...` from `compute_manifest_id`),
     `manifest_engagement_id` (`"cybergym-x-instrument-v1"`).
   - `lab`: `{ "localstack_image": "localstack/localstack:3.0",
     "services": ["localstack","sigv4-proxy","api"], "bound_host":
     "127.0.0.1" }`.
   - `chains`: list of `{ "id", "discovered": bool, "validated_end_to_end":
     bool, "finding_id"|null, "verdict_tier"|null, "control_disposition"|null }`
     — `verdict_tier`/`control_disposition` read from the persisted FINDING
     node (R9 path A persistence, `src/kronos/schema.py` FINDING columns), not a
     validator return.
   - `started_at`, `ended_at` (UTC ISO 8601), `kronos_commit` (repo HEAD SHA
     the run was executed at).
   - `budget`: the `BudgetSnapshot.to_dict()` output
     (`src/kronos/budget/ledger.py:73-95`).
   - `teardown`: the `TeardownReport.to_dict()` output
     (`src/kronos/cleanup/registry.py:68-81`); `all_ok` MUST be `true`.
2. `evidence/` — the content-addressed proof blobs produced by
   `kronos.evidence.store_evidence` (`src/kronos/evidence.py:26-47`): the
   two-armed request/response bytes backing each validated FINDING.
3. `budget_ledger.json` — `write_ledger_snapshot` output.
4. `teardown_report.json` — `write_teardown_report` output.

**Redaction invariant (hard):** no committed artifact may contain the private
signing key, raw secret VALUES from `ground_truth.yaml`, or any credential.
Evidence blobs are the lab's own mocked request/response bytes against
`127.0.0.1`; the SECRET node's value is NOT written to committed evidence
(only its presence/finding is). This mirrors the §8 checkpoint rule "no
credentials, targets, client identifiers, or manifest contents"
(`KRONOS_RND_CONTRACT.md:101-103`).

## §4a KRONOS-owned evidence wrapper (maintainer decision 2026-11-20)

`cybergym/**` is NEVER-edit. The run's output is committed by a new
**KRONOS-owned** wrapper, to be built in the subsequent IMPLEMENTATION brief,
not here. Design constraints the implementation brief MUST satisfy:

- **Location:** KRONOS-owned code only — a new module under `src/kronos/`
  (e.g. `src/kronos/eval/cybergym_x_score.py`) and/or a repo-root entry script
  outside `cybergym/`. No file under `cybergym/**` is created, edited, moved,
  or deleted.
- **Mechanism:** the wrapper owns the `engagement_dir` and sets it to a path
  under `evaluation_evidence/cybergym-x-score/<run_id>/` (§3) instead of the
  ephemeral `TemporaryDirectory` that `cybergym/kronos_validation_run.py`
  currently uses. It then captures the `run_summary.json` (§4.1), the
  content-addressed `evidence/` blobs, the budget ledger snapshot, and the
  teardown report into that committed directory.
- **Reuse, not fork:** the wrapper reuses `cybergym`'s importable primitives
  by import only — `cybergym.selftest.compose` / `wait_for_services` for
  stand-up/tear-down, and whatever ingestion/enrichment/validation entry
  points `cybergym/kronos_validation_run.py` already exposes as importable
  callables — plus the generic `kronos.validate.run_validation_pass` and
  `kronos.evidence` / `kronos.budget` / `kronos.cleanup` writers. If a needed
  step is NOT importable without editing `cybergym/`, the implementation brief
  STOPS and returns to GATE-1 rather than editing `cybergym/` or silently
  forking the lab logic. It must NOT weaken the CYBERGYM-ONLY enrichment
  no-shortcut assertion (`cybergym/kronos_validation_run.py:10-25`).
- **Fidelity:** the wrapper changes only WHERE output lands, never WHAT is
  validated; it hands the same completed graph to the same generic
  `run_validation_pass` any engagement uses.

## §5 Safety limits (enforced by existing machinery)

- **Locality:** every service bound `127.0.0.1` only; LocalStack mocked; no
  real cloud/credentials (`cybergym/docker-compose.yml:1-8`,
  `README.md:34-36`).
- **Scope gate:** `run_validation_pass` never calls a validator (and never
  makes a network/boto3 call) on an out-of-scope candidate
  (`runner.py:168-174`); `CLOUD_RESOURCE` skipped when no cloud proxy endpoint.
- **Non-destructive:** `destructive_allowed: false` in the manifest.
- **Budget:** the run is budget-governed; `BudgetLedger`/`BudgetExceeded` cap
  validation attempts and tool invocations (`runner.py` budget chokepoint;
  `ledger.py`). A `budget.yaml` is written into the engagement dir.
- **Manifest window + signature:** `load_and_verify` rejects unsigned,
  tampered, or out-of-window manifests before any run.
- **No secret egress:** redaction invariant §4.

## §6 Rollback

- **Lab:** `docker compose down -v` tears everything down and leaves nothing
  running (`cybergym/README.md:14-18`); `kronos_validation_run.py` performs
  teardown itself via `kronos.cleanup.CleanupRegistry` and asserts
  `TeardownReport.all_ok`.
- **Repo:** all preflight work is confined to branch `kronos/r10-preflight`;
  no `main` write occurs until a separate GATE-2 authorization. The committed
  evidence (when the later run is authorized) is additive under
  `evaluation_evidence/` and revertible with a single `git revert`.
- **Ephemeral state:** the current run writes to a `TemporaryDirectory`
  discarded on exit; nothing persists unless the IMPLEMENTATION brief
  deliberately redirects it to the committed path.

## §7 Seal-tax (`tests/test_commit_authority.py`)

Whole-window seal tax. Surgical edit only, weakening no other assertion:

1. Seal R9 window to its merge SHA: add `R9_MERGE = "44d0771"` (squash merge
   of PR #62) and change the scope-audit assertion `set(names(f"{R9_BASE}..
   HEAD")) <= R9_SECTION_10` to `set(names(f"{R9_BASE}..{R9_MERGE}")) <=
   R9_SECTION_10`.
2. Open R10 window: add `R10_BASE = "44d0771"` and
   `R10_SECTION_10 = {"SPEC_BRIEF_R10_preflight.md",
   "tests/test_commit_authority.py"}`, and assertion
   `set(names(f"{R10_BASE}..HEAD")) <= R10_SECTION_10`.

## §8 Acceptance (§8) and risks

Acceptance of THIS preflight brief:
- The two files above present; full canonical suite 0 failed via
  `TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" rtk test .venv/bin/python -m pytest -q`,
  decided on the runner SUMMARY line, never `$?`.
- No live run performed, no network, no credentials.

Resolved maintainer decisions (2026-11-20):
- **cybergym/ edit boundary:** RESOLVED — `cybergym/**` stays NEVER-edit.
  Output redirection is done by a KRONOS-owned wrapper (§4a); no hand-apply,
  no boundary exception.
- **Path/schema:** RESOLVED — §3 path and §4 schema ACCEPTED as proposed.

Remaining note (not blocking):
- **No contract §7.2:** the roadmap's "S1/§7.2 CyberGym" cite refers to
  `docs/research/KRONOS_RESEARCH_RECORD.md §7.2`, not the contract (the
  contract has no §7.2). Noted to avoid a dangling governance reference.

## §9 Non-goals

Live runs, the actual X-score measurement, any `cybergym/` edit, the
`run_summary.schema.json` file itself, the output-redirection code, R12
(BE-G2-6), and any `src/kronos/` change are all OUT of scope for this preflight
brief. They belong to the subsequent authorized GATE-step.
