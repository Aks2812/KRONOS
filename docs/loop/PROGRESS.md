# KRONOS loop-state checkpoint

seq: 259
derived_at: 2026-11-04T11:50:00Z
stage: R&D-RAILS REPAIR — BUILT + REVIEWED, GATE-2 HOLD (operator decision required; NOT merged). Branch claude/rails-repair c878b685, draft PR #44. kronos-reviewer (Haiku) PASS R1-R8; but two findings, both confirmed by orchestrator Gate-2: F1 HIGH — brief-scope.sh:68 gh-api method filter only detects -X/--method, defaults GET, so `gh api .../pulls/* -f ...` (gh POSTs on -f/-F/--input) and glued -XPOST slip past; the generalized allow (pulls/* *, issues/* *) widened this from one PR to any PR/issue = write bypass of the ask tier (regression introduced by this repair). F2 MEDIUM — RAILS.md:79 still lists the narrowed allow as pulls/13/issues/2, contradicting the shipped wildcards. Recommend remediation before merge: (A) remove pulls/* *, pulls/*/reviews *, issues/* * from settings.json allow so they fall to the ask tier (removes fail-open; honors "no hardcoded PR/issue" better than wildcarding); (B) fix brief-scope.sh to classify -f/-F/--field/--raw-field/--input and glued -XPOST as non-GET -> deny; (C) correct RAILS.md prose. S8 §6 live-run still PAUSED (SEQ 140). Do NOT merge rails PR, do NOT reset local main, do NOT touch 3c712d4.
seq250_merge_authorization:
  pr: 43
  head: 122bca63962084846625824a1cca35db12de5d5a
  authorized_by: "operator, 2026-11-04"
  method: "gh pr ready 43 + gh pr merge 43 --squash --match-head-commit 122bca6 (no --admin, no --auto)"
seq249_pending_action_outcome: >
  RESOLVED — PR #43 MERGED as squash commit 445dbfc at 2026-11-04T08:14:07Z. Head stayed 122bca6
  through merge (--match-head-commit enforced). main advanced 329194c -> 445dbfc. Guard + brief
  confirmed on main. No gate turned red.
seq251_pending_action_outcome: >
  RESOLVED — builder (Sonnet 5.5) pushed c878b685 (9 files, 544 ins), draft PR #44 opened; reviewer
  (Haiku) returned PASS R1-R8 with F1 HIGH + F2 MEDIUM; orchestrator Gate-2 confirmed both. Build and
  review complete; merge HELD pending operator decision on remediation A/B/C.
seq252_pending_action_outcome: "RESOLVED — operator authorized remediation A+B+C on PR #44 (2026-11-04)."
seq253_pending_action_outcome: >
  A+B+C PUSHED as 9ed5b9c on claude/rails-repair (4 files: settings.json -3 removed the three PR/issue
  write allows; brief-scope.sh +132 hardened method filter, fail-closed; RAILS.md corrected;
  tests/test_brief_scope_hook.py new, 27 passed = 22 deny / 5 allow). BUT full suite = 1 failed, 3992
  passed, 1 skipped: tests/test_commit_authority.py::test_B31_Q_scope_audit. The seal-tax scope audit
  asserts names(329194c..HEAD) <= B36_SECTION_10; the rails-repair legitimately adds .claude/*, scripts/,
  .gitignore which are outside B36_SECTION_10. Pre-existing seal-tax design (fails on clean c878b685 too),
  NOT an A/B/C regression. A/B/C themselves verified sound.
seq254_pending_action_outcome: "RESOLVED — operator authorized adding tests/test_commit_authority.py to the rails-repair allowlist for scope-seal changes only (2026-11-04)."
seq255_pending_action_outcome: >
  Seal fix pushed cb10cb4 (tests/test_commit_authority.py only); full suite 3993 passed/1 skipped/0 failed.
  Haiku 5.5 re-review of full rails-repair: VERDICT FAIL. R1-R4,R6-R10 PASS; R5 FAIL on F1 HIGH.
  F1 (CONFIRMED by Opus probe): brief-scope.sh:152 matches only bare token "gh"; argv0 `/usr/bin/gh api ... -f`
  and `$G=gh; $G api ... -f` are not analyzed -> scan returns None -> prints GET -> no deny. Hook fail-closed
  claim broken. (Hook is supplemental per RAILS.md; settings-A removed pulls/issues allows so those calls
  prompt anyway, but the asserted guarantee is false.) F2 LOW: RAILS.md says PR/issue calls fall to "ask tier"
  but there is no gh-api ask rule; they fall to default-mode prompting. Suite green; not an A/B/C/seal regression.
seq256_pending_action_outcome: "RESOLVED — operator authorized one more PR #44 hardening round (argv0 normalization + fail-closed on dynamic/wrapper forms + RAILS F2), 2026-11-04."
seq257_pending_action_outcome: >
  Hardening pushed c4a819c (brief-scope.sh, test_brief_scope_hook.py, RAILS.md); suite 4009 passed/1
  skipped/0 failed; focused 43 passed. argv0 forms now deny. BUT Haiku 5.5 re-review VERDICT FAIL:
  5 NEW hook bypasses via shell expansion of the literal-token parser: (1) gh ap[var]i ... -f,
  (2) gh [A] ... -f with A=api, (3) brace {gh,api} ... -f, (4) gh api ... [F] with F=-XPOST dynamic arg,
  (5) F=-XPOST then gh api ... [F]. Also R6 FAIL: RAILS.md still has a #13 literal (:97-98) and the
  "ask tier" wording (:79). Builder disclosed the prior-call alias/function gap too.
decision_opus: >
  The hook is SUPPLEMENTAL per RAILS.md; a static per-command parser cannot be made watertight against
  shell expansion (brace/var/substitution/alias/function) — this is whack-a-mole. The real exposure is
  the SETTINGS layer: settings.json:51-52 allow branches/main and commits/*/check-runs with a trailing
  wildcard absorbing any args, so a mutating call on those prefixes auto-approves with the leaky hook as
  the only control. Durable fix is the settings/branch-protection layer, not more hook patches.
seq258_pending_action_outcome: "RESOLVED — operator chose Opt1 (2026-11-04): remove the gh-api auto-approve surface; hook is best-effort DiD only."
pending_action:
  action: "Opt1 minimal fix on claude/rails-repair (files already in RAILS_SECTION_10, no new seal). settings.json: remove both trailing-wildcard gh-api allows (branches/main, commits/*/check-runs) so NO gh-api auto-approves — all fall to Claude Code default permission prompt. brief-scope.sh + RAILS.md: remove all claims the hook is complete/fail-closed against every shell form; state best-effort defense-in-depth. RAILS.md: fix remaining #13 literals + ask-tier wording to match enforcement (default prompt). tests/test_brief_scope_hook.py: assert settings.json allow has NO gh-api entry (no auto-approved surface) + docs match. Sonnet 5.5 fix, Haiku 5.5 review, Opus final + full suite. PR #44 draft; no merge/mirror/3c712d4."
  pr: 44
  branch_base_head: c4a819c554fce1c43495e56ba2bf69020923cd47
  outcome: >
    RESOLVED — PR #44 MERGED (squash) as main commit 6e206e6 2026-11-04T14:34:28Z,
    --match-head-commit f9070dd enforced. The merged head carries Opt1 (gh-api
    auto-approve surface removed; hook is best-effort DiD) AND the operator's
    rails-policy correction (2026-11-04): repo .claude/ is the sole canonical and
    executable source — KRONOS commands/agents are NOT mirrored into ~/.claude;
    scripts/check_rails_drift.sh flipped from repo->global parity to a duplicate
    detector (fails on kronos-*.md in user scope or a second in-repo .claude/, or a
    missing canonical); Edit(.claude/**) deny restored. Gates: 4009 passed/1
    skipped/0 failed re-measured on f9070dd; Haiku independent review PASS on §8
    reqs 1-3; scope-audit test_B31_Q_scope_audit green; CI none; main protected
    (ruleset void-rule-kronos). Rails verified present on origin/main at 6e206e6.
seq259_pending_action_outcome: >
  WRITE-AHEAD superseded: the Opt1 fix plus the operator's canonical/no-mirror correction
  shipped together in PR #44 and merged as 6e206e6 (see pending_action.outcome above).
pending_action:
  action: "none — rails-repair complete and merged to main (6e206e6). Four global v6 duplicates remain under ~/.claude by design (transitional, accepted); deletion deferred until operator authorizes post-merge. Local main NOT reset (still 3c712d4, 1 ahead/3 behind origin/main). Awaiting operator direction."
  pr: null
  outcome: pending
