# KRONOS loop-state checkpoint

seq: 5
derived_at: 2026-10-18T07:05:00Z
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
  protected: true   # via ruleset 25333712; see branch_protection below

brief:
  path: SPEC_BRIEF10.3.md
  sha256: 75a666d81a3bcce92915c51fba7e75a3d08ce389fc65458ff475a95bdf0d8938

pr_13:
  state: open
  draft: true
  merged: false
  head: d2ad51e611927525780b9069db2bc16b0a7209b2
  mergeable_state: clean
  reviews: 0
  check_runs: 0

pr_14:
  state: open
  draft: true
  merged: false
  head: 33a882f9a43c01e7fe9696cbb4ccad6bfb8e771f
  base: main
  commits: 1
  mergeable_state: clean
  note: >
    Scaffolding PR, not a SPEC_BRIEF — the v6 3.1 acceptance-criteria path does not apply.
    Branch claude/loop-scaffolding pushed from session kronos-railcheck.

issue_2:
  state: open

ci: "none; local evidence only"

tests:
  last_run: "2026-10-18 FORK-2 — base 620 passed/1 skipped; PR head 1023 passed/6 FAILED/1 skipped"

merge_authorization: null

pending_action: null   # seq 4's FORK-2 review completed; outcome below
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

## SEQ 3 FINDINGS — rail-layer survivability under bypassPermissions

hook_deny_survives_bypass:
  status: verified
  severity: load-bearing
  evidence: >
    Direct `gh api -X POST /rate_limit` was blocked by brief-scope.sh with its own
    permissionDecisionReason text, in a session whose observed permissionMode is
    bypassPermissions. The call never reached GitHub. Payload was chosen to mutate
    nothing had it landed.
  layer_table:
    deny_rules:            "survives bypass — 5/5 in the seq 2 negative checks"
    pretooluse_hook_deny:  "survives bypass — verified above"
    ask_rules:             "INERT under bypass"
    no_matching_allow:     "INERT under bypass"
  consequence: >
    The hook is the only place an ask-tier condition can be enforced without the ask
    tier. This is what makes the mode guard viable where a settings.json change is not.

mode_guard:
  status: authored, NOT APPLIED
  purpose: "remediation for seq 2 merge_gate_exposed"
  design: >
    Defer in permission_mode "default" so `ask: Bash(gh pr merge *)` authorizes as v6 2.2
    intends; deny otherwise. Avoids the blanket-deny trap: per v6 2.1 the tiers are
    first-match-wins and an allow cannot carve an exception out of a deny, so
    `deny: Bash(gh pr merge *)` would swallow the narrow authorized-merge allow and kill
    MERGE-GATE criteria 4 and 9. The tier is not where the hole lives; the mode is.
  covers: ["gh pr merge", "gh pr ready", "gh issue close", "WebFetch", "WebSearch"]
  field_name: "permission_mode, top-level, snake_case (maintainer-confirmed against the hooks docs)"
  dry_run: >
    21 crafted hook inputs against the guard logic in isolation, rails untouched: defers
    in default mode; denies all five subjects under bypassPermissions and acceptEdits;
    fails closed when the mode field is absent; no over-reach on git status, gh pr view,
    `gh pr mergeability` (word boundary), non-Bash tools, or the subject appearing inside
    a quoted string. Chained (`echo ok; gh pr merge 13`) and irregular whitespace caught.
  not_yet_verified: >
    Live behaviour and placement. The guard must sit after the gh api method filter and
    BEFORE the AGENT_TYPE assignment, or it guards only dispatched subagents while the
    parent orchestrator — the actor that would merge — goes unguarded.

command_text_indirection:
  status: verified
  severity: high
  finding: >
    Every command-text rail in this design is defeated by one level of shell indirection.
    The hook's regexes anchor on start-of-string or [;&|], so quoting the command inside
    another command puts it out of view.
  evidence:
    denied:  'gh api -X POST /rate_limit  -> hook denied, never reached GitHub'
    evaded:  'bash -c "gh api -X POST /rate_limit"  -> reached GitHub, HTTP 404'
  also_defers: ["eval \"...\"", "xargs gh pr merge", "/usr/bin/gh pr merge", "./script.sh"]
  deny_tier_inference:
    status: INFERENCE, NOT VERIFIED
    claim: >
      settings.json deny patterns are command-text prefix matches by the same mechanism,
      so `bash -c "gh pr merge 13 --admin"` should likewise evade the nine --admin/--auto
      deny entries that v6 2.1 builds the merge boundary on.
    why_untested: >
      The only payload that would test it is a real merge of PR #13 into unprotected
      main. Unlike the /rate_limit probe there is no null version. Confirm on a throwaway
      repo, never this one.
  framing: >
    Consistent with RAILS.md's own "discipline, not security boundary" language — but it
    means the DENY tier is not a boundary either, which RAILS.md does not say.

force_push_deny_gap:
  status: verified
  severity: high
  finding: >
    The nine force/delete deny entries all anchor on the literal token --force or
    --delete. Two force forms carry neither and match no deny rule.
  uncaught:
    - form: "git push origin +HEAD:refs/heads/<branch>"
      note: "git's refspec force syntax — no flag exists to pattern-match"
    - form: "git push origin HEAD:refs/heads/<branch> --force-with-lease"
      note: "`git push * --force *` needs a space after --force; this has -with-lease"
  method: >
    Both probed with --dry-run, which performs no remote mutation; both reached `ok`,
    i.e. no deny rule matched. Confirmed nothing was created on origin afterwards.
  live_exposure: >
    These fall through to the default prompt, which is inert under bypass. So in a bypass
    session `git push origin +HEAD:refs/heads/main` executes unprompted. NOT ATTEMPTED.
    This is the second and stronger argument for branch protection: allow_force_pushes
    false is enforced server-side and no refspec syntax reaches past it.
  recommended_deny_additions: ["Bash(git push +*)", "Bash(git push * +*)", "--force* shapes with no trailing space"]
  caveat: "defense in depth only — see command_text_indirection; the server-side setting is the boundary"

rails_md_correction:
  status: verified-false
  severity: documentation
  rails_md_claims: >
    Under "Why `git push origin HEAD:refs/heads/claude/*` is not in allow": that the
    --force deny "does not catch" `git push origin HEAD:refs/heads/claude/foo --force`.
  actual: >
    It does. That is verbatim the seq 2 negative check (d) command and it was DENIED. The
    three flag-position shapes work as designed.
  conclusion_still_correct: >
    The rule should stay out of allow — but for a better reason than the one given. With
    `Bash(git push origin *:refs/heads/claude/*)` in allow, `git push origin
    +HEAD:refs/heads/claude/scope-guard-shape-aware-brief10` matches the allow, matches no
    deny, and force-pushes the branch carrying PR #13's head with no flag to notice.
  action: "correct the example in RAILS.md; the section's conclusion needs no change"

claude_branch_push_allowlist:
  status: UNRESOLVED — requested, not implemented
  history: >
    Maintainer asked for `Bash(git push origin *:refs/heads/claude/*)` to be added to
    allow, to match kronos-builder.md's claim of "two allowed refspecs". On being shown
    that RAILS.md removed that rule deliberately, and the +refspec hole above, the request
    was neither reaffirmed nor withdrawn. Not added. settings.json is unchanged.
  recommendation: >
    Do not add it. Instead correct kronos-builder.md to match settings.json, since
    RAILS.md states the fall-through prompt is intended behaviour and not a gap.

branch_push_authorization_note:
  record: >
    claude/loop-scaffolding was pushed from this bypass-mode session. That refspec matches
    no allow rule and would normally surface the default prompt, which is inert here. The
    push was made on the maintainer's explicit verbal authorization given in lieu of the
    prompt, after the orchestrator initially declined to take it. Recorded so the audit
    trail does not imply a prompt occurred.

rails_edits_not_made_by_agent:
  record: >
    No .claude/** file was modified by the orchestrator at any point. Edit(.claude/**) is
    denied, and the deny was not routed around via Bash, which would have succeeded under
    bypass. All rails changes this session were authored as patches and applied by the
    maintainer, or left unapplied. The indirection finding above means such a bypass was
    available and was deliberately not used.

## SEQ 4 — STEP 2 ASSERTIONS AND BRANCH PROTECTION

step2_assertions:
  a_checkpoint_read: "pass — origin/kronos/loop-state at 71ecc07, read without checkout"
  b_permission_mode:
    observed: bypassPermissions
    source: "session transcript, 61 occurrences, no other value"
    handling: >
      Recorded, not halted: FORK-2 is a read-only review stage, per the stage contract.
      The only write this turn is the checkpoint push to kronos/loop-state, which matches
      the allow rule `git push origin *:refs/heads/kronos/loop-state` — so no prompt was
      ever expected for it and the inert ask tier does not change its authorization.
      Any stage that writes to the repository still halts unless the mode is "default".
  c_rails_unmodified: "pass — git diff --quiet HEAD -- .claude/ clean"
  d_protection: "pass — see branch_protection"
  e_rederive: "pass — all values match the expected set"
  f_draft_and_automerge: "pass — pr.draft true, pr.auto_merge null"

branch_protection:
  status: LIVE
  mechanism: "repository ruleset, NOT classic branch protection"
  ruleset:
    id: 25333712
    name: void-rule-kronos
    enforcement: active
    target: branch
    conditions: 'ref_name.include = ["~DEFAULT_BRANCH"], exclude = []'
    bypass_actors: "[] (empty)"
    current_user_can_bypass: never
    created_at: "2026-10-18T02:30:41-04:00"
    rules:
      - deletion
      - non_fast_forward
      - pull_request (required_approving_review_count 0, allowed_merge_methods merge/squash/rebase)
  closes_seq3_force_push_deny_gap: >
    YES. non_fast_forward is enforced server-side, so both forms seq 3 recorded as
    matching no deny rule — `git push origin +HEAD:refs/heads/main` (refspec force, no
    flag) and `--force-with-lease` — are now rejected by the server regardless of local
    pattern coverage. deletion covers the --delete gap on the same basis. This is the
    first layer in the stack that is not command-text pattern matching, and
    current_user_can_bypass "never" means it binds the admin token this session holds.
  unrestricted_by_design:
    - "kronos/loop-state — rules/branches/kronos%2Floop-state returns [] (asserted empty)"
    - "claude/* feature branches — not covered by the ruleset"
  api_surface_note: >
    branches/main/protection still returns 404 "Branch not protected" because that
    endpoint reports classic protection only. branches/main.protected now reads true, so
    it IS ruleset-aware, contrary to the stage instruction's note. rules/branches/main is
    the correct probe either way and is what the assertion uses. Earlier seq 3 readings of
    protected=false were accurate at the time: the ruleset was created 02:30:41, after
    the last of those checks.

superseded_from_seq3:
  - "MERGE-GATE item 1 (main protected) moves from FAIL to pass"
  - >
      mode_guard and rails_md_correction remain NOT APPLIED, and are now OUT OF SCOPE for
      the loop: the stage contract forbids editing .claude/ outright. They are maintainer
      actions outside the pilot, not pending loop work. The orchestrator's earlier offer
      to apply them, and the proposal to remove the Edit(.claude/**) deny rule, are both
      withdrawn as incompatible with the stage contract.

## SEQ 5 — FORK-2 INDEPENDENT REVIEW OUTCOME

review:
  stage: "PILOT A / FORK-2"
  pr: 13
  head_reviewed: d2ad51e611927525780b9069db2bc16b0a7209b2
  reviewer: kronos-reviewer (foreground subagent, fresh context, no builder report passed)
  brief_sha256_verified_by_reviewer: true
  verdict: FAIL
  recommendation: "DO NOT MERGE at d2ad51e"

  section_scope_correction:
    issue: >
      The stage instruction said to review "SPEC_BRIEF10.3 section 6 (acceptance
      criteria)". Those are two different sections of the brief: section 6 is the Live-use
      gate (6 closing conditions, brief line 242) and section 8 is Acceptance criteria
      (12 items, brief line 278). Verified independently by the orchestrator against the
      brief's heading list.
    handling: >
      The reviewer flagged the ambiguity rather than picking one, and judged BOTH tables
      separately. Both are recorded below. Future stage instructions should name section 8
      for acceptance criteria and section 6 for the live-use gate.

  section_8_acceptance_criteria:
    result: "9 PASS, 1 FAIL, 1 UNVERIFIABLE-treated-as-FAIL — NOT every criterion passed"
    pass: [1, 2, 3, 4, 5, 6, 7, 8, 10, 12]
    fail:
      - criterion: 11
        finding: >
          README_scope.md carries section 6's gate verbatim, but DECISIONS.md does not,
          despite a heading claiming it does. Independently confirmed by the orchestrator:
          the gate's opening sentence appears 1 time in README_scope.md and 0 times in
          DECISIONS.md at the PR head.
    unverifiable:
      - criterion: 9
        missing_evidence: >
          No X-SCORE line, no exit code, and no explicit BLOCKED/INCOMPLETE declaration
          naming the environment appears anywhere in the diff. DECISIONS.md defers it to
          the PR body, which is not a reviewer input. Not rounded up to PASS.

  section_6_live_use_gate:
    result: "2 of 6 conditions met — FORK-2 is NOT complete and issue #2 may NOT close"
    met: [4, 6]
    not_met:
      - condition: 1
        reason: "not merged; this review is the approval step and it is not an approval"
      - condition: 2
        reason: "test suite is RED at the PR head — see test_evidence"
      - condition: 3
        reason: "unverifiable: no merge commit exists, no X-SCORE in the diff, no network"
      - condition: 5
        reason: "issue #2 cannot close without a merge commit"

test_evidence:
  method: "both trees exported read-only with git archive; nothing checked out"
  base_origin_main_dcbdba9: "620 passed, 1 skipped"
  pr_head_d2ad51e: "1023 passed, 6 FAILED, 1 skipped"
  brief_5_5_baseline_stated: "620 passed / 1 skipped (brief line 232)"
  baseline_matches: true
  contract_figure_discrepancy: >
    The stage contract cites local test evidence as "591/1". The brief's own section 5.5
    baseline is 620 passed / 1 skipped, independently confirmed by the orchestrator at
    brief line 232, and the reviewer measured exactly that on base. The 591/1 figure
    appears stale; the brief is authoritative.
  scope_guard_suite_alone: "562 passed, 0 failed"
  regressions_introduced_by_this_pr: 6
  failing_tests:
    - tests/test_invariants.py::test_invariant_out_of_scope_secret_cannot_anchor_finding
    - tests/test_invariants.py::test_invariant_find_paths_returns_seeded_mobile_to_cloud_chain
    - tests/test_query.py::test_find_paths_returns_seeded_mobile_to_cloud_chain
    - tests/test_query.py::test_find_paths_only_in_scope_excludes_out_of_scope_hop
    - tests/test_reconcile.py::test_web_endpoint_real_duplicate_merges_and_tombstones
    - tests/test_schema_graph.py::test_upsert_node_stamps_in_scope_via_scope_guard
  root_cause_measured: >
    NODE_TYPE_SHAPES narrows the endpoint and cloud-resource families, so nodes whose id
    or scope_key is written in a bare-host shape now deny where they previously allowed.
    Measured by direct probe at both trees, not inferred.
  guardrail_9_compliance: >
    COMPLIANT. The builder did not edit any of the six tests and listed them in
    DECISIONS.md as out-of-section-3 regressions, reported not edited. Confirmed absent
    from `git diff --name-only`. The resolution decision therefore belongs upstream.
  cybergym_cloud_suite:
    status: NOT INDEPENDENTLY VERIFIED
    reason: >
      Collection fails in this environment: the test client requires httpx2, which is not
      installed in the venv. The files are zero-diff and contain no scope-guard
      references, so they are structurally unaffected, but the claimed pass count is
      unconfirmed.

guardrail_10_hash_pin:
  status: verified
  detail: >
    sha256 of scope_guard.py at the PR head matches the re-pinned constant in all three
    test files that pin it, byte for byte.

reviewer_findings_beyond_criteria:
  - id: A
    severity: high
    finding: >
      Section 1.3 (exclusions are representation-blind across shapes) is only partially
      implemented. URL exclusion patterns that carry a path still route to the
      shape-, port- and scheme-bound matcher, so a deny-side under-match of exactly the
      class this brief exists to close survives for that pattern family. The patterns the
      fix did widen behave correctly. Criterion 3 was not failed on this, because every
      row section 5.2 literally enumerates passes — but 1.3 is normative prose.
  - id: B
    severity: high
    finding: >
      The section 5.4 generated grid declares the two affected cells as expected-False,
      codifying finding A as intended behaviour. This is the section 0.3 method defect
      the brief was written to prevent: the expectation table was derived from observed
      behaviour rather than from the prose. The grid also never exercises a matching path
      against those patterns, so it could not have caught it.
  - id: C
    severity: medium
    finding: >
      Section 5.4's "run the product for the allow side per node type" was run for one
      node type only. Disclosed in DECISIONS.md as a reported scope reduction, not
      concealed. Section 8.4's literal text does not require it; section 5.4's does.
  - id: D
    severity: minor
    finding: "the 5.4 exclusion grid asserts through a private matcher, not the public API"
  - id: E
    severity: minor
    finding: >
      Section 5.3's "correctly-spelled type absent from the shape table" is exercised with
      a name that is not a real schema type. The property was independently confirmed to
      hold for the two real candidates, so this is test naming, not a gap.
  - id: F
    finding: "nothing in the diff falls outside what section 3 permits"

verified_solid_measured_not_asserted:
  - "H2 closed: all 9 rows of section 5.1 observed as required"
  - "H3 closed for all 7 rows of section 5.2, both directions"
  - "fail-closed holds for every malformed, empty, None and non-schema node_type probed"
  - "the required keyword-only argument is enforced by the interpreter at both entry points"
  - "graph.py is a one-line passthrough; the untouched-module list holds"
  - "manifest.py zero-diff and nothing under cybergym/ touched"
  - "the pre-#10 signed manifest still verifies"
  - "PR #13 open, unmerged, draft, head not an ancestor of main"

reviewer_model_pin:
  status: UNVERIFIABLE BY DESIGN
  detail: >
    kronos-reviewer is pinned to claude-opus-5, the same model the parent orchestrator
    runs on, so its usage aggregates into a single per-model line and cannot be separated
    from the orchestrator's. The builder's pin was verifiable in seq 3 precisely because
    it differs from the orchestrator's. A silent fallback on the reviewer would be
    invisible to the /usage method; the practical risk is low since fallback would land on
    the same family, but it is unverified rather than verified.

## MERGE-GATE status (10 prerequisites, v6 section 3.1)

1. main protected: pass (ruleset 25333712, active, bypass_actors empty, current_user_can_bypass never)
2. PR #13 not a draft: FAIL (true)
3. PR #13 open and unmerged: pass
4. head SHA equals authorized SHA: n/a (no authorization granted yet)
5. independent review PASS on every criterion: FAIL (run at seq 5 — section 6: 2/6 met; section 8: 9 PASS, 1 FAIL, 1 UNVERIFIABLE)
5b. GitHub approving review: n/a (single-maintainer repo, see v6 section 2.4)
6. CI green or "ci: none" acknowledged: acknowledged ("ci: none; local evidence only")
7. local test evidence recorded in checkpoint: FAIL (now recorded, and RED — 6 regressions at the PR head vs a green 620/1 base)
8. mergeable_state clean, head not already ancestor of main: pass
9. merge_authorization present, granted this turn: FAIL (null)
10. clean tree, stale branches reconciled or recorded: pass (recorded above, none deleted)

Four of ten prerequisites fail (2, 5, 7, 9); 4 and 5b are n/a. Item 1 now passes.
Do not merge.

## SEQ 6 — SESSION MIGRATION TO CLAUDE CODE (Kali); STEP 2 RE-ASSERTED; FORK-2 RESEARCH OPENED

seq: 6
derived_at: 2026-10-18T00:00:00Z
stage: FORK-2
phase: RESEARCH (pre-GATE-1)

session_change:
  record: >
    R&D moved into a Claude Code session on Kali to remove Desktop/Code copying. Parent
    orchestrator claude-opus-5. Contract loaded from /home/void/TE.md (merged single
    contract) plus the kronos-continue stage instruction. No architecture revision made.

step2_assertions:
  a_checkpoint_read: "pass — origin/kronos/loop-state at 90969db, read via git show, no checkout of the state branch into the working tree"
  b_permission_mode:
    observed: default
    source: "this session's transcript jsonl, 7 occurrences of permissionMode, no other value"
    change_from_seq5: >
      seq 4/5 observed bypassPermissions. This session observes default. Writes are
      therefore authorized under the step-2b rule rather than excepted by an allow-rule
      argument. The persistent sources seq 2 named are STILL PRESENT
      (/home/void/.zshrc:260 alias, and /home/void/.claude/settings.json defaultMode
      bypassPermissions) — this session simply was not launched through the alias. The
      remediation seq 2 recommended is still outstanding and is a maintainer action.
  c_rails_unmodified: "pass — git diff --quiet HEAD -- .claude/ clean"
  d_protection:
    main: "pass — rules/branches/main lists deletion, non_fast_forward, pull_request from ruleset 25333712"
    loop_state: "pass — rules/branches/kronos%2Floop-state returns []"
  e_rederive:
    main_head: "dcbdba950a45253f2c417b0c95c6ccb6930e9221 — matches checkpoint"
    pr13_state: OPEN
    pr13_draft: true
    pr13_merged: false
    pr13_head: "d2ad51e611927525780b9069db2bc16b0a7209b2 — matches checkpoint"
    pr13_mergeable_state: CLEAN
    pr13_head_is_ancestor_of_main: false
    pr13_auto_merge: null
    pr13_reviews: "[] (no GitHub review objects)"
    issue2_state: OPEN
    brief_sha256: "75a666d81a3bcce92915c51fba7e75a3d08ce389fc65458ff475a95bdf0d8938 — matches checkpoint"
    result: pass
  f_draft_and_automerge: "pass — draft true, auto_merge null"
  pending_action_from_seq5: "none outstanding — seq 5 recorded its own outcome (review FAIL)"

handoff_conflicts_resolved:
  - id: baseline_figure
    conflict: >
      The stage instruction (kronos-continue) cites local test evidence against "the 591/1
      and 17 baselines". The brief's own section 5.5 states 620 passed / 1 skipped.
    resolution: >
      620 passed / 1 skipped is AUTHORITATIVE. Independently confirmed three ways: brief
      line 232 prose; the seq 5 reviewer's own measurement on base origin/main dcbdba9
      (620 passed, 1 skipped); and the merged contract's explicit correction. 591/1 is
      stale and is retired. The "17" figure is unsourced in the brief and is treated as
      unverified; it is not used as a gate input until a brief names it in prose.
  - id: section_numbering
    conflict: >
      The stage instruction says review "SPEC_BRIEF10.3 section 6 criterion" for
      acceptance. Section 6 is the Live-use gate; section 8 is Acceptance criteria.
    resolution: >
      Section 8 = Acceptance criteria (brief line 278, 12 items). Section 6 = Live-use
      gate (brief line 242, 6 closing conditions). Re-verified this turn against the
      brief's heading list. VERIFY runs against section 8; the live gate is section 6.
      Every dispatch names the section number explicitly. Never conflated.

standing_rule_recorded:
  id: "prose-derived expectations"
  origin: "seq 5 reviewer Finding B; third variant of the section 0.3 method defect"
  rule: >
    Expected values in any test matrix derive from the brief's PROSE, never from observed
    behaviour. A grid cell written from what the code currently does turns a conformance
    test into a change detector. If the prose is ambiguous about a cell, that is a
    PAUSE-DECISION, not a judgment call. Hard rule, permanent.

pending_action:
  seq: 6
  action: >
    FORK-2 research turn, read-only: (1) per-test in-scope/out-of-scope determination for
    each of the six regressions from section 1.3 PROSE with citation; (2) Finding A
    disposition — same brief or its own, with reasoning; (3) Findings C, D, E triage and
    proposed disposition; (4) X-score verdict, which is BLOCKED with the environment named
    unless the httpx2==2.13.1 pin from Brief 7.1 is installed and re-run at the head —
    installing it is a PAUSE-DECISION under the NETWORK rule and is NOT done here.
    Then author SPEC_BRIEF10.4 draft, push it to kronos/loop-state, and STOP for GATE-1.
  scope: "repository reads and pytest only; no .claude/, .github/, cybergym/ or manifest edits; no network beyond gh repo reads and state-branch pushes"
  outcome: pending
