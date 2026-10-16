# SPEC_BRIEF8.md — Negative-control validation (two-armed proof) — S1

**Status:** build brief (stateless). Start from latest `main` (must contain the Brief #7 merge
`ac1167b` — check `cybergym/ground_truth.yaml` has a `cloud_denial_matrix` key). New branch, open
a PR, **do NOT merge**. Cloud build.
**Autonomy:** Balanced. Proceed on reversible calls. Escalate only the FORKs below
(FORK / OPTIONS / RECOMMENDATION / DEFAULT); every one carries a DEFAULT — if unattended, take it
and record which.
**Role separation (binding):** researcher wrote this; **builder** implements on a branch, opens a
PR, and never merges; **reviewer** reads the diff against §6 before merge.

---

## 0. Why this brief exists, and what Brief #7 just unlocked

This is the first piece of real false-positive-reduction machinery (goal **G3**). Two holes exist
in `src/kronos/validate/` today, both verified in source on `main`:

**Hole 1 — `http_validator.py` treats any 2xx as proof.** It loops header variants and returns
`live=True` on the first `200 <= status < 300`. Nothing checks whether the endpoint would have
said 200 to *anything*. The CyberGym range contains a live demonstration: `cybergym/api/app.py`
exposes `GET /health`, which returns `{"status": "ok"}` with **200, no auth required**. Point
today's validator at `/health` with a garbage secret and it reports the secret as live. That is
not a hypothetical FP; it is reproducible against the running range.

**Hole 2 — `cloud_validator.py` collapses every `ClientError` to `live=False`.** One `except
(ClientError, BotoCoreError)` branch, no inspection of `Error.Code`. It therefore cannot tell
*no-credential* from *wrong-credential* from *valid-credential-denied-this-bucket*.

**The payoff from Brief #7.** On AWS-faithful semantics — which Brief #7 established and verified
live (5/5 rows, X-score 3/3 at `bdec3b4`) — a **signed** request that comes back `AccessDenied`
means the signature *verified* and policy denied the resource. A signed request with a wrong secret
comes back `SignatureDoesNotMatch`; an unknown key comes back `InvalidAccessKeyId`. So
`AccessDenied` to our signed request is positive evidence that **the credential is real**, even
though that bucket is closed to it.

That inference is only safe if the target actually discriminates. A sloppy S3-compatible endpoint
could return `AccessDenied` to everything. **That is precisely what the negative-control arm
settles**, and it is why denial fidelity had to land first: with Brief #7's flattened `AccessDenied`
on every path, this capability was unbuildable.

This brief adds **no new autonomy and no new scope surface.** Both arms hit the same target, so
`scope_guard` is unchanged. It makes existing validation honest, not broader.

---

## 1. Hard guardrails

1. `src/kronos/scope_guard.py` MUST stay a **zero-line diff** (FORK-2 / GitHub #2 stays open).
2. `advance_secret_status` stays the **only** forward status mutator, called only from
   `validate/runner.py`. This brief changes *when* the runner advances a secret, never *how*
   status is written. Do not touch `lifecycle.py`.
3. **No positive claim without its counterfactual.** `ValidationOutcome.live = True` MUST be
   impossible unless the differential ran and discriminated. There must be no code path that sets
   `live=True` from a single arm.
4. **Abstain rather than guess.** Insufficient or contradictory arm evidence → not live, secret
   stays `extracted`, classification recorded. Never "probably live".
5. **Deterministic and replayable.** The negative-control credential is derived deterministically
   (FORK-L), never random, so a run is reproducible and attributable. No LLM anywhere in this
   module.
6. **A negative control must never be a real credential.** The derivation must be structurally
   valid but cryptographically guaranteed not to authenticate, with an invariant test.
7. **Never log a secret value.** Arm evidence records shapes, status codes and error codes — never
   the real secret, and never the derived control in a form that could be mistaken for one.
8. The budget remains fail-closed through `BudgetLedger.charge`; cleanup remains budget-exempt.
   See FORK-J for arm metering.
9. **No FINDING nodes.** An indiscriminate endpoint is a real finding (broken access control), but
   finding creation belongs to a later brief. Record the classification; do not create nodes.

---

## 2. File allowlist

**May change:**
- `src/kronos/validate/controls.py` (new) — the differential engine and control derivation.
- `src/kronos/validate/types.py` — additive fields only (see §3.1).
- `src/kronos/validate/http_validator.py`, `cloud_validator.py` — arm-aware.
- `src/kronos/validate/runner.py` — arm metering, both-arm evidence, abstention.
- `src/kronos/validate/README.md`, `DECISIONS.md`.
- `tests/test_negative_controls.py` (new), plus additive edits to existing validate tests.
- `cybergym/selftest.py` — one new live check (§5.3).

**Must NOT change:** `scope_guard.py`, `lifecycle.py`, `schema.py`, `reconcile/`, `budget/`,
`cleanup/`, `registry.py`, `candidates.py`, `cybergym/cloud/*`, `ground_truth.yaml`, the
Dockerfiles, `docker-compose.yml`, `requirements.txt`. If you believe one is required, **stop and
report**.

---

## 3. Design

### 3.1 `types.py` — additive only

Keep `live: bool` as the single field the runner acts on, so `lifecycle.py` and every existing
caller are untouched. Add:

- `classification: Literal["live_discriminated", "not_live", "authenticated_not_authorized",
  "indiscriminate_target", "self_request_malformed", "inconclusive"]`
- `control_outcome: str` — what the control arm observed (code/status, never a secret).
- `discriminated: bool` — did the arms differ in a way that isolates the credential as the cause?

**Invariant, enforced in code and asserted in a test:** `live is True` implies
`discriminated is True` and `classification == "live_discriminated"`.

### 3.2 `controls.py` — the one chokepoint

Mirror the `scope_guard` / `advance_secret_status` pattern: one module, one entry point, no
per-caller reimplementation.

- `derive_negative_control(real_value, *, target_id, kind) -> str` — deterministic, shape-preserving,
  guaranteed-invalid (FORK-L).
- `run_differential(arms) -> DifferentialResult` — executes the arm set, compares, classifies, and
  returns the combined evidence. **The only place `discriminated` is ever set true.**

### 3.3 HTTP arms

| Arm | Credential sent | Purpose |
|---|---|---|
| A canonical | the real secret | the positive claim |
| B negative control | derived invalid, same shape | does the target discriminate? |

Classification:
- A 2xx, B non-2xx → `live_discriminated`, **live=True**.
- A 2xx, B **also 2xx** → `indiscriminate_target`, live=False. *(This is the `/health` case.)*
- A non-2xx → `not_live`, live=False (B not required; record that it was skipped).
- Both transport-error → `inconclusive`, live=False.

### 3.4 Cloud arms

| Arm | Credential sent | Purpose |
|---|---|---|
| A canonical | real access key + real secret | the positive claim |
| B bad-secret | real access key + derived wrong secret | does the target verify signatures? |
| C unknown-key | derived invalid access key | does the target distinguish unknown keys? |

Read `exc.response["Error"]["Code"]` and `ResponseMetadata.HTTPStatusCode`. Classification:
- A succeeds, B/C denied → `live_discriminated`, **live=True**.
- A succeeds, **B also succeeds** → `indiscriminate_target`, live=False (endpoint is not enforcing
  auth — exactly the free-tier-LocalStack trap `cybergym/README.md` documents).
- A `AccessDenied`, B `SignatureDoesNotMatch`, C `InvalidAccessKeyId` →
  `authenticated_not_authorized`. **The credential is proven real**: advance the secret to
  `validated`, but write **no** `authenticates_to` edge for this resource and do **not** take it to
  `reachable` via this candidate (FORK-M).
- A and B both `AccessDenied` → the target does not discriminate → `inconclusive`, live=False.
- **Any arm returns 400 `AuthorizationHeaderMalformed`** → `self_request_malformed`: *we* broke our
  own request. Surface it loudly (log + classification); never record it as a target signal. This
  is the false-negative guard Brief #7 §3.1a exists to make possible.

### 3.5 Runner integration

- **Charge every arm BEFORE the first arm runs** (FORK-J), so a `BudgetExceeded` can never bisect a
  differential and leave a half-proof.
- Evidence on a positive claim MUST contain **both/all arms** — the differential *is* the proof. A
  single-arm evidence blob is not acceptable for `live=True`.
- `authenticates_to` edge and `_advance_through` only on `live_discriminated` (plus the
  `validated`-only path in §3.4 / FORK-M).
- `ValidationAttempt` gains `classification` and `discriminated` so the run report and X-score
  path can show abstentions distinctly from failures.

---

## 4. FORKs (pre-resolved)

**FORK-I — where the arm logic lives.** (1) one shared `controls.py`; (2) per-validator.
→ **DEFAULT: (1).** Same reasoning as `scope_guard`: a rule duplicated per caller is a rule that
rots per caller.

**FORK-J — budget metering of arms.** (1) charge all arms up front, differential atomic;
(2) charge per arm as it runs.
→ **DEFAULT: (1).** Consistent with Brief #5 FORK-E (finish the atomic action). Option 2 lets a
ceiling land between arms and produce an unprovable half-differential. Validation now costs 2–3×
per candidate; say so in `DECISIONS.md` and keep `validation_attempts` = 1 per *candidate* while
`tool_invocations` counts *arms*.

**FORK-K — control arm also succeeds.** (1) abstain: live=False,
`classification="indiscriminate_target"`, secret stays `extracted`, evidence attached as
`negative_control_failure`, no FINDING; (2) mark the secret dead.
→ **DEFAULT: (1).** The secret is not disproven — the *target* is uninformative. `dead` is sticky
and would destroy a credential that may well be valid elsewhere.

**FORK-L — control derivation.** (1) HMAC-derived, shape-preserving, with a fixed non-secret
`KRONOS-NEGATIVE-CONTROL` domain-separation label; (2) a hardcoded sentinel string.
→ **DEFAULT: (1).** Deterministic, replayable, attributable, and collision-safe against the real
value. Option 2 is trivially fingerprintable by a target that wants to defeat the control. Add an
invariant test: the derived control never equals the real value, is the same shape class, and is
stable across runs.

**FORK-M — cloud `authenticated_not_authorized`.** (1) advance to `validated`, no edge, not
`reachable` via that candidate; (2) treat as `not_live`.
→ **DEFAULT: (1).** It is genuine, differentially-proven evidence that the credential is real;
discarding it is a false *negative*. The distinction is exactly what Brief #7 bought, and it is the
over-privilege signal §0 of Brief #7 named.

---

## 5. Tests

### 5.1 Hermetic — the FP that exists today
1. **`/health`-shaped target (THE headline test):** a stub returning 200 to every request. Assert
   `live is False`, `classification == "indiscriminate_target"`, the secret stays `extracted`, and
   **no `authenticates_to` edge** is written. Assert this same stub makes the *pre-brief* logic
   claim live (keep it as a documented regression anchor).
2. **True positive still passes:** a stub that 200s only the correct credential →
   `live_discriminated`, `live is True`, edge written, secret advances.
3. **Invariant:** no input produces `live=True` with `discriminated=False` — assert over the
   classification matrix, not one case.
4. **Cloud matrix:** parametrize A/B/C over Brief #7's five codes and assert each classification,
   including `self_request_malformed` on 400 `AuthorizationHeaderMalformed`.
5. **`authenticated_not_authorized`:** secret reaches `validated`, gains **no** edge, and is not
   `reachable` via that candidate.
6. **Control derivation:** deterministic across runs, never equal to the real value, shape
   preserved; `derive_negative_control` never returns a value present in the evidence store.
7. **Budget atomicity:** a ledger with room for one arm set but not two stops *between* candidates,
   never mid-differential — assert no candidate has a partial arm record.
8. **Carried from §7.6 review:** (a) add `assert scanned > 0` non-vacuity to the anti-leak guard in
   `cybergym/cloud/test_denial_matrix.py`; (b) add a negative test that a **non-M1** malformed
   `Authorization` header does **not** return 400.

### 5.2 Regression
Full suite stays green: **140 passed / 1 skipped** before this brief's additions; report the new
total. `cybergym/cloud/` stays at 16 plus (b) above.

### 5.3 Live, Docker-backed — required, not optional
Add one check to `cybergym/selftest.py`:

- Call the HTTP validator against the running range's **`/health`** (`127.0.0.1:8091`) with a
  deliberately bogus secret. Assert `classification == "indiscriminate_target"` and `live is False`.
  **This is the live proof that the FP is actually closed on a real target**, not just a stub.
- Re-assert the cloud differential against the live SigV4 proxy produces `live_discriminated` for
  the genuine fixture credential and `indiscriminate_target`/`inconclusive` for none of them.

**X-score must still be 3/3 and exit 0.** If it drops, the differential is rejecting a chain it
should accept — report it as a FAIL with the arm evidence; do **not** loosen a gate to recover the
score.

**Environment:** the live run requires a host with **unproxied egress** (local Kali). In a proxied
cloud container the image build fails at PyPI and the live criteria cannot be met — if that
happens, report **BLOCKED / INCOMPLETE** for §5.3 and do not present hermetic tests as satisfying
it.

---

## 6. Acceptance criteria

1. `scope_guard.py` zero-line diff; `lifecycle.py` untouched.
2. No code path sets `live=True` without `discriminated=True` (test 5.1.3).
3. The `/health` FP is closed, proven **both** hermetically (5.1.1) and live (5.3).
4. True positives unaffected; live **X-score 3/3**, exit 0.
5. Cloud classification matrix matches Brief #7's codes, `self_request_malformed` included.
6. `authenticated_not_authorized` advances to `validated` only, with no edge (FORK-M).
7. Abstention never advances a secret and never writes an edge (FORK-K).
8. Arms charged atomically up front; no partial differential under budget exhaustion (5.1.7).
9. Negative-control derivation deterministic, shape-preserving, provably never a real credential.
10. No secret value in any evidence blob, log line, or `detail` string.
11. Both §7.6 hardening nits landed (5.1.8).
12. Which FORK option taken for I, J, K, L, M — DEFAULT or escalated, with reason.

---

## 7. Output expected back

- Branch + PR link (not merged); diff summary; full test-suite count before/after.
- Guardrail confirmation: `scope_guard.py` zero-line, `lifecycle.py` untouched, allowlist respected.
- FORK choices (I, J, K, L, M).
- The classification matrix as **implemented**, next to Brief #7's declared matrix.
- Live `selftest.py` output including the new `/health` abstention check, and the literal
  `X-SCORE:` line with exit code — or an explicit **BLOCKED / INCOMPLETE** naming the environment.
- A one-line statement of the differential cost multiplier now charged per candidate.
