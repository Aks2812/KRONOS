# KRONOS loop-state checkpoint

seq: 2
derived_at: 2026-10-18T04:35:00Z
repo_path: /home/void/Void-Projects/KRONOS-Artifacts/KRONOS-void
baseline: docs/loop/KRONOS_LOOP_ARCHITECTURE_v6.md
stage: FORK-2

provider:
  anthropic_base_url: "http://127.0.0.1:8787"
  custom_base_url: true
  managed_settings_fetched: false
  org_policy_fetched: false
  model_picker_lists_claude_sonnet_5: false
  claude_sonnet_5_reachable: true   # dispatch succeeded; see subagent_model_resolution
  note: >
    This session runs against a custom ANTHROPIC_BASE_URL (http://127.0.0.1:8787).
    As a direct result, managed settings and org policy are NOT fetched, so no
    enterprise-managed permission or model constraints are in effect here — the
    rails observed in this repo come from .claude/settings.json, the
    .claude/hooks/brief-scope.sh PreToolUse hook, and per-agent tools lists only.
    Additionally, claude-sonnet-5 does not appear in the /model picker under this
    provider. The kronos-builder frontmatter pin (model: claude-sonnet-5) is left
    exactly as written: do NOT substitute any other model for it, and do not treat
    its absence from the picker as a reason to change the pin.

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

pending_action: >
  HELD, not executed: direct push of local commit 33a882f ("chore(loop): add KRONOS loop
  scaffolding and v6 architecture baseline", 7 files, clean fast-forward over
  dcbdba95) to origin/main. TE.md authorized it on the stated condition that the push
  would prompt; the session was in bypass-permissions mode, where that prompt does not
  exist. Maintainer directed: do not push; relaunch in default mode and push from there.
  Commit exists locally only. origin/main remains dcbdba95.

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

## RAIL-CHECK FINDINGS — session kronos-railcheck (first-class, not a footnote)

permission_mode_breach:
  severity: high
  declared: '.claude/settings.json sets "defaultMode": "default"'
  actual_observed: "bypassPermissions"
  observation_method: >
    Session transcript record 3616f42d-a39a-4a6f-b4b9-a65f2264a5bd.jsonl: 16 occurrences
    of "permissionMode":"bypassPermissions", zero occurrences of any other value. The
    PreToolUse hook's own permission_mode field was NOT used, because brief-scope.sh does
    not log its stdin and .claude/** is Edit-denied; the hook was deliberately left
    unmodified rather than instrumented via a Bash write that would have routed around
    that deny rule.
  cause:
    proximate: "launch flag --dangerously-skip-permissions"
    full_argv: "claude --dangerously-skip-permissions -n kronos-railcheck --model claude-opus-5"
    persistent_sources:
      - path: "/home/void/.zshrc:260"
        content: 'alias claude="claude --dangerously-skip-permissions"'
        effect: >
          PERSISTENT AND INHERITED. Every `claude` invoked from an interactive zsh gets
          bypass mode. Relaunching by typing `claude` will NOT produce default mode.
          Must be bypassed explicitly (`command claude`, `\claude`, or full path) or the
          alias removed.
      - path: "/home/void/.claude/settings.json"
        content: '"permissions": { "defaultMode": "bypassPermissions" }'
        effect: >
          User-level default. Project .claude/settings.json "default" outranks it by
          precedence, but it is a second independent source of the same posture and
          should be corrected too.
    ruled_out:
      - "project .claude/settings.local.json — absent"
      - "/home/void/.claude/settings.local.json — absent"
      - "/etc/claude-code/managed-settings.json — absent (no managed settings; see provider)"
      - "--settings payload — not present in argv"

  consequence:
    ask_tier_inert: >
      In bypass mode the entire ask tier does not exist. .claude/settings.json's ask list
      is therefore unenforced: Bash(gh pr merge *), Bash(gh pr ready *),
      Bash(gh issue close *), WebFetch, WebSearch.
    merge_gate_exposed: >
      The merge gate lives in the ask tier. Bare `gh pr merge 13` is ask-tier and was
      NEVER TESTED by the four negative checks. PR #13 was mergeable_state clean and main
      unprotected, so in this session that single command would have merged PR #13
      silently, with no prompt.
    also_exposed: >
      Every git push form outside the two allow rules, including the direct push to main
      that this checkpoint records as held.
    scope_of_what_was_actually_validated: >
      The four negative checks exercised DENY-TIER rules only (--admin, --auto, --force,
      and two Edit path denies). They validated the deny layer and nothing else. They are
      NOT evidence that the ask tier works, and must not be cited as such.
    deny_tier_verdict: "deny rules fired correctly in all five attempts; zero bypassed"

  remediation:
    - "No loop session runs outside default permission mode."
    - >
      Step 2 of every loop turn must ASSERT the observed permission mode before
      dispatching anything, and abort the turn if it is not default. Assert on observed
      mode, never on /config's 'Default permission mode', which reports the default for
      NEW sessions and not the running mode.
    - "Remove or override the .zshrc alias; set user-level defaultMode off bypassPermissions."
    - >
      Prefer deny-tier rules over ask-tier rules for anything that must not happen, since
      the ask tier is silently inert under bypass. Consider moving the bare
      `gh pr merge *` rule from ask to deny, with merge performed only by the maintainer.

negative_checks:
  session: kronos-railcheck
  tier_exercised: deny
  layer_that_fired: >
    .claude/settings.json deny rules in all five cases. Not brief-scope.sh (no
    permissionDecisionReason text appeared) and not a tool allowlist.
  results:
    - check: "Edit src/kronos/manifest.py"
      refusal: "File is in a directory that is denied by your permission settings."
      note: "message wording is generic and does not name the matching rule"
    - check: "Edit .claude/settings.json"
      refusal: "File is in a directory that is denied by your permission settings."
    - check: "gh pr merge 13 --admin"
      refusal: "Permission to use Bash with command gh pr merge 13 --admin has been denied."
    - check: "gh pr merge 13 --auto"
      refusal: "Permission to use Bash with command gh pr merge 13 --auto has been denied."
    - check: "git push origin HEAD:refs/heads/claude/test --force"
      refusal: "Permission to use Bash with command git push origin HEAD:refs/heads/claude/test --force has been denied."
  post_state_verified: >
    manifest.py unmodified; settings.json unmodified; PR 13 open with autoMergeRequest
    null; refs/heads/claude/test absent from origin.
  untested_and_known_exposed:
    - "bare `gh pr merge 13` (ask-tier) — would have merged silently; see above"

subagent_model_resolution:
  status: verified
  pin: "kronos-builder frontmatter — model: claude-sonnet-5"
  evidence_usage_session_block:
    claude-sonnet-5: "4 input, 112 output, 8.7k cache read, 11.8k cache write ($0.0325)"
    claude-opus-5: "1.1k input, 8.4k output"
  evidence_source: >
    MAINTAINER-REPORTED. The model did not and cannot read /usage — it is a client-side
    slash command whose output never enters the model's context. Recorded on the
    maintainer's direct report of the Session block, not on independent observation.
  independent_corroboration: >
    Task telemetry for the dispatch, observed directly by the orchestrator, is a tight
    match for the reported sonnet line: subagent_tokens 11871 (vs 11.8k cache write),
    tool_uses 1, duration 4830ms, result "# KRONOS". Additionally
    /home/void/.claude/settings.json carries "model": "claude-sonnet-5" and a
    modelSettings entry for it, confirming the id is valid under this provider despite
    its absence from the /model picker.
  conclusion: >
    The frontmatter pin resolved; it did not fall back silently to Sonnet 5.5 or Opus.

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
