# SPEC_BRIEF12 — S4.1 Infra validation (two-armed reachability → FINDING)

**Stage:** S4 (research record v6 §6 — infra validation, two-armed + control disposition).
**Goal:** G1 (second protocol family) + G3 (two-armed evidence, abstention when undiscriminated).
**Depends on:** S3 infra ingestion (PR #19 / `19c9464`), S1 differential engine.
**Authorization:** maintainer §6-autonomy grant (checkpoint SEQ 69) + architecture decision SEQ 70:
**Q1 = FINDING via edge**, **Q2 = reuse `Classification` enum**. GATE-1 self-approved by Opus after
validating this brief against the researcher's cited findings.

## §1 — Problem

S3 writes `HOST`/`SERVICE` nodes but nothing validates them. S4.1 adds the first infra validator:
a two-armed reachability differential over in-scope `SERVICE` nodes, recording a proven-reachable
verdict as a `FINDING` linked `SERVICE --vulnerable_to--> FINDING`. `HOST`/`SERVICE` have no status
column (`schema.py:30-39`), so the verdict attaches to a `FINDING` (Q1), which carries
`status`/`confidence` (`schema.py:86-91`). Disposition reuses the existing `Classification` enum (Q2).

## §2 — Approach

Add `src/kronos/validate/infra_validator.py`:

- `validate_service_reachable(canonical_probe: ArmResult, control_probe: ArmResult) -> ValidationOutcome`
  — a PURE function (no I/O, no graph writes). The caller supplies the two arms already probed,
  labelled exactly `A_canonical` and `B_negative_control`. It calls
  `run_differential([canonical_probe, control_probe], kind="infra")` (controls.py) and returns a
  `ValidationOutcome(live, evidence, detail, classification, control_outcome, discriminated)` mapped
  1:1 from the `DifferentialResult`. `evidence` is a non-empty, secret-free byte summary of the two
  arm outcomes (labels + success + status only) and is REQUIRED non-empty only when `live` is True
  (ValidationOutcome invariant, types.py:57-66).
- `run_infra_validation_pass(engagement, *, probe) -> InfraValidationReport` — the writer/orchestrator:
  1. Enumerate **in-scope** `SERVICE` nodes from the graph (`in_scope == True` only).
     **Out-of-scope services are never probed** — this is the CyberGym-only guarantee.
  2. For each in-scope SERVICE `host:port/proto`: build the canonical arm by calling
     `probe(host, port)` and the negative-control arm by calling `probe(host, <closed control port>)`
     where the control port is a **closed port on the SAME in-scope host** (never a different host) —
     so the control never sends traffic outside the CyberGym range.
  3. `outcome = validate_service_reachable(canonical_arm, control_arm)`.
  4. On `outcome.live` (⟺ `classification == "live_discriminated"`): create a `FINDING` and link it.
     Otherwise create nothing (G3 abstention).
- `record_infra_finding(engagement, service_id, outcome) -> str` — creates the FINDING deterministically:
  - `finding_id = f"finding:infra-reachable:{service_id}"` (deterministic → idempotent MERGE).
  - `engagement.upsert_node("FINDING", finding_id, {"source": "infra_validator", "title": …,
    "severity": "info", "status": "hypothesis"})` — NOTE: do NOT pass `confidence` or `in_scope`
    (both in `NODE_PROPS_FORBIDDEN`, schema.py:212); `status` is create-only (schema.py:190).
  - `engagement.upsert_edge("vulnerable_to", service_id, "SERVICE", finding_id, "FINDING")`
    (edge pair `("SERVICE","FINDING")`, schema.py:125).
  - `advance_finding_status(engagement, finding_id, "reachable")` — the sole forward write path
    (lifecycle.py); `hypothesis → reachable` is a legal transition (FINDING_TRANSITIONS); the lifecycle
    derives `confidence` (reachable-no-evidence → 7, lifecycle.py `derive_confidence`). Do NOT set
    confidence here.

Edit `src/kronos/validate/controls.py` — the ONLY code change to the differential engine:
- widen `run_differential(..., *, kind: Literal["http", "cloud"])` to include `"infra"`.
- make the two-arm branch handle infra: change `if kind == "http":` to `if kind in ("http", "infra"):`
  (infra uses the identical `A_canonical` + `B_negative_control` logic: canonical succeeds & control
  rejected → `live_discriminated`; control also succeeds → `indiscriminate_target`; canonical fails →
  `not_live`; both transport-error → `inconclusive`). Change nothing else; do not touch the cloud branch,
  `derive_negative_control`, or the `self_request_malformed` guard.

No new dependency. No event emission (existing validators/runner emit none; `events.py` untouched).
No live network in the module itself — the caller supplies probed `ArmResult`s; tests inject a fake probe.

## §3 — Permitted files (ONLY these; whole-window `git diff --name-only 19c9464..HEAD` ⊆ this set)

1. `SPEC_BRIEF12.md`
2. `src/kronos/validate/controls.py`  (edit: add `"infra"` kind only)
3. `src/kronos/validate/infra_validator.py`  (new)
4. `tests/test_infra_validator.py`  (new)

Base = `origin/main` @ `19c9464`. Never `git add -A`; stage these explicit paths only.
Do NOT edit `schema.py`, `lifecycle.py`, `types.py`, `events.py`, `runner.py`, `candidates.py`,
`manifest.py`, `.github/`, or anything under `cybergym/`. Reuse the existing fixture
`tests/fixtures/infra/cybergym_nmap.xml` READ-ONLY (ingest it to build SERVICE nodes); do not modify it.

## §8 — Acceptance criteria (tests-as-rules; `tests/test_infra_validator.py`)

Decide PASS/FAIL from pytest's summary line, never `$?` (CLAUDE.md §3). Expected values derive from
this brief's prose.

A. **Differential kind=infra** — `run_differential([A_canonical(success=True), B_negative_control(success=False)], kind="infra")`
   → `classification=="live_discriminated"`, `live is True`, `discriminated is True`. Control also
   success → `"indiscriminate_target"`, `live is False`. Canonical fail → `"not_live"`, `live is False`.
B. **Outcome invariant** — `validate_service_reachable` returns a `ValidationOutcome`; a `live` outcome
   has `discriminated is True` and `classification=="live_discriminated"` (constructor invariant holds;
   no path yields `live=True` otherwise).
C. **In-scope only / no out-of-scope traffic** — after ingesting `cybergym_nmap.xml`, the pass probes
   ONLY the in-scope `127.0.0.1` services; the out-of-scope `10.0.0.1:22/tcp` SERVICE is NEVER passed to
   `probe` (assert via a recording fake probe). 
D. **FINDING on live** — for each in-scope reachable SERVICE, a `FINDING` `finding:infra-reachable:<sid>`
   exists, `SERVICE --vulnerable_to--> FINDING` edge exists, FINDING `status=="reachable"`, and derived
   `confidence==7`.
E. **Abstention** — when the differential is `not_live` / `indiscriminate_target` / `inconclusive`, NO
   FINDING node and NO `vulnerable_to` edge is created for that SERVICE.
F. **No secret/sensitive leak** — `outcome.evidence` and `outcome.detail` contain only arm labels,
   success booleans and status codes (no credential, no raw probe payload).
G. **No live network** — the module opens no real socket; the fake `probe` is the only connection point
   (assert, e.g., by monkeypatching `socket.socket` to raise during the pass).
H. **Control is same in-scope host** — the negative-control arm's target host equals the canonical arm's
   host (an in-scope `127.0.0.1`), and only its port differs (a closed control port) — never a different
   or out-of-scope host.
I. **Idempotence** — running the pass twice yields the same FINDINGs/edges, no duplicates (deterministic
   `finding_id` + MERGE).
J. **Scope audit** — `git diff --name-only 19c9464..HEAD` ⊆ §3 (whole window).

Full suite green (`0 failed`) under `.venv`; refresh the total count as the final edit. Reviewer runs
independently against this brief and the diff.

## §9 — Explicitly deferred (NOT in S4.1)
- EVIDENCE-node storage + `evidences` edge (would raise reachable confidence 7→9) — a later increment.
- Extending `CandidateTarget`/`candidates.py` to HOST/SERVICE (SECRET→infra auth) — not this brief.
- Any new `events.py` validate_* kind.
