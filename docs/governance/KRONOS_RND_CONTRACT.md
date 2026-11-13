# KRONOS R&D Contract

Version: 1.4.2

## §0 Status & authority

This file is the sole binding R&D governance for KRONOS as of version 1.4.2.

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

Under contract v1.4.0, v1.4.1, and v1.4.2 the object additionally carries `contract_version` and, when `contract_version` is exactly `1.4.0`, exactly `1.4.1`, or exactly `1.4.2`, the strict render fields that back §15: the `[WHEN]` milestone (locked baseline, numerator, denominator, percentage-or-`UNKNOWN`, remaining gates, ETA assumptions, confidence) under `when.milestone`; the Goal-Framed Reference Knowledge Transfer Ledger under `how.reference_ledger` (with an explicit not-applicable form); and the orchestrator-effort justification under `effort_justification`. The extension is version-discriminated and fail-closed: `contract_version` is required and must be one of the recognized schema-bound versions. Reports declaring a recognized legacy version (`1.3.0`, `1.3.1`, `1.3.2` — the versions that share the current eleven-required-key, five-decision-class object introduced at contract v1.3.0) validate against the permissive base; reports declaring exactly `1.4.0`, exactly `1.4.1`, or exactly `1.4.2` additionally satisfy the strict branch and its fields. A missing, malformed, or unknown `contract_version` fails closed (rejected), never silently validated as a legacy report. Historical unversioned terminal reports remain historical evidence; they are not re-represented as, and are no longer accepted as, schema-valid v1.4.0/v1.4.1/v1.4.2 report objects, and no historical record is rewritten or migrated. Strict validation (v1.4.0, v1.4.1, and v1.4.2) is never loosened. The schema remains authoritative for the required fields.

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

The set is exactly the five classes above. The strings `RESEARCH-ONLY`, `DEFERRED`, and `NO-OP` are not members of this set; they MUST NOT appear in the Decision-Class position of any rendered report, and rendering any non-enum string there is a render failure. Research influence never silently upgrades a decision class: the report-level Decision Class stays one of the five regardless of any reference-knowledge disposition.

The `[NEXT PROMPT]` section of §15 renders the next operator prompt per decision class; it is an additive presentation cross-reference and changes neither the five classes nor their meanings.

## §15 Persistent terminal presentation

Every terminal report (§9) is rendered for the operator as an ordered sequence of bracket-labeled sections in GitHub-flavored Markdown, read top to bottom; the underlying report object still validates against `docs/governance/stop_report.schema.json`. The rendering is presentation-only: what the loop emits for a human changes, what it validates against does not. The report is bounded — detailed evidence remains in artifacts (`.claude/pipeline/**` and the evidence store), referenced by evidence ID — and intermediate progress updates stay concise; the full labeled report is required only at the genuine terminal states of §9. Box-drawing characters are rejected; a necessary internal break inside a line is written as `<br>`, never a raw newline.

The sections render in this exact order:

1. `[STATUS]` — the first section; it renders `Report Type` (from `report_type`) and exactly one valid §14 Decision Class (from `decision_class`). An invalid or non-enum string in the Decision-Class position is a render failure.
2. `[WHY]` — one line; the `why` value in plain language.
3. `[WHERE]` — branch, head SHA, PR (or none), and main; from `where`.
4. `[WHEN]` — `checkpoint_seq` and `timestamp`, plus the milestone fields: locked baseline, numerator, denominator, percentage, remaining gates, ETA assumptions, and confidence. The percentage MUST name its locked-milestone baseline, numerator, and denominator; if no defensible baseline exists the section renders `UNKNOWN`, never an invented percentage or ETA.
5. `[WHAT]` — the `what` summary, bounded. The conditional Goal-Framed Reference Knowledge Transfer Ledger renders here, nested under `[WHAT]`; it appears only when external-reference knowledge materially influenced this iteration, and otherwise states in one line that none materially influenced this iteration (never omitted silently).
6. `[WHO]` — agents and models; from `who`.
7. `[HOW]` — evidence, tests, and gates, bounded and detailed by evidence ID; from `how`.
8. `[HOW TO DO FOR NEXT STEP BASED ON SEVERITY]` — the `next` array, ranked by severity then dependency; rendered as readable bullets, one bullet per `next` entry with its fields inline (`rank · severity · decision_class · depends_on · action`); never a wide pipe table and never box-drawing. The underlying `next` array object is unchanged.
9. `[MOST RECOMMENDED ACTION]` — exactly one preferred recommendation (`recommendation`), limited to three sentences and 60 words; alternatives only when materially different.
10. `[OPERATOR ACTION]` — the exact operator response required (`operator_action`); a `SAFE-TO-APPROVE` report adds exactly one authorization line naming the PR number and the full head SHA.
11. `[NEXT PROMPT]` — mandatory on every terminal report and presentation-only; it renders the next operator prompt, placed immediately after `[OPERATOR ACTION]` and before the final `RECOMMENDED ORCHESTRATOR EFFORT` line. When a prompt exists it renders as exactly one fenced ```text block holding exactly one single line (one copy-ready prompt), with no alternatives and no commentary inside the fence; when none exists it renders the bare token `NONE` with its reason and no fence. The rendered prompt is one line of at most 200 Unicode code points (Python `len` of the decoded string) and carries only the exact action, essential identifiers, the mandatory pause, and critical prohibitions. The prompt is never truncated: when no safe prompt fits within 200 code points, or the derived prompt would violate any listed constraint, `[NEXT PROMPT]` renders the verbatim fallback line `REVIEW-REQUIRED: discuss the decision above; do not act.` instead of a clipped prompt. The fallback is presentation-only and does not change `decision_class`. The prompt is derived only from `decision_class`, `operator_action`, `recommendation`, `where.pr`, and `where.head_sha`, and is never invented. It MUST NOT broaden scope beyond the approved brief, infer or assert §6/§8 (live-use) authority, weaken or bypass a blocker or gate, introduce a new target, or embed raw external-reference instructions. It never upgrades or overrides a decision class; if the derived prompt would violate any of these constraints, it renders the verbatim fallback line instead. Per decision class:
    - `AUTO-CONTINUE` — renders exactly `NONE — loop continues autonomously`, with no fence.
    - `SAFE-TO-APPROVE` — renders one fenced ```text block holding a single copy-pasteable authorization prompt naming the PR number (`where.pr`) and the full head SHA (`where.head_sha`); the prompt is one line of at most 200 code points, else the fallback line.
    - `NO-ACTION` — renders a supported next-direction prompt only when an authoritative roadmap or backlog item exists (cited); otherwise `NONE` with the reason. Direction is never fabricated. Where a next-direction prompt renders it is one line of at most 200 code points, else the fallback line.
    - `REVIEW-REQUIRED` — renders one fenced ```text block holding the single recommended decision prompt, preserving every required human choice and boundary: it states the decision, does not make it, and does not pre-authorize a merge or any §6/§8 action; the prompt is one line of at most 200 code points, else the fallback line.
    - `HOLD` — never renders an override, bypass, force, `--admin`, or `--auto` prompt; it renders only the remediation step or the safe resume condition. A `HOLD` prompt that would advance past the blocker is a render failure. Where a `HOLD` prompt renders it is one line of at most 200 code points, else the fallback line.
12. The final line `RECOMMENDED ORCHESTRATOR EFFORT: <LOW|MEDIUM|HIGH> — <justification>` is mandatory on every terminal report. It is presentation-only, rendering the existing validated `opus_effort` enum plus one concise technical justification; default LOW, with MEDIUM or HIGH requiring the stated reason. Thin-Orchestrator delegation (§1) is preserved.

The Goal-Framed Reference Knowledge Transfer Ledger, when it renders, carries one physical line per materially-influencing reference, each naming: source, pinned SHA, evidence ID, license / privacy status, Observed / Inferred / Unknown epistemic status, G1 / G2 / G3 mapping, clean-room evolution, disposition (Adopt / Adapt / Defer / Investigate / Reject), and implementation status. Implementation status is the sole authority for whether anything shipped; it reads not-implemented unless a merged PR or measured evidence proves otherwise. The loop MUST never represent research as implemented. The ledger's machine form nests under `how.reference_ledger`, with an explicit not-applicable form when no reference materially influenced the iteration.

The machine object remains schema-valid and version-discriminated: a report rendered under this section declares `contract_version` exactly `1.4.0`, exactly `1.4.1`, or exactly `1.4.2` (all satisfy the strict branch and its fields), nests the `[WHEN]` milestone fields under `when.milestone`, and carries the ledger under `how.reference_ledger` and the justification under `effort_justification`; a report declaring a recognized legacy version (`1.3.0`, `1.3.1`, `1.3.2`) validates against the permissive base, while a missing, malformed, or unknown `contract_version` fails closed rather than falling back to legacy validation; historical unversioned reports remain historical evidence rather than schema-valid v1.4.0/v1.4.1/v1.4.2 objects, and strict validation is never loosened.

Flat key/value terminal reports (for example `What: ...` lines in place of the labeled sections) are prohibited. Pre-response self-check (perform before emitting any terminal report; re-render on any failure): the labeled sections appear in the order above with `[STATUS]` first and a valid §14 Decision Class; `[WHEN]` names its locked baseline, numerator, denominator, remaining gates, ETA assumptions, and confidence, or renders `UNKNOWN`; the conditional ledger is present under `[WHAT]` or states none materially influenced this iteration; `[MOST RECOMMENDED ACTION]` holds exactly one preferred recommendation within three sentences and 60 words; `[NEXT PROMPT]` is present and complete, is a single line of at most 200 Unicode code points (the report is rejected, fail closed, if it exceeds 200 code points), and when no safe prompt fits within the bound the verbatim fallback line `REVIEW-REQUIRED: discuss the decision above; do not act.` is emitted and nothing else; the report is also rejected if `[NEXT PROMPT]` is truncated, merged with another section, malformed (missing or incorrect fence), or incomplete; the final `RECOMMENDED ORCHESTRATOR EFFORT` line is present with a justification; no flat key/value report; no box-drawing character anywhere.

## §16 Single-source rule

- This contract is the sole semantic authority for the decision classes (§14) and the persistent terminal-presentation policy (§15). `CLAUDE.md`, `.claude/RAILS.md`, and `.claude/commands/kronos-continue.md` reference and operationalize those clauses; they never independently redefine them.
- `docs/governance/stop_report.schema.json` mirrors only the permitted decision-class enum and the required fields; it carries no decision-class semantics of its own.
- After merge, `kronos/loop-state` records the active `contract_version` (1.4.2) and the verified hashes only; it never duplicates the contract body.

Contract-Version: 1.4.2
