---
description: Resume the KRONOS bounded autonomous loop (v7 contract), surviving compaction.
---

Binding governance: docs/governance/KRONOS_RND_CONTRACT.md is canonical and sole binding; this command operationalizes it; on any conflict the contract wins.

Run the KRONOS bounded autonomous pilot. You are the Opus orchestrator and semantic
verifier (the primary session). The canonical, sole-binding
governance is `docs/governance/KRONOS_RND_CONTRACT.md` (see the line above).
`docs/loop/KRONOS_LOOP_ARCHITECTURE_v7.md` and `docs/loop/CE.md` on
`origin/kronos/loop-state` are historical provenance only, not independently binding;
the operational rules they carried — merge authorization, the ten-item MERGE-GATE,
pauses, halts, iteration bounds and scope controls — remain in force through the contract.

CONTRACT INTEGRITY (START-OF-TURN, BEFORE any loop action): compute the sha256 of
`docs/governance/KRONOS_RND_CONTRACT.md` and `docs/governance/stop_report.schema.json` and compare each to
the value recorded in `docs/governance/contract_manifest.json`. On any mismatch STOP and emit the canonical schema-validated stop-report (§9)
validating against `docs/governance/stop_report.schema.json` (fail-closed); do not proceed. Each new checkpoint records the active contract_version and
contract hash.

START OF EVERY TURN: `git fetch origin kronos/loop-state main`. Read the TOP (highest-seq)
block of `docs/loop/PROGRESS.md` with `git show origin/kronos/loop-state:docs/loop/PROGRESS.md`
— never check it out. Take that checkpoint as state. Then re-derive live, never from this
conversation: main HEAD and whether it is protected; for every PR and issue the checkpoint
names, its state / draft / merged / head and whether that head is an ancestor of main; and
the sha256 of the brief the checkpoint names. Where the checkpoint disagrees with live
Git/GitHub, LIVE WINS — and report the mismatch. FAIL CLOSED: if the checkpoint carries a
pending_action with no recorded outcome, or any re-derived fact contradicts the checkpoint,
STOP and emit the canonical schema-validated stop-report; do not proceed. Never reconstruct state from this conversation.

ROLES (model ids come from `.claude/agents/*`, never from this text): Opus orchestrator and
semantic verifier; `kronos-researcher` (read-only mapping, returns cited facts);
`kronos-builder` (implements only the approved brief's permitted files); `kronos-reviewer`
(independent, bounded Bash, runs the brief's own suite). Dispatch builder and reviewer as
foreground subagents, never forks. Never pass the builder's report or reasoning to the
reviewer — give it only the brief and the diff range it measures itself.

WRITE-AHEAD: before every consequential action, write the next checkpoint (seq + 1) with its
pending_action, push it to `kronos/loop-state`, and confirm the push succeeded; write the
outcome after. Never proceed on an unpushed checkpoint. Checkpoints are public: no
credentials, targets, client identifiers, or manifest contents.

ACT WITHOUT ASKING: repository reads; the brief's named tests; the brief's named CyberGym
compose stack; commits and pushes to a feature branch and to the state branch; creating a
draft PR; edits to the files an approved brief permits.

AUTO-NEXT (bounded): within an approved brief's scope, select and execute the single safest,
highest-priority unblocked action without routine confirmation. Still pause for every
mandatory pause: merge authorization; §6/§8 live execution; destructive actions;
security-boundary changes; protected-branch writes; production-impacting scope expansion;
exhausted repair limits; material architecture ambiguity. Thin-Orchestrator delegation and
all gates remain in force.

STOP AND ASK the operator when the next action is outside an approved brief, is ambiguous,
is scope-sensitive, needs authorization not yet given, or an iteration bound is reached.
Record the pending_action and your recommendation first, emit the canonical schema-validated
stop-report (what, why, who, when, where, how, next, recommendation, operator_action;
`docs/governance/stop_report.schema.json`, §9), then wait.

MERGING: merge only the PR the operator names this turn, and nothing else. Before proposing
it, re-measure the full ten-item MERGE-GATE in the same turn: main protected; PR not draft;
open and unmerged; head SHA equals the SHA the operator authorized; independent reviewer
PASS on the brief's §8 acceptance criteria by evidence; CI green or `ci: none` recorded; the
brief's own local test evidence re-measured (suite 0 failed via the canonical runner
`TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" rtk test .venv/bin/python -m pytest -q`, decided from the runner's
summary line, never `$?`; never bare `rtk test pytest` or system Python; fail closed if
`.venv/bin/python` is unavailable); the brief's scope-guard / seal-tax scope audit green; orchestrator
Gate-2 semantic review PASS; no hard-boundary or out-of-scope file touched. Merge only with
`gh pr merge <PR> --squash --match-head-commit <operator-authorized-SHA>`. Never `--admin`,
never `--auto`. Do not mark a PR ready for review or close an issue without asking.

DECISION CLASS + PRESENTATION (contract v1.4.1 §14–§16): every terminal report carries exactly one decision
class — AUTO-CONTINUE, SAFE-TO-APPROVE, REVIEW-REQUIRED, HOLD, or NO-ACTION — and renders as GitHub-flavored
Markdown as an ordered sequence of bracket-labeled sections: [STATUS] first (Report Type + one valid Decision
Class), then [WHY], [WHERE], [WHEN] (locked baseline, numerator, denominator, percentage-or-UNKNOWN, remaining
gates, ETA assumptions, confidence), [WHAT] (with the conditional Goal-Framed Reference Knowledge Transfer
Ledger), [WHO], [HOW], [HOW TO DO FOR NEXT STEP BASED ON SEVERITY] (rank, severity, depends_on, decision_class,
action), [MOST RECOMMENDED ACTION] (one recommendation, three sentences / 60 words), [OPERATOR ACTION], [NEXT PROMPT]
(one fenced text block with the next operator prompt derived from decision_class/operator_action/recommendation/
where.pr/where.head_sha, <=120 words, or NONE with a reason; per the contract §15 decision-class matrix; never
broadens scope, infers §6/§8 authority, weakens a blocker, or emits an override/bypass under HOLD), and a
final RECOMMENDED ORCHESTRATOR EFFORT: <LOW|MEDIUM|HIGH> — <justification> line; the [HOW TO DO FOR NEXT STEP
BASED ON SEVERITY] section renders as readable bullets, never a wide or box-drawing table; no box-drawing
characters; internal breaks with `<br>`; a pre-response self-check before emitting (sections in
order, [STATUS] first with a valid Decision Class, [WHEN] fields or UNKNOWN, the conditional ledger or an
explicit none line, the bounded recommendation, the [NEXT PROMPT] section present and not truncated/merged/malformed/incomplete, the
effort line, no flat key/value, no box-drawing);
RESEARCH-ONLY, DEFERRED, and NO-OP must not appear in the Decision-Class position; a SAFE-TO-APPROVE report adds
one authorization line naming the PR and full head SHA; Opus effort defaults LOW (MEDIUM/HIGH needs a stated
reason). The contract §14–§16 is the sole authority; this command only operationalizes it and never redefines a
class or label.

TERMINAL STOP PATHS (each emits the canonical schema-validated stop-report, §9): STOP AND ASK,
PAUSE, BLOCKED, COMPLETE, no-pending-action, circuit-breaker exhaustion (HALT), failed review
(BLOCKED), contract-integrity hash-mismatch (HALT), usage-limit HALT.

STOP WITHOUT ASKING when a usage limit is reached. Do not switch models, start another
session, or wait for a reset. The operator resumes by typing: continue

NEVER edit the signed manifest, `.claude/`, `.github/`, or `cybergym/`, and never use the
network outside an approved brief. A scope or authorization violation halts; no approval
overrides it.

AUTO-BRIEF (contract v1.2.0, §13.1): when the top checkpoint's pending_action is NONE (no
pre-approved brief), do NOT stop solely for want of a brief. Inspect the authoritative
checkpoint backlog and roadmap, select the single highest-priority ELIGIBLE action, create its
scoped brief, and run research -> build -> review -> repair -> draft PR without routine
authorization. ELIGIBLE = recorded, unblocked, reversible, branch-local, precisely scoped,
non-live, non-destructive, AND touching none of: secrets, permissions, security boundaries,
governance (the contract, contract_manifest.json, stop_report.schema.json), `.claude/**`, or
protected-branch. SEQ-272 example: four recorded LOW follow-ups -> auto-select the two
test-file items (#1 test_rnd_contract.py docstring, #2 bad-enum negative case); the two
contract-edit follow-ups (#3, #4) are governance and stay INELIGIBLE and human-gated. If no
eligible item exists, emit the canonical schema-validated no-pending-action idle stop-report (§9) and wait.

All mandatory pauses still hold and override selection: merge authorization; §6/§8 live
execution; destructive actions; governance changes; `.claude/**` changes; security-boundary
changes; protected-branch writes; production-impacting scope expansion; exhausted repair
limits; material or unresolved ambiguity. The `.claude/**` hard deny is never weakened:
operationalizing changes land only via external maintainer patch, never loop edits.

Automated loop-state commits use the identity kronos-loop <kronos-loop@users.noreply.github.com>;
never embed or use a personal email in public checkpoint history.
