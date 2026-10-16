# SPEC_BRIEF7.md — CyberGym denial fidelity (prerequisite for negative-control validation)

**Status:** build brief (stateless). Start from latest `main` (must contain `src/kronos/cleanup/`
from PR #8). New branch, open a PR, **do NOT merge**. Cloud build.
**Autonomy:** Balanced. Proceed on reversible calls. Escalate only the FORK below
(FORK / OPTIONS / RECOMMENDATION / DEFAULT); it carries a DEFAULT — if unattended, take it and record it.
**Role separation (unchanged, binding):** this brief was written by the **researcher**; the
**builder** implements it on a branch and opens a PR and never merges; the **reviewer** reads the
diff against §5 before merge. Do not self-merge, and do not widen scope beyond §2.

---

## 0. Why this brief exists, and why it is first

The next FP-critical work is negative-control validation (two-armed proof) in `src/kronos/validate/`.
That brief cannot be written correctly yet, because the range it would be measured against cannot
tell its own denial reasons apart.

**Verified empirically (2026-10-15, research session).** The real `cybergym/cloud/sigv4_proxy.py` was
run against a stub upstream and driven with boto3 across six arms. Result: the two authorized arms
returned HTTP 200, and **all four denial arms returned identical HTTP 403 with identical S3
`Error.Code` = `AccessDenied`**, differing only in free-text `Message`:

| Arm | Observed |
|---|---|
| valid general key → general bucket | 200 |
| valid admin key → admin bucket (over-privilege) | 200 |
| unauthenticated (UNSIGNED) | 403 `AccessDenied` — "Missing or malformed AWS SigV4 Authorization header" |
| unknown access key | 403 `AccessDenied` — "Unknown access key" |
| known key, wrong secret | 403 `AccessDenied` — "SignatureDoesNotMatch" |
| valid key, disallowed bucket | 403 `AccessDenied` — "…is not authorized to access…" |

Two consequences, both blocking:

1. **`src/kronos/validate/cloud_validator.py` collapses every `ClientError` to `live=False`**, so it
   cannot distinguish *no-auth-required* from *wrong-credential* from *valid-credential-but-not-
   authorized*. The third is the **over-privilege signal**. Chain 3 currently passes only because the
   *positive* arms differ (admin succeeds where general fails) — not because any code reads the
   denial reason.
2. **Real AWS S3 returns distinct codes** for these conditions. The proxy flattens them, so a
   validator tuned against this range would not transfer to a real target. Fixing the validator
   before fixing the range would bake in prose-matching against fixture text — the worst outcome for
   G3, because it would pass the benchmark and fail in production.

This brief fixes **only the range**. It changes no KRONOS behaviour.

---

## 1. Hard guardrails

1. **`src/kronos/` MUST have a zero-line diff.** This is a fixture-only brief. If you believe a
   change under `src/kronos/` is required, **stop and report** — do not make it.
2. Therefore untouched by construction: `scope_guard.py` (FORK-2 / GitHub #2 stays open),
   `lifecycle.py`, `validate/`, `reconcile/`, `budget/`, `cleanup/`, `schema.py`.
3. **`known_secrets.py` authorization semantics do not change** — same keys, same secrets, same
   `allowed_buckets`. Only the *representation of a denial* changes.
4. **Authorized requests must behave identically**: still forwarded to upstream, still returning the
   upstream status and body. This brief must not alter the success path.
5. **No new runtime dependencies, no new network egress, no new exposed ports.** The range stays
   localhost-only per SPEC_BRIEF05's posture.
6. **Do not weaken or re-tune anything to make the X-score pass.** The live run must still earn
   **3/3** on its own.

---

## 2. Scope — exactly what changes

Only these files may change:

- `cybergym/cloud/sigv4_proxy.py` — denial response construction
- `cybergym/cloud/sigv4_verify.py` — only if splitting "absent" from "malformed" requires it (§3.1)
- `cybergym/ground_truth.yaml` — add the expected denial matrix
- `cybergym/selftest.py` — extend the existing consistency assertion
- `cybergym/cloud/test_sigv4_verify.py` and/or a new `cybergym/cloud/test_denial_matrix.py` — tests
- `cybergym/README.md`, `DECISIONS.md` — document the change and its rationale

Anything else is out of scope.

---

## 3. Design

### 3.1 Emit AWS-faithful S3 error codes

Replace the flattened `AccessDenied`-for-everything behaviour with the codes real AWS S3 returns.
Target matrix:

| Condition | HTTP | S3 `Error.Code` | Notes |
|---|---|---|---|
| **No `Authorization` header at all** | 403 | `AccessDenied` | matches real AWS for anonymous access to a private resource |
| **`Authorization` header present but unparseable** | 400 | `AuthorizationHeaderMalformed` | real AWS distinguishes a malformed header from an absent one; the current proxy conflates them |
| **Well-formed header, unknown access key** | 403 | `InvalidAccessKeyId` | |
| **Known access key, signature mismatch** | 403 | `SignatureDoesNotMatch` | the cryptographic arm |
| **Valid signature, bucket not in `allowed_buckets`** | 403 | `AccessDenied` | authorization failure — the over-privilege discriminator |
| **Authorized** | upstream status | — | unchanged, forwarded |

`Message` text may remain human-readable and is **not** part of any contract — no test and no future
validator may match on it.

**Deliberate, documented ambiguity:** *no-auth* and *bucket-not-allowed* both yield 403
`AccessDenied`. **This is correct and must not be "fixed."** It is faithful to real AWS, and it is
harmless because a validator always knows which arm it sent — the arm identity disambiguates. Record
this in `cybergym/README.md` so a later reader does not treat it as a bug.

#### 3.1a The one malformed-header case under contract

The `400 AuthorizationHeaderMalformed` row covers **exactly one specified case**, and the test
asserts only that case:

> **Case M1 — correct algorithm token, missing required SigV4 components.**
> `Authorization: AWS4-HMAC-SHA256 Credential=CYBERGYMGENERALUSER0001/20260101/us-east-1/s3/aws4_request`
> — i.e. the `AWS4-HMAC-SHA256` algorithm token and a `Credential=` component are present, but the
> required `SignedHeaders=` and `Signature=` components are absent.
> **Expected: HTTP 400, `Error.Code` = `AuthorizationHeaderMalformed`.**

**Scope of the claim — read this before generalising.** This brief specifies the behaviour of **M1
only**. It does **not** assert that every malformed or unexpected `Authorization` header maps to
`400 AuthorizationHeaderMalformed`, and no test may imply that. Other shapes are deliberately
**unspecified** here and may legitimately map elsewhere — for example a header carrying a
*different* auth scheme entirely (a `Basic` credential, say) is arguably not a SigV4 request at all
and could reasonably be treated like the absent-header case (403 `AccessDenied`). Real AWS behaviour
also varies across these shapes.

Consequences for the builder:

- Implement and test **M1**. Do not add speculative handling for other malformed shapes.
- If, while implementing, you find that the existing parser already routes some other shape to a
  *different* outcome, that is acceptable and out of scope — **report it, do not change it**.
- Document in `cybergym/README.md` that M1 is the only malformed case under contract, so a later
  reader does not mistake the single test for a general rule.

### 3.2 FORK-H — a machine-readable fixture-only discriminator header?

- **OPTIONS:** (1) **AWS-faithful codes only; no custom header.** (2) Additionally emit
  `x-cybergym-deny-reason: malformed_auth|unknown_key|signature_mismatch|bucket_not_allowed`.
- **RECOMMENDATION / DEFAULT: option 1 — no custom header.**

  *Rationale:* the entire point of this brief is that the range must produce signals that
  **transfer to a real target**. A non-AWS header is a signal that exists only here, and the lazy
  implementation path for the next brief would be to read it — producing a validator that passes the
  benchmark and fails in production. The gap found empirically was *flattened codes*; fixing the
  codes closes it. The range's own self-tests do not need the header either, because each test knows
  which arm it sent.

  *If the builder finds a concrete case where a self-test genuinely cannot assert without it:* make
  it **opt-in via an env var, default OFF**, document it as debug-only, and say so explicitly in the
  PR — and §5.4's anti-leak test still applies unconditionally.

### 3.3 Ground truth carries the expected matrix

Add the §3.1 matrix to `cybergym/ground_truth.yaml` as data, and extend `cybergym/selftest.py`'s
existing consistency assertion (the one that already prevents `ground_truth.yaml` and
`known_secrets.py` drifting apart) so the declared matrix and the proxy's actual behaviour cannot
diverge silently.

### 3.4 Make the matrix test hermetic

The research-session verification ran the proxy against a **stub upstream** rather than LocalStack,
because the classification decision happens entirely *before* the proxy forwards. Adopt that as the
committed test design: exercise the denial matrix against the proxy app directly (FastAPI
`TestClient`, or an equivalent in-process harness) with a stubbed upstream, so the matrix tests are
**fast, hermetic, and runnable without Docker or network**. The full docker-backed run stays as the
integration check (§5.5), not as the matrix test's prerequisite.

---

## 4. Tests required

**Unit — header parsing (§3.1):**

1. absent `Authorization` header and malformed `Authorization` header now take **different** paths
   and produce different outcomes (previously identical).
2. a well-formed header still parses to the same `ParsedAuth` fields as before (no regression).

**Unit — denial matrix (the core deliverable), hermetic per §3.4:** one test per row of §3.1,
asserting the exact `(HTTP status, Error.Code)` pair. Six tests. Each must assert on the **code**,
never on `Message`.

**Unit — success path unchanged:** an authorized request is forwarded and returns the upstream
status and body.

**Determinism:** the same arm repeated yields the same `(status, code)`.

**Guard — anti-leak (mechanical, mirroring the budget-exemption grep test):** assert that **no file
under `src/kronos/` references** `x-cybergym-deny-reason` (or whatever header name, if FORK-H's
fallback was taken). This test must exist and pass even under FORK-H option 1, so the guard is in
place before the next brief is written.

**Self-test — ground-truth consistency (§3.3):** declared matrix matches observed behaviour.

**Integration — live range (COMPLETION REQUIREMENT, not optional):** the full **docker-backed**
CyberGym run must be executed and must still earn **X-score 3/3**, and the denial matrix must be
exercised against the **running range** — not only the hermetic harness — confirming the stub
harness and the real stack agree.

> **The hermetic tests do not satisfy this criterion and may never be reported as doing so.** They
> test the classification decision in isolation; only the live run proves the real stack agrees.
>
> **If the live run cannot be executed** — no Docker daemon, image registry unreachable, build
> failure, or any other blocker — the correct outcome is an **explicit `BLOCKED / INCOMPLETE`
> report**, not a pass. Name the blocker, the exact command, and its error output; state plainly
> that the live-run and X-score criteria are **unverified**; and leave the PR open and marked
> incomplete. Do **not** substitute the hermetic result, do not describe the brief as satisfied, and
> do not relax or reinterpret the criterion. A truthful blocked report is a successful outcome for
> this task; an overstated pass is a failure.

Keep all existing tests green (140 passed / 1 pre-existing skip on `main` before this brief).

---

## 5. Acceptance criteria

The PR is acceptable only if **all** of these hold:

1. **§3.1 matrix implemented exactly**, including the 400 `AuthorizationHeaderMalformed` split
   (scoped to **case M1 only**, §3.1a) and the deliberate `AccessDenied` ambiguity documented rather
   than removed. No test asserts or implies a general malformed-header rule.
2. **`src/kronos/` zero-line diff** — state this explicitly in the PR report; the reviewer verifies
   it on the diff.
3. **Authorized-path behaviour unchanged**, with a test proving it.
4. **Anti-leak guard test present and passing**, regardless of which FORK-H option was taken.
5. **Live docker-backed CyberGym run executed and earning X-score 3/3**, reported with the run
   output — **or** an explicit `BLOCKED / INCOMPLETE` report per §4 naming the blocker, the command
   and its error, and stating that this criterion is unverified. Hermetic tests alone never satisfy
   this criterion. These are the only two acceptable outcomes; a pass claimed without the live run
   is a failed brief.
6. **Ground truth and behaviour cannot drift** — the self-test assertion covers the new matrix.
7. **Hermetic matrix tests** run without Docker or network.
8. Full suite green; new test count stated.
9. FORK-H option taken is named, with reasoning if it was not the DEFAULT.
10. `cybergym/README.md` documents the new matrix and the intentional ambiguity;
    `DECISIONS.md` records the fidelity rationale (code-based, transferable; prose is not a contract).

---

## 6. Output expected back (for the reviewer)

- Branch + PR link (not merged); diff summary; full test-suite count before and after.
- Explicit confirmation of **`src/kronos/` zero-line diff**.
- The implemented matrix as a table, so it can be compared against §3.1 line by line.
- Which FORK-H option was taken, and why if not the DEFAULT.
- Confirmation the anti-leak guard test exists and passes, and the exact assertion it makes.
- Live run output showing **X-score 3/3** — or, if it could not be run, a clearly-labelled
  `BLOCKED / INCOMPLETE` section with the blocker, the exact command, its error output, and an
  explicit statement that the live-run and X-score criteria are unverified. Do not present hermetic
  results in its place.
- Confirmation that the malformed-header work covers **case M1 only** (§3.1a), and that nothing
  asserts a general malformed-header rule.
- Confirmation that no test asserts on `Message` text.
- Anything you had to change outside §2's file list (which should be nothing — if there is
  something, that is a FORK, not a silent edit).

---

## 7. Notes

- **Not blocked by the unassessed Cairn features.** The 2026-10-16 customized-Cairn archive was
  byte-identical to the 2026-10-15 one, so the team's newer work remains unassessed; nothing in this
  brief depends on it.
- **This brief unblocks, and does not include, the negative-control validator.** That is the next
  brief (stage S1) and will change `src/kronos/validate/`. Do not start it here.
- **Why fixture-before-validator:** fixing the validator first would encode prose-matching against
  fixture text. The ordering is the point of this brief.
