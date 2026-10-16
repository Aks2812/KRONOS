# SPEC_BRIEF7.1.md — Declare the test dependency (amends PR #9, pre-merge)

**Status:** build brief (stateless). Continue on the SAME branch as PR #9
(`claude/cybergym-denial-fidelity-brief7`, head `d6dc3264f3de4c63c4063e437b75491c8aadf60c`) and
push to that PR. Do NOT open a new PR, do NOT merge.
**Autonomy:** Balanced. No FORKs. Nothing here requires a judgement call.
**Role separation (unchanged, binding):** researcher writes; builder implements on the branch and
never merges; reviewer reads the diff before merge.

---

## 0. Why this brief exists

PR #9 passed all ten §5 acceptance criteria, including the live Kali verification
(5/5 denial rows, 13/13 selftest checks, X-score 3/3 exit 0). One defect remains, and it was
introduced by this PR:

- `git grep "TestClient" 7d2df97 -- cybergym/` returns **nothing**. PR #9's
  `cybergym/cloud/test_denial_matrix.py` is the first `TestClient` user under `cybergym/`.
- `starlette.testclient` requires **`httpx2`**, which is declared in **no** requirements file
  and no `pyproject.toml` on the branch.
- Consequence: on a clean checkout following only `cybergym/requirements.txt`, pytest **cannot
  collect** `test_denial_matrix.py` — it fails with
  `RuntimeError: starlette.testclient requires httpx2`. The 16 passing tests are real, but they
  are not reproducible from a clean environment.

The cloud builder could not have fixed this inside Brief #7: `cybergym/requirements.txt` is
outside §7 §2's allowlist, so the correct move there was to stop and report. It did not notice
only because its venv already carried the package. This brief supplies the missing authorization.

**Exact pin, observed on the Kali verification run:** `httpx2==2.13.1`.

---

## 1. Scope — deliberately one line

**ALLOWLIST (this brief only, superseding §7 §2 for this file):**

- `cybergym/requirements.txt` — add the `httpx2` pin.

Optionally, and only if it falls out cleanly: `cybergym/README.md`, if it documents the install
steps and would now be wrong.

**Everything else is out of scope**, explicitly including:

1. **`src/kronos/` MUST stay a zero-line diff.** Unchanged from Brief #7. Stop and report if you
   believe otherwise.
2. No change to `sigv4_proxy.py`, `sigv4_verify.py`, `ground_truth.yaml`, `selftest.py`, or
   `test_denial_matrix.py`. The matrix is verified; do not touch it.
3. No Dockerfile or `docker-compose.yml` change. The range builds correctly on an unproxied host;
   the earlier TLS failures were a wrong-environment artifact, **not** a range defect. Do not
   "fix" them.
4. No dependency upgrades, no unrelated pins, no lockfile introduction, no `pyproject.toml` edit.

---

## 2. What to do

1. Confirm the branch head is `d6dc3264f3de4c63c4063e437b75491c8aadf60c`. If it is not, stop and
   report — someone has pushed since review.
2. Determine the authoritative requirement. Read the installed `starlette` version and confirm
   which package its `TestClient` imports. Pin **what that starlette actually requires**:
   `httpx2==2.13.1` is the verified value, but if the installed starlette demands something else,
   report the discrepancy rather than pinning a value that contradicts the code.
3. Add the pin to `cybergym/requirements.txt`, matching the file's existing pin style
   (`package==version`, as `fastapi==0.143.0` is written).
4. Prove the fix from a genuinely clean environment (below).
5. Commit to the same branch, push to PR #9. Do not merge.

---

## 3. Acceptance test — clean-environment collection

This is the whole point of the brief, so prove it rather than asserting it:

1. Create a **fresh** venv that has never had `httpx2` installed.
2. Install **only** from the declared files: the repo root requirements and
   `cybergym/requirements.txt`. Install nothing by hand.
3. `PYTHONPATH=. <venv>/bin/pytest cybergym/cloud/` must **collect and pass 16 tests** with no
   manual intervention. Paste the collection line and the summary line.
4. `PYTHONPATH=. <venv>/bin/pytest` must still report **140 passed, 1 skipped**.

A run in a venv that already had the package proves nothing — it is the exact blind spot that let
this defect through. If you cannot build a clean venv, say so and report the step as INCOMPLETE
rather than reusing an existing one.

The live Docker run is **not** repeated for this brief; §5.5/§5.6 are already satisfied at this
branch head by the Kali verification, and a one-line dependency pin cannot invalidate them.

---

## 4. Output expected back

- Same branch / same PR (#9) updated; one-line diff shown in full.
- The starlette version and the package its `TestClient` requires, confirming the pin.
- Clean-venv proof: the pytest collection + summary lines for `cybergym/cloud/` (16 passed) and
  for `tests/` (140 passed, 1 skipped), plus a statement that the venv was fresh.
- Confirmation `git diff --stat 7d2df97 HEAD -- src/kronos/` is still empty.
- Confirmation that no file outside §1's allowlist was touched.
