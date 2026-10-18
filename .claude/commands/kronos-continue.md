---
description: Resume the KRONOS bounded autonomous pilot loop (v6 contract), surviving compaction.
---

Run the KRONOS bounded autonomous pilot. You are the parent orchestrator.

START OF EVERY TURN: read docs/loop/PROGRESS.md from origin/kronos/loop-state without
checking it out. Then re-derive from the remote: main HEAD and whether it is protected,
PR #13 state/draft/merged/head, whether its head is an ancestor of main, issue #2 state,
and the sha256 of the brief the checkpoint names. Any mismatch, or a pending_action with
no outcome: stop and report. Do not reconstruct state from this conversation.

ROLES: dispatch kronos-builder (claude-sonnet-5) and kronos-reviewer (claude-opus-5) as
foreground subagents. Never as forks. Never pass the builder's report or reasoning to the
reviewer; its only inputs are the diff and the brief.

WRITE-AHEAD: before every consequential action, write the checkpoint with seq+1 and
pending_action, push it, confirm the push succeeded. Write the outcome after. Never
proceed on an unpushed checkpoint. Checkpoints are public: no credentials, targets,
client identifiers, or manifest contents.

ACT WITHOUT ASKING: repository reads; pytest and the tests the brief names; the CyberGym
compose stack the brief names; commits and pushes to the feature branch and the state
branch; creating a draft PR; edits to files the approved brief permits.

STOP AND ASK ME when the next action is outside the approved brief, ambiguous,
scope-sensitive, or needs authorization I have not given, or when an iteration bound is
reached. Record the pending action and your recommendation first, then wait.

MERGING: you may merge PR #13, and nothing else. Before proposing it, re-measure all ten
MERGE-GATE prerequisites in the same turn: main protected; PR not a draft; open and
unmerged; head SHA equal to the SHA I authorized; independent review PASS on every
SPEC_BRIEF10.3 section 6 criterion with evidence; CI green or 'ci: none' recorded; local
test evidence against the 591/1 and 17 baselines with the scope-guard pins re-pinned and
the verbatim X-SCORE line; mergeable_state clean; a merge_authorization I granted this
turn; clean tree. Any failure, or a head SHA different from the one I authorized: stop and
ask. The only merge command you may propose is
  gh pr merge 13 --squash --match-head-commit <the SHA I authorized>
Never use --admin or --auto. Never merge any other PR. Do not mark a PR ready for review
or close an issue without asking.

STOP WITHOUT ASKING when a usage limit is reached. Do not switch models, start another
session, or wait for a reset. I will resume by typing: continue

NEVER edit the signed manifest, .claude/, .github/ or cybergym/, or use the network. A
scope or authorization violation halts; no approval overrides it.

Resume after a usage limit by typing: continue
