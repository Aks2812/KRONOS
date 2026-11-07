# KRONOS R&D Contract

Version: 1.3.2

## §0 Status & authority

This file is the sole binding R&D governance for KRONOS as of version 1.3.1.

- `docs/loop/KRONOS_LOOP_ARCHITECTURE_v7.md` (v7) and `docs/loop/CE.md` (CE) are retained UNCHANGED as historical provenance. They are NO LONGER independently co-binding; where they overlap this contract, this contract supersedes them. (Transition recorded: previously v7 + CE on `origin/kronos/loop-state` were the binding contract.)
- `.claude/RAILS.md`, `.claude/agents/*` and `.claude/commands/kronos-continue.md` are enforcement/operational implementations of this contract, not independent authorities.
- Integrity manifest: `docs/governance/contract_manifest.json`. Stop-report schema: `docs/governance/stop_report.schema.json`.
- GATE-1 and GATE-2 are the maintainer's. The loop neither produces nor unlocks them.

## §1 Thin-Orchestrator delegation & effort policy

- The orchestrator is thin: it delegates work to role agents and does not do the builder's or reviewer's work.
- Zero context between researcher, builder and reviewer steps; handoff is files on disk, not conversation.
- The expensive model never reads raw terminal errors; cheaper agents measure and return evidence.
- Dispatch builder and reviewer as foreground subagents, never forks.
- Never pass the builder's report or reasoning to the reviewer; give it only the brief and the diff range it measures itself.
- Do not create an unused orchestrator subagent.
- The researcher must not be told to write files while it is read-only; prefer returning findings.
- ACT WITHOUT ASKING: repository reads; the brief's named tests; the brief's named CyberGym compose stack; commits and pushes to a feature branch and to the state branch; creating a draft PR; edits to files an approved brief permits.
- Effort: Headroom compression averages about 0.7% and is not a lever. `rtk test` returns exit 0 on failure: read the SUMMARY line, never `$?`.

## §2 Roles & models

Authoritative pins:

| Role | Model | Tools | Disallowed |
|---|---|---|---|
| Orchestrator / semantic verifier | Opus (the primary session; no agent file) | n/a | n/a |
| Researcher (`kronos-researcher`) | claude-sonnet-5 | Read, Glob, Grep | Write, Edit, Bash, WebFetch, WebSearch |
| Builder (`kronos-builder`) | claude-sonnet-5-5 | Read, Edit, Write, Bash, Glob, Grep | WebFetch, WebSearch |
| Reviewer (`kronos-reviewer`) | claude-haiku-5-5 | Read, Bash, Glob, Grep | Write, Edit, WebFetch, WebSearch |

`.claude/agents/*` frontmatter MUST match these pins; the contract tests enforce agreement. Only three agent definitions exist (researcher, builder, reviewer); there is no orchestrator agent file.

- Researcher: read-only; returns cited facts only, no conclusions, recommendations or summaries of intent.
- Builder: edits only dispatch-authorized files, else returns NEEDS-DECISION naming file and reason. Never `git add -A`; stages explicit paths only. Decides pass/fail from the runner's summary line, not the shell exit code. Does not open, modify, mark ready, comment on or merge any PR unless the dispatch says so. No live targets or network beyond what is instructed.
- Reviewer: independent; reviews the approved brief and diff and reports evidence and test results. Not read-only (it has Bash) and not an unrestricted shell: Bash is bounded to the project test command, `git diff`/`log`/`show`/`archive`, `sha256sum`, `grep`, `wc`, and reading files; no checkout, reset, branch switch, install, network or PR actions. It may run only project-approved local tests. It never rounds UNVERIFIABLE up to PASS; an assertion in a commit, comment or doc is not evidence. It audits the full file window `git diff --name-only <base>..HEAD` and confirms every changed path is authorized. It is isolated from the builder's report and reasoning; wanting it is the signal to measure yourself.
- Escape hatch: the orchestrator may request a one-off independent Opus review when it materially changed code it is reviewing, or when a brief's deliverable is a judgment. Requesting it is never a failure.

## §3 Gates

- GATE-1 = maintainer approval of a brief. Reviewer output is `.claude/pipeline/04-review/review-evidence.json`, not `gate1.json`.
- GATE-2 = maintainer merge authorization naming the PR number and exact head SHA, with the ten-item MERGE-GATE (§7) re-measured the same turn.
- A recommendation or `continue` is never authorization to cross a human gate, expand scope, push, or merge.
- Crossing a human gate requires an explicit maintainer instruction naming what is authorized.
- The maintainer is the remaining independent check; the final step hands up measured evidence, not conclusions.

## §4 Pause conditions & circuit breaker

- Circuit breaker: the 3-attempt reviewer-builder cycle is the BUILD bound. Maximum 3 attempts, then HALT and escalate to the maintainer. Exhausting the bound is a PAUSE-DECISION, not a retry.
- Prose silence is a PAUSE-DECISION. Expected values derive from the brief's prose, never from observed behaviour. Excluded-first default-deny.
- STOP AND ASK when the next action is outside an approved brief, ambiguous, scope-sensitive, needs authorization not yet given, or an iteration bound is reached. Record the pending_action and a recommendation first, and emit the canonical schema-validated stop-report (§9).
- STOP WITHOUT ASKING at a usage limit. Do not switch models, start another session, or wait for a reset. A usage limit means stop, not switch models. The operator resumes by typing: continue
- FAIL CLOSED: if the checkpoint carries a pending_action with no recorded outcome, or a re-derived fact contradicts the checkpoint, STOP and report with the canonical schema-validated stop-report (§9).
- A scope or authorization violation halts; no approval overrides it.
- Within approved scope, continue without asking routine confirmations.

## §5 Authorization boundaries

- NEVER edit the signed manifest (`manifest.py`), `.claude/`, `.github/`, or `cybergym/`; never use the network outside an approved brief.
- Do not modify KRONOS product code, signed scope data, or external repo settings.
- A scope or authorization violation halts; no approval overrides it.
- `gh pr merge --admin`, `--auto`, `--disable-auto` are denied (nine deny entries, three shapes each). The real boundary is `ask` on `Bash(gh pr merge *)` plus GitHub branch protection including administrators.
- `git push --force` / `--delete` are denied in three-shape patterns.
- `git push origin HEAD:refs/heads/claude/*` is removed from allow (it would permit a smuggled `--force`); feature-branch pushes fall to ask.
- `git push origin *:refs/heads/kronos/loop-state` stays in allow (anchored tail).
- `gh api` allow is narrowed to GET-only `branches/main` and `commits/*/check-runs`; `brief-scope.sh` denies mutating/non-GET `gh api` and fails closed on unparseable input.

## §6 Live-use restrictions

- §8 of a brief is acceptance criteria; §6 is the live-use gate. They are never conflated. The section number is named in every dispatch.
- CyberGym only; no live targets.
- Do not enable live-target work or expand scope.
- Builders use no live targets or network beyond what is instructed.

## §7 MERGE-GATE

Before proposing any merge, re-measure all ten items in the same turn:

1. main protected;
2. PR not draft;
3. PR open and unmerged;
4. head SHA equals the operator-authorized SHA;
5. independent reviewer PASS on the brief's §8 acceptance criteria by evidence;
6. CI green or `ci: none` recorded;
7. the brief's own local test evidence re-measured (suite 0 failed, decided from the runner's summary line, never `$?`);
8. the brief's scope-guard / seal-tax scope audit green;
9. orchestrator Gate-2 semantic review PASS;
10. no hard-boundary or out-of-scope file touched.

Merge only the PR the operator names this turn, with exactly:

`gh pr merge <PR> --squash --match-head-commit <operator-authorized-SHA>`

Never `--admin`, never `--auto`. Do not mark a PR ready for review or close an issue without asking.

## §8 Write-ahead checkpointing

Before every consequential action, write the next checkpoint (seq + 1) with its pending_action to `docs/loop/PROGRESS.md` on `kronos/loop-state`, push it, and confirm the push succeeded; write the outcome after. Never proceed on an unpushed checkpoint. Checkpoints are public: no credentials, targets, client identifiers, or manifest contents.

## §9 Stop-report (5W+1H)

A canonical schema-validated stop-report is REQUIRED on EVERY terminal path: STOP AND ASK, PAUSE, BLOCKED, COMPLETE, no-pending-action, circuit-breaker exhaustion (HALT), failed review (BLOCKED), contract-integrity hash-mismatch (HALT), and usage-limit HALT. Each validates against `docs/governance/stop_report.schema.json`; a bare pending_action + recommendation is insufficient. The schema (`docs/governance/stop_report.schema.json`) is authoritative for the required fields; the keys below are informative, not a field count:

- WHAT
- WHY
- WHO (agents + models)
- WHEN (checkpoint seq + timestamps)
- WHERE (branch, SHA, PR, main)
- HOW (evidence / tests / gates)
- NEXT (array, ranked by severity and dependency)
- RECOMMENDATION (exactly one)
- OPERATOR_ACTION (the exact response required)
- DECISION_CLASS (exactly one class, §14)
- OPUS_EFFORT (§15)

It is validated by `docs/governance/stop_report.schema.json` (lowercase keys, plus `report_type`) and is a superset of v7's prior five-item hand-up (why stopped; checkpoint; what completed with evidence; recommended next plus alternatives; exact maintainer response), which was mandatory on every pause or finish.

## §10 Artifact authority & precedence

1. This contract outranks v7/CE provenance.
2. Repo `.claude/` is the sole canonical/executable source; there is no mirror. `check_rails_drift.sh` fails on a missing rail file, a `kronos-*.md` in user scope, or a second in-repo `.claude/`.
3. `docs/loop/PROGRESS.md` on `kronos/loop-state` is the durable checkpoint; `.claude/pipeline/` is per-iteration working state only, never a second checkpoint copy.
4. Where the checkpoint disagrees with live Git/GitHub, LIVE WINS and the mismatch is reported.
5. The binding source was previously v7 + CE; v7 superseded v6's role model only. That transition to this contract is recorded here.

## §11 Scope control & seal-tax

- Every review finding becomes a test.
- Full-window file audit is a hard gate: `git diff --name-only <base>..HEAD` asserts every path is in the authorized scope.
- Explicit-path staging; never `git add -A` on a brief-scoped branch.
- Totals are refreshed last: as the final edit after the last suite run.
- Claims must be enforced or softened: a test proves each claim, or the prose is weakened to what ships.
- A builder returns NEEDS-DECISION when a fix requires an unauthorized file.

## §12 Contract integrity

`docs/governance/contract_manifest.json` records the version and sha256 of this contract AND of the stop-report schema. `/kronos-continue` verifies both hashes before any loop action and STOPS on mismatch (fail-closed). Every new loop checkpoint records the active contract_version and hash.

## §13 Bounded AUTO-NEXT

Within an approved brief's scope the loop selects and executes the single safest, highest-priority unblocked action without routine confirmation. It still pauses for every mandatory pause: merge authorization; §6/§8 live execution; destructive actions; security-boundary changes; protected-branch writes; production-impacting scope expansion; exhausted repair limits; material architecture ambiguity. It preserves Thin-Orchestrator delegation (§1) and all existing gates.

### §13.1 Standing AUTO-BRIEF envelope

When `pending_action` is NONE (no pre-approved brief is open), the loop does not halt solely for want of a brief. It inspects the authoritative checkpoint backlog and roadmap, selects the single highest-priority ELIGIBLE action, creates that action's scoped brief, and executes research -> build -> review -> repair -> draft PR without routine authorization.

An action is ELIGIBLE only if it is ALL of: recorded (named in the checkpoint backlog or roadmap), unblocked, reversible, branch-local, precisely scoped, non-live, and non-destructive; AND it touches none of: secrets, permissions, security boundaries, governance (this contract, the integrity manifest, the stop-report schema), `.claude/**`, or any protected-branch modification.

The mandatory pauses are unchanged and override selection: merge authorization; §6/§8 live execution; destructive actions; governance changes; `.claude/**` changes; security-boundary changes; protected-branch writes; production-impacting scope expansion; exhausted repair limits; and material or unresolved ambiguity. An ineligible backlog item is never auto-selected; it is deferred to the maintainer.

A missing pre-approved brief MUST NOT cause a pause when an eligible recorded backlog item exists. If no eligible item exists, the loop emits the complete canonical schema-validated idle (`no-pending-action`) stop-report (§9) and waits.

AUTO-BRIEF preserves Thin-Orchestrator delegation (§1), the gates (§3), the MERGE-GATE (§7), write-ahead checkpointing (§8), and the seal-tax (§11). It never crosses a human gate: a created brief still PAUSES before merge for GATE-2.

## §14 Decision classes

Every terminal evaluation carries exactly one decision class. This contract is the sole semantic authority for the set and its meaning; `CLAUDE.md`, `.claude/RAILS.md`, `.claude/commands/kronos-continue.md`, and `docs/governance/stop_report.schema.json` operationalize or mirror these classes and never independently redefine them.

- `AUTO-CONTINUE` — eligible, reversible, in-scope work: checkpoint and continue without operator confirmation.
- `SAFE-TO-APPROVE` — a routine protected-branch merge with exact-head independent review, complete green gates, zero failures, and no unresolved purpose-critical or Medium/Critical finding.
- `REVIEW-REQUIRED` — governance, `.claude/**`, security, privacy, authorization, destructive/history-rewriting action, §6/§8 live execution, ambiguous scope, or a purpose-critical residual finding.
- `HOLD` — red, incomplete, or conflicting evidence; an unavailable required environment; a dirty working tree; or an exhausted circuit breaker.
- `NO-ACTION` — a complete or genuinely idle state.

A finding that weakens the brief's primary acceptance objective is blocking regardless of its nominal severity.

While any such blocking finding is unresolved, the report-level decision class MUST be `REVIEW-REQUIRED` or `HOLD`; no recommendation and no next-action row may be classified `SAFE-TO-APPROVE`; and the report MUST NOT recommend accepting the blocker and merging. `SAFE-TO-APPROVE` becomes available only once no blocking finding remains.

A decision class is a readiness statement, never an authorization. `SAFE-TO-APPROVE` does not cross GATE-2: a protected-branch merge still requires the explicit maintainer authorization of §3 and the ten-item re-measurement of §7. No decision class weakens the merge, live-use (§6), security, privacy, `.claude/**` hard-deny (§5), or circuit-breaker (§4) boundaries.

## §15 Persistent terminal presentation

Every terminal report (§9) is rendered for the operator as GitHub-flavored Markdown; the underlying report object still validates against `docs/governance/stop_report.schema.json`.

- The terminal Summary and Next-Actions MUST be rendered as literal GitHub-flavored-Markdown pipe tables, each with a header row and a `|---|` separator row, and both tables MUST be emitted together inside exactly one fenced code block whose info string is `markdown` (one fence for the whole terminal report, never two separate fences). Not Unicode/ASCII box tables, and not raw JSON by default. Box-drawing characters are rejected.
- Every table row is a single physical line; a necessary internal break is written as `<br>`, never a raw newline inside a cell or a row split across physical lines.
- Pre-response self-check (perform before emitting any terminal report; re-render on any failure): exactly one fenced `markdown` block; two literal pipe tables, each with a header row and a `|---|` separator row; the Summary carries all eleven fields in the order above; the Next-Actions carries Rank, Severity, Dependencies, Decision Class, Action; every row on one physical line with internal breaks as `<br>`; no flat key/value report; no box-drawing character anywhere.
- Flat key/value terminal reports (e.g. `What: ...` lines in place of a table) are prohibited.
- One summary table with exactly these columns, in this order: Report Type, Decision Class, What, Why, Who, When, Where, How, Recommendation, Operator Action, Opus Effort. Canonical template:

```markdown
| Report Type | Decision Class | What | Why | Who | When | Where | How | Recommendation | Operator Action | Opus Effort |
|---|---|---|---|---|---|---|---|---|---|---|
| <type> | <class> | <what> | <why> | <who> | <when> | <where> | <how> | <recommendation> | <operator action> | <LOW> |
```

- One next-actions table with exactly these columns, in this order: Rank, Severity, Dependencies, Decision Class, Action. Canonical template:

```markdown
| Rank | Severity | Dependencies | Decision Class | Action |
|---|---|---|---|---|
| 1 | <severity> | <dependencies> | <class> | <action> |
```

- Escape every pipe character inside a cell as `\|`, and write multi-line cell content with `<br>` (never a raw newline inside a cell).
- Provide exactly one preferred recommendation; list alternatives only when materially different.
- A `SAFE-TO-APPROVE` report includes exactly one authorization line naming the PR number and the full head SHA.
- Intermediate progress updates stay concise; the complete tables are required only at genuine terminal states.
- Opus effort defaults to LOW; MEDIUM or HIGH requires a stated reason in the report. Thin-Orchestrator delegation (§1) is preserved.

## §16 Single-source rule

- This contract is the sole semantic authority for the decision classes (§14) and the persistent terminal-presentation policy (§15). `CLAUDE.md`, `.claude/RAILS.md`, and `.claude/commands/kronos-continue.md` reference and operationalize those clauses; they never independently redefine them.
- `docs/governance/stop_report.schema.json` mirrors only the permitted decision-class enum and the required fields; it carries no decision-class semantics of its own.
- After merge, `kronos/loop-state` records the active `contract_version` (1.3.2) and the verified hashes only; it never duplicates the contract body.

Contract-Version: 1.3.2
