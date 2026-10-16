# SPEC_BRIEF8.1.md — Differential fixes + allowlist carve-out (amends PR #10, pre-merge)

**Status:** build brief (stateless). Continue on the SAME branch as PR #10
(`claude/negative-control-validation-brief8`, head `561cf2b965d9b0bf11c89fe8808018e549bb3ad1`) and
push to that PR. Do NOT open a new PR, do NOT merge.
**Autonomy:** Balanced. No FORKs — every decision below is settled.
**Role separation (binding):** researcher wrote this; builder implements on the branch and never
merges; reviewer reads the diff before merge.

---

## 0. Why this brief exists

PR #10 is good work. Reviewer-verified on the real diff: `scope_guard.py` zero-line,
`lifecycle.py` untouched, `cybergym/cloud/*` untouched, the §3.1 invariant enforced structurally in
`ValidationOutcome.__post_init__` on a frozen dataclass, and a 125-combination exhaustive cloud
matrix. The invariant demonstrably *bites* — it is what forced the six mock updates in
`test_budget.py` / `test_reconcile.py`, and those fixes are minimal and weaken no assertion.

Review found **two defects in `run_differential`, both of the same kind: the code claims more than
it checked.** Both are narrow. One can produce a false positive, which is the exact thing Brief #8
exists to prevent. Plus one contradiction in Brief #8 that was mine, which the builder correctly
refused to guess at.

---

## 1. Fix #1 (REQUIRED) — cloud `live_discriminated` must require BOTH controls denied

**Problem.** In `controls.py`, the cloud branch is:

```
if a.success:
    if b.success:
        return indiscriminate_target
    return live_discriminated      # <-- arm C is never consulted
```

Arm `C_unknown_key` is never read when `A_canonical` succeeds. So for
(A = success, B = denied, C = **success**) the function returns `live_discriminated`, `live=True`,
`discriminated=True` — a positive claim made while a control arm succeeded. The `detail` string on
that branch reads *"canonical succeeded, both controls were rejected"*, which in that case is
simply false.

Brief #8 §3.4 specified "A succeeds, **B/C denied** → `live_discriminated`". Guardrail 3 is
stronger still: a positive claim requires the differential to have discriminated. A target that
accepts arbitrary unknown access keys while rejecting a bad secret for a known key is contrived,
but it is precisely the shape this brief forbids.

**Fix.** Require **both** controls to have failed before returning `live_discriminated`. If `A`
succeeds and *either* control also succeeds, the target is not discriminating →
`indiscriminate_target`, `live=False`. Make the `detail` string state what was actually observed.

**Acceptance:** a test asserting (A success, B denied, C success) → `indiscriminate_target`,
`live=False`. Assert on the classification, not only the invariant.

---

## 2. Fix #2 (REQUIRED, lower severity) — cloud both-transport-error must be `inconclusive`

**Problem.** The HTTP branch handles unreachability explicitly:

```
if a.transport_error and b.transport_error: -> "inconclusive"
```

The cloud branch has no equivalent. A cloud arm with `transport_error=True` has `success=False`
and `error_code=None`, so it falls through every `AccessDenied` check to the terminal
`return not_live` with detail *"canonical arm did not succeed"*. An unreachable endpoint is then
recorded as a statement about the **credential** ("not live") when nothing about the credential was
learned. That is a false negative dressed as a finding, and it violates guardrail 4 (abstain rather
than guess).

**Fix.** Add the cloud equivalent: if `A_canonical` and `B_bad_secret` both report
`transport_error`, return `inconclusive`, `live=False`, `discriminated=False`, with a detail saying
the target was unreachable.

**Acceptance:** a test for the cloud both-transport-error case → `inconclusive`. Note that
`_all_cloud_arm_combinations()` never sets `transport_error`, so this case is currently **untested
entirely** — the new test must construct it directly.

---

## 3. Fix #3 (REQUIRED) — the matrix test must assert classifications, not just the invariant

**Problem.** `test_cloud_invariant_live_implies_discriminated_over_every_combination` walks all 125
combinations but asserts only `not (live and not discriminated)` and that a live result is labelled
`live_discriminated`. Fix #1's bad cell **passes that test**: it returns `live=True` *with*
`discriminated=True`, so the invariant holds while the classification is wrong. An exhaustive test
that cannot fail on a wrong answer is a coverage illusion.

**Fix.** Keep the invariant assertion, and add an **expected-classification table**: for each
`(a_code, b_code, c_code)` triple, the classification `run_differential` must return. Derive the
expectations from Brief #8 §3.4 plus Fixes #1–#2 — write them out as data, do **not** compute them
by re-implementing the function under test (a test that mirrors the implementation proves nothing).
A full 125-row table is acceptable and preferred; a documented rule-based table is acceptable only
if each rule is stated independently of `controls.py`'s code.

**Acceptance:** deliberately inverting Fix #1 in a scratch copy must make this test **fail**. State
in the report that you checked this, and that the check was reverted.

---

## 4. Fix #4 (REQUIRED) — allowlist carve-out for the §7.6 hardening nits

**My error, not yours.** Brief #8 §5.1.8 instructed editing
`cybergym/cloud/test_denial_matrix.py` while §2's must-not-change list covered `cybergym/cloud/*`.
Stopping and reporting was the correct call.

**Resolution — §2 is hereby amended for this brief:** `cybergym/cloud/test_denial_matrix.py` is
**authorized**. It is a test file about the range, not range behaviour; nothing it does affects the
proxy, the images, or Brief #7's verified matrix. Everything else under `cybergym/cloud/` stays
forbidden — in particular `sigv4_proxy.py`, `sigv4_verify.py` and `known_secrets.py` must keep a
zero-line diff.

Implement both nits from the §7.6 review:
- **(a)** Add a non-vacuity assertion to
  `test_src_kronos_never_references_the_fixture_only_discriminator_header`: count the files the
  guard scans and `assert scanned > 0`. Today it would pass trivially if the path ever stopped
  resolving. (Reviewer measured it currently scans 21 files.)
- **(b)** Add a negative test that a **non-M1** malformed `Authorization` header does **not**
  return 400 `AuthorizationHeaderMalformed` — proving §3.1a's scope claim is enforced and
  protecting against a future widening of `_CASE_M1_RE`.

---

## 5. Unchanged guardrails (still binding)

1. `src/kronos/scope_guard.py` zero-line diff. `lifecycle.py` untouched.
2. `cybergym/cloud/sigv4_proxy.py`, `sigv4_verify.py`, `known_secrets.py`, `ground_truth.yaml`,
   the Dockerfiles, `docker-compose.yml` and `requirements.txt` all zero-line diff.
3. The §3.1 structural invariant stays enforced in `__post_init__` — do not relax it to make a
   test pass.
4. No secret value in any evidence blob, log line or `detail` string.
5. No FINDING nodes.
6. Do not weaken or delete any existing test to accommodate these fixes.

---

## 6. Tests

- The three new/strengthened tests from §1, §2, §3.
- The two nits from §4.
- Full suite stays green. Baseline for this branch is **306 passed / 1 skipped** in `tests/` and
  **16 passed** in `cybergym/cloud/`; report the new totals. The `cybergym/cloud/` count must rise
  by at least one (nit (b)).
- The §5.3 live checks from Brief #8 remain **BLOCKED / INCOMPLETE** in a proxied cloud container
  and are **not** this brief's responsibility to satisfy. Do not attempt a Dockerfile workaround.
  Leave `check_negative_control_differential` wired as PR #10 left it.

---

## 7. Output expected back

- Same branch / same PR (#10) updated; diff summary; full test-suite counts before/after.
- Guardrail confirmation: `scope_guard.py` and `lifecycle.py` zero-line; everything under
  `cybergym/cloud/` except `test_denial_matrix.py` zero-line.
- For Fix #1 and #2: the new classification each case now returns, and the corrected `detail`
  strings.
- For Fix #3: confirmation that inverting Fix #1 makes the table test fail, and that the inversion
  was reverted.
- For Fix #4: the non-vacuity count the guard now asserts, and the non-M1 header case used.
