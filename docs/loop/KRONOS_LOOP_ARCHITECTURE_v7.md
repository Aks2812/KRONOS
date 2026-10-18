# KRONOS_LOOP_ARCHITECTURE.md — v7

**Status:** adopted 2026-10-18 at the maintainer's direction. Supersedes **v6's role model only**.
Everything v6 says about merge authorization, the ten-item MERGE-GATE, pauses, halts and state is
**unchanged and still binding** — v7 replaces who does what, not what may be merged.

**Why v7 exists:** token economics. v6's loop spent ~1.21M subagent tokens on one brief
(builder 379k + reviewer 241k + builder 124k + builder 203k + reviewer 266k), with research run
inline on the orchestrator. v7 moves research off the expensive model, stops re-inlining
instructions, and puts a cheap gate in front of the expensive one.

---

## 1. The five steps

| Step | Model | Job | Terminates? |
|---|---|---|---|
| 1 | **Opus** (orchestrator, init) | Parse the task, write a lean `todo.md`, set up the workspace | no — owns the loop |
| 2 | **Sonnet** (researcher) | Explore files, dump **strict cited facts** into `context.txt` | **yes** |
| 3 | **Sonnet** (builder) | Consume `todo.md` + `context.txt`, make precise edits | **yes** |
| 4 | **Haiku** (test runner, Gate 1) | Run suite, linters, compilers. Emit pass/fail + error logs | **yes** |
| 5 | **Opus** (orchestrator, final review + Gate 2) | Read the clean diff, semantic review, verify `todo.md` compliance, request human approval | no |

Zero context carries between steps 2, 3 and 4. Handoff is **files on disk**, not conversation.

## 2. Short-circuit logic

```
step 3 (Sonnet builder)
   -> step 4 (Haiku gate)
        FAIL -> back to step 3, fed Haiku's raw error logs. Opus is NOT touched.
                circuit breaker: max 3 attempts, then HALT and escalate to the maintainer.
        PASS -> step 5 (Opus final gate)
```

**The expensive model never reads raw terminal errors.** That is the point of step 4.

Circuit breaker interacts with v6's existing iteration bounds (RESEARCH 3 / BUILD 3 / REVIEW 2):
the 3-attempt Haiku↔builder cycle **is** the BUILD bound. Exhausting it is a PAUSE-DECISION, not
a retry.

## 3. File contracts

### `todo.md` — written by step 1, read by step 3
Lean. The approved brief is the specification and is **not** copied into it. It carries: the brief
path and its sha256; the §3 permitted-file list verbatim; the §8 criteria this iteration must
satisfy; what is already done and must not be re-opened; the forbidden paths; and the commit and
push protocol. Nothing else.

### `context.txt` — written by step 2, read by step 3
**Cited facts only.** Every line is `path:line` plus the quoted text. **No conclusions, no
recommendations, no summaries of intent.**

> **This constraint is load-bearing.** The orchestrator inheriting a derivation without its
> evidence is exactly how the §0.3 method defect propagates in this project. Two orchestrator
> derivations were overturned on 2026-10-18 (PD-2's premise, FORK-AB's `HOST` row) and both were
> caught by returning to the evidence, never by re-reading a summary. A researcher that writes
> conclusions has silently become a decision-maker with no gate in front of it.

### `gate1.json` — written by step 4, read by step 3 (on FAIL) or step 1 (on PASS)
`{"verdict": "PASS"|"FAIL", "suite": "<SUMMARY line>", "failures": [...], "attempt": n}`
On PASS the payload stays small. On FAIL the raw logs go to the **builder**, not the orchestrator.

## 4. What v7 removes, and what must replace it

v7 **removes the separate Opus reviewer**: step 5 is the orchestrator reviewing its own loop's
output. Recorded plainly, because the evidence against it is in this repo's own history:

- On 10.4 the orchestrator declared §8 **15 of 15**; the independent reviewer found **3 failures**.
- On 10.5 the orchestrator declared §8 **15 of 15**; the independent reviewer found **4 failures**,
  including `docs/loop/PROGRESS.md` — an out-of-§3 file the **orchestrator itself** had committed
  via `git add -A`.
- At `7fc1863` the suite was green (3456 passed, 0 failed) and the review still returned FAIL. A
  pass/fail gate cannot replace semantic review; it can only run **in front of** one.

A self-review cannot catch the orchestrator's own breach, because the orchestrator already
believes it is fine. **Therefore independence is replaced by ENFORCEMENT, not by diligence.** The
following are mandatory under v7:

1. **Every review finding becomes a test.** When a defect is found by reading, the fix includes a
   test that fails if it recurs. Precedent: `NODE_TYPE_SHAPE_EVIDENCE` +
   `test_b105_8_2_every_row_records_a_citation_and_a_rule_number`, which caught the
   orchestrator's own incomplete citation within a minute of being written.
2. **Full-window file audit as a hard gate.** Step 5 runs
   `git diff --name-only <brief-base>..HEAD` and asserts every path is in §3 — not just the paths
   it expected to change. This is the check that would have caught §8.11.
3. **Explicit-path staging.** Never `git add -A` on a brief-scoped branch. §8.11 was caused by
   exactly that, sweeping up an untracked directory belonging to another branch.
4. **Totals refreshed last.** A total measured before the final test lands is always wrong. It
   went stale three times on one brief. Refresh as the final edit, after the last suite run.
5. **Claims must be enforced or softened.** A document asserting a criterion is met, where the
   shipped file contradicts it, is worse than silence. Either a test proves it or the prose is
   weakened to what ships.
6. **The maintainer is the remaining independent check.** GATE-2 is no longer a second opinion on
   top of an independent review; it **is** the independent review. Step 5 must therefore hand up
   measured evidence, not conclusions — verbatim counts, verbatim lines, file:line citations — so
   approval rests on data rather than on the orchestrator's summary of itself.

**Escape hatch, retained:** the orchestrator may request a one-off independent Opus review when it
has materially changed code it is about to review, or when a brief's central deliverable is a
judgment rather than a behaviour. Requesting it is never a failure.

## 5. Unchanged from v6 — all still binding

Write-ahead checkpointing to `kronos/loop-state` before every consequential action. **§8 is
acceptance criteria, §6 is the live-use gate; never conflated, section number named in every
dispatch.** Expected values derive from brief PROSE, never from observed behaviour; prose silence
is a PAUSE-DECISION. Excluded-first default-deny. CyberGym only, no live targets. Never edit
`manifest.py`, `.claude/`, `.github/` or `cybergym/`. The ten-item MERGE-GATE, re-measured in the
same turn as any merge proposal. Usage limit means stop, not switch models.

## 6. Token notes, measured not projected

- `rtk test` vs raw pytest: **45 bytes vs 3953** — 98.9% less. Already adopted; it means step 4's
  "shield Opus from terminal output" is partly achieved before Haiku is involved. **Caveat:
  `rtk test` returns exit 0 on failure — read the SUMMARY line, never `$?`.**
- Headroom compression measured **0.7% average**, $0.23 on a 43-request session. Its larger
  reported figure is prompt-cache saving, not compression. Not a lever.
- The orchestrator's prior claim that step 5 saves "up to 40%" by eliminating a redundant Opus
  initialization is **not supported**: the reviewer's 266k was spent measuring (two suite runs, a
  12,168-cell differential harness, an in-memory matcher break), not initializing. Moving that
  work to the orchestrator moves its cost, it does not remove it. Realistic saving from merging
  steps: **one agent spin-up plus duplicated suite runs**. The large, certain saving is the Haiku
  short-circuit, which avoids a ~266k review whenever the suite is red.
