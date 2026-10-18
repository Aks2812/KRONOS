# KRONOS loop-state checkpoint

seq: 1
derived_at: 2026-10-18T03:41:00Z
repo_path: /home/void/Void-Projects/KRONOS-Artifacts/KRONOS-void
baseline: docs/loop/KRONOS_LOOP_ARCHITECTURE_v6.md
stage: FORK-2

## Re-derived facts (public: SHAs, PR/issue numbers, gate names, test counts, verdicts only)

main:
  head: dcbdba950a45253f2c417b0c95c6ccb6930e9221
  protected: false

pr_13:
  state: open
  draft: true
  merged: false
  head: d2ad51e611927525780b9069db2bc16b0a7209b2
  mergeable_state: clean
  reviews: 0
  check_runs: 0

issue_2:
  state: open

ci: "none; local evidence only"

tests:
  last_run: null

merge_authorization: null

pending_action: null

stale_branches:
  - claude/cybergym-denial-fidelity-brief7
  - claude/ingestion-contract-canonical-keys-brief9
  - claude/negative-control-validation-brief8
  - claude/scope-guard-shape-aware-brief10
  - claude/sweet-gauss-x4l1wi

known_stale_clones:
  - path: /home/void/Void-Projects/KRONOS-Artifacts/KRONOS
    note: >
      root-owned, legitimate but stale clone of the same origin; last commit 492a620,
      53 commits behind main as of this checkpoint. Do not chown, delete, or
      git-operate on it. Recorded here so future discovery does not re-trip on it.

## MERGE-GATE status (10 prerequisites, v6 section 3.1)

1. main protected: FAIL (false)
2. PR #13 not a draft: FAIL (true)
3. PR #13 open and unmerged: pass
4. head SHA equals authorized SHA: n/a (no authorization granted yet)
5. independent review PASS on every SPEC_BRIEF10.3 section 6 criterion: FAIL (not yet run)
5b. GitHub approving review: n/a (single-maintainer repo, see v6 section 2.4)
6. CI green or "ci: none" acknowledged: acknowledged ("ci: none; local evidence only")
7. local test evidence recorded in checkpoint: FAIL (tests.last_run is null)
8. mergeable_state clean, head not already ancestor of main: pass
9. merge_authorization present, granted this turn: FAIL (null)
10. clean tree, stale branches reconciled or recorded: pass (recorded above, none deleted)

Six of ten prerequisites fail. Do not merge.
