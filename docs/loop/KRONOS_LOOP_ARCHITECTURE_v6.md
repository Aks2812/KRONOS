# KRONOS_LOOP_ARCHITECTURE.md — v6

**Status:** revised architecture + merge-authorization model + setup decisions.
**Nothing merged. No repository settings, CI, code, or files changed. Implementation not started.**
**Supersedes:** v5. **Date:** 2026-10-17.

**[VERIFIED]** = measured today or read from official documentation. **[ASSUMED]** = my inference.

---

## 0. Recheck — 2026-10-17T13:32:02Z

| Fact | Measured | Status |
|---|---|---|
| PR #13 `state` / `draft` / `merged` | `open` / **`true`** / `false` | **BLOCKER — still a draft** |
| PR #13 head | `d2ad51e611927525780b9069db2bc16b0a7209b2` | unchanged since 06:03Z |
| PR #13 `mergeable_state` | `clean` | GitHub would accept a merge today |
| PR #13 reviews | **none** | **BLOCKER — no independent review recorded** |
| PR #13 CI checks | **0 check-runs, 0 statuses, 0 workflows in repo** | **BLOCKER — no CI exists** |
| PR #13 author | **`Aks2812`** | see §2.4 — this is structurally important |
| `main` | **`protected: false`**, no rulesets | **BLOCKER — unprotected** |
| `main` HEAD | `dcbdba950a45253f2c417b0c95c6ccb6930e9221` | — |
| Issue #2 | `open` | **BLOCKER — FORK-2 not closed** |
| Repository | `private: false`, owner `Aks2812` | checkpoints would be public |

**All five blockers stand. This is not approval to merge, and nothing was merged.** FORK-2 remains
incomplete; S3 stays blocked; CyberGym only — no live-client target, no Beast mode.

### `--match-head-commit` verified

```
--match-head-commit SHA   Commit SHA that the pull request head must match to allow merge
--admin                   Use administrator privileges to merge a pull request that does not meet requirements
--auto                    Automatically merge only after necessary requirements are met
```

**`--match-head-commit` is enforced by GitHub, not by the client.** If the head has moved, the merge
is rejected server-side. That makes it the mechanism for "only at the exact head SHA I authorize" —
not a rule that can be phrased around. `--admin` and `--auto` are the two flags that would defeat the
model, and both are denied in §3.3.

---

## 1. What changed from v5

| # | Change |
|---|---|
| **F-1** | **The loop may merge — PR #13 only, at one authorized head SHA.** v5's blanket `deny` on `gh pr merge` is replaced by the authorization model in §2. |
| **F-2** | **`MERGE-GATE`** — ten measurable prerequisites (§3.1), all re-measured at merge time, not inherited from an earlier check. |
| **F-3** | **A `merge_authorization` record in the checkpoint**, naming PR number and exact head SHA, void the moment either changes. |
| **F-4** | **I am correcting my own v5 prerequisite.** v5 said protect `main` with "require one approving review". **[VERIFIED]** the PR author is `Aks2812`, the repo owner — GitHub does not permit approving your own PR, so a required-approval rule would make PR #13 unmergeable except via `--admin`, which this design denies. §2.4 has the corrected recommendation. |
| **F-5** | **`--admin` and `--auto` explicitly denied** — the two flags that would bypass protection or merge outside your authorization window. |
| **F-6** | **The API merge route closed** — `gh api …/pulls/*/merge` denied, so the REST path can't route around `gh pr merge`. |
| **F-7** | **Consolidated setup decisions** (§5). |

Everything else from v5 stands unchanged: parent in `default` permission mode; models pinned as full
IDs `claude-opus-5` / `claude-sonnet-5`; autonomous checkpoint pushes, named tests, draft-PR creation
and in-brief edits; `PAUSE-LIMIT` and `PAUSE-DECISION` as the only two pauses; `HALT-SCOPE`
non-overridable; hooks supplemental throughout.

---

## 2. The merge-authorization model

### 2.1 The constraint that shapes it

**[VERIFIED]** permission rules are evaluated **deny → ask → allow, first match wins**, and *"an allow
rule can't carve an exception out of a deny rule."*

So a blanket `deny: Bash(gh pr merge *)` **cannot** coexist with a narrow allow for one authorized
merge — the deny would swallow it. Likewise `ask: Bash(gh pr merge *)` would swallow a narrow allow,
because ask also outranks allow. The grant has to be built so the authorized command and the
prohibited ones never collide in the same rule shape.

### 2.2 Recommended construction — the prompt is the authorization

```jsonc
"deny": [
  "Bash(gh pr merge --admin *)",      // never bypass protection
  "Bash(gh pr merge --auto *)",       // never merge later, outside the authorization moment
  "Bash(gh pr merge --disable-auto *)",
  "Bash(gh api *pulls/*/merge*)"      // close the REST route
],
"ask": [
  "Bash(gh pr merge *)"               // every merge surfaces, with its full command text
]
```

The loop composes exactly one command and you see it in full before it runs:

```
gh pr merge 13 --squash --match-head-commit d2ad51e611927525780b9069db2bc16b0a7209b2
```

Your approval at that prompt **is** the authorization of that specific merge, of that specific PR, at
that specific SHA. None of the three denied flags can appear in it — they match a deny rule first.

**Answer "Yes", never "Yes, and don't ask again."** **[VERIFIED]** the dialog *"writes the
space-separated form when you select 'Yes, and don't ask again' for a command prefix"*, so a
mis-click could persist a prefix rule. The blast radius is bounded — any rule derived from that string
still contains the SHA, and `--match-head-commit` is server-enforced, so the worst case is re-running
an already-completed merge of the same commit, which is a no-op — but the habit matters.

### 2.3 Alternative construction — exact-match allow (silent)

If you would rather the authorized merge run without a prompt:

```jsonc
"allow": [
  "Bash(gh pr merge 13 --squash --match-head-commit d2ad51e611927525780b9069db2bc16b0a7209b2)"
]
```

**[VERIFIED]** *"A rule with no `*` matches one exact command."* The §2.2 deny rules still apply and
do not collide with this string. Every other merge form matches no rule and therefore prompts.

The authorization act here is **you editing `.claude/settings.json` by hand** — and because
`Edit(./.claude/**)` is in the deny set, **the loop cannot write that rule itself**. That is the
property that makes this safe, and it leaves the authorization in git history rather than only in a
transcript.

**Recommendation: §2.2.** It needs no settings edit, shows you the SHA at the moment of decision, and
the transcript records it. §2.3 is Decision 1 if you prefer the stronger paper trail.

### 2.4 Correcting my v5 protection recommendation

v5 told you to protect `main` with *"require one approving review."* **[VERIFIED]** today: PR #13's
author is `Aks2812`, the same account that owns the repository. GitHub does not allow you to approve
your own pull request. With a single-maintainer repo, a required-approval rule makes **every** PR
unmergeable except through `--admin` — the one flag this design denies, and the one that bypasses the
protection you just added.

**Corrected recommendation for `main`:**

| Setting | Value | Why |
|---|---|---|
| Require a pull request before merging | **on** | stops direct pushes to `main`; the real risk |
| Require approvals | **off** | unsatisfiable with one account; would force `--admin` |
| Block force-pushes | **on** | — |
| Block deletions | **on** | — |
| Include administrators | **on** | binds you and the loop alike |

The review requirement is then met where it actually belongs: **the independent reviewer subagent's
PASS table, recorded in the checkpoint, plus your explicit merge authorization.** A GitHub approval
you cannot give is not a control; a reviewer that never saw the builder's reasoning is.

If you later add a collaborator or a review bot, turn required approvals on and add it to `MERGE-GATE`
as prerequisite 5b.

### 2.5 The `merge_authorization` record

Written to the checkpoint by the parent **only after you grant it**, never inferred:

```yaml
merge_authorization:
  pr: 13
  head_sha: d2ad51e611927525780b9069db2bc16b0a7209b2
  strategy: squash
  granted_at: <timestamp>
  granted_by: human
  gate_evidence: <seq of the checkpoint holding the passing MERGE-GATE>
```

**The grant is void** if the PR head changes, if the PR number differs, if any `MERGE-GATE`
prerequisite re-check fails, or if it is not used in the same loop turn it was granted in. A void
grant is a `PAUSE-DECISION`, not a retry.

---

## 3. `MERGE-GATE`

### 3.1 Prerequisites — all ten, all re-measured at merge time

A check that passed an hour ago does not count. The loop runs every one of these in the turn it
intends to merge.

| # | Prerequisite | Measured by | Today |
|---|---|---|---|
| 1 | `main` is protected per §2.4 | `gh api repos/Aks2812/KRONOS/branches/main --jq .protected` → `true` | **FAIL** (`false`) |
| 2 | PR #13 is **not a draft** | `gh api …/pulls/13 --jq .draft` → `false` | **FAIL** (`true`) |
| 3 | PR #13 open and unmerged | `--jq '{state,merged}'` → `open`, `false` | pass |
| 4 | Head SHA **equals the authorized SHA** | `--jq .head.sha` vs `merge_authorization.head_sha` | pass at `d2ad51e` |
| 5 | **Independent review complete** — every `SPEC_BRIEF10.3` §6 criterion marked PASS with evidence by `kronos-reviewer`, recorded in the checkpoint's `self_check`, produced from the diff and the brief only | checkpoint `self_check` | **FAIL** (not yet run) |
| 5b | *(only once a second reviewer account exists)* a GitHub approving review | `…/pulls/13/reviews` | n/a — §2.4 |
| 6 | **CI, if any exists** — every required check `conclusion: success`. If no workflow exists, the checkpoint must record `ci: none; local evidence only` as an explicit acknowledgement | `…/commits/<sha>/check-runs` | **0 checks, 0 workflows** — acknowledge or add CI (Decision 3) |
| 7 | **Local test evidence** in the checkpoint: suite totals against the `591 passed / 1 skipped` and `17 passed` baselines; the three `_SCOPE_GUARD_SHA256` pins re-pinned with guards intact; the verbatim `X-SCORE:` line with exit code and the host it ran on | checkpoint `tests` | **FAIL** (`last_run: null`) |
| 8 | `mergeable_state` is `clean`; head is **not** already an ancestor of `main` | `--jq .mergeable_state`; `git merge-base --is-ancestor` | pass |
| 9 | `merge_authorization` present, matching PR and SHA, granted this turn | checkpoint | **FAIL** (not granted) |
| 10 | Clean tree; no unexpected remote branches beyond those recorded | `git status --porcelain`; `git branch -r --no-merged origin/main` | **five stale branches** to reconcile |

**Any FAIL → stop and ask. Never merge on a partial gate.** Today **six** of the ten fail.

### 3.2 If the head moves

If `head.sha` ≠ `merge_authorization.head_sha`, the loop stops and asks — and even if it did not,
`--match-head-commit` would make GitHub reject the merge. Two independent stops, one of them
server-side.

### 3.3 Every other merge is prohibited

| Prohibition | Enforcement |
|---|---|
| Any PR other than the one in `merge_authorization` | the loop is instructed to merge only that PR; the hook denies a `gh pr merge` whose number differs or when no authorization is recorded *(supplemental)*; the `ask` rule surfaces it to you *(primary)* |
| Administrator bypass | `Bash(gh pr merge --admin *)` in **deny** |
| Auto-merge queued for later | `Bash(gh pr merge --auto *)` in **deny** — this one matters most, because it would merge **outside** the moment you authorized |
| REST merge endpoint | `Bash(gh api *pulls/*/merge*)` in **deny** |
| Direct push to `main` | **branch protection** (server-side) — the only control no client-side phrasing can route around |

**[VERIFIED]** a Bash rule *"isn't a security boundary around the program"* — `Bash(git push *)` in
deny stops `git push origin main` but not `git -C . push origin main`. Every command-text rule above
is advisory. Prerequisite 1 is what makes the merge path real.

---

## 4. Unchanged: autonomy, pauses, halts, state

**Autonomous under an approved brief, no prompt:** repository reads; built-in read-only git; the
brief's named tests (`pytest`, `python -I`); the CyberGym compose stack the brief names;
`sha256sum`; `git add` / `git commit`; **checkpoint pushes**
(`Bash(git push origin *:refs/heads/kronos/loop-state)`) and **feature-branch pushes**
(`Bash(git push origin HEAD:refs/heads/claude/*)`), allowed by explicit refspec so no general push
grant exists; **draft-PR creation** (`Bash(gh pr create --draft *)`); `gh api` reads; and edits to
files the approved brief permits, allowed by the PreToolUse hook.

**`PAUSE-DECISION`:** out-of-brief edits; a contradictory brief or a brief whose `sha256` doesn't
match; `gh pr ready`; `gh issue close`; any push form other than the two above; a new or amended
brief; an iteration bound reached (RESEARCH 3 / BUILD 3 / REVIEW 2); **and now, the merge grant
itself**.

**`PAUSE-LIMIT`:** a usage limit stops the loop — no model switch, no second session, no waiting for a
reset. Set `autoContinueAtUsageLimit` to `false`. Resume with `continue`.

**`HALT-SCOPE`, no override:** any write to `src/kronos/manifest.py`; re-signing a manifest; a target
outside the signed scope; lifting `live_target_gate` in-loop; any fail-closed path in `scope_guard`.

**State:** orphan branch `kronos/loop-state`, write-ahead before every consequential action, push
confirmed before the action runs, five verification checks on resume. **Public** — commit SHAs, PR and
issue numbers, brief hashes, test counts, verdicts, gate names and finding IDs are fine; credentials,
live-target identifiers, manifest contents and engagement specifics never.

**Hooks remain supplemental.** If the hook were entirely disabled, nothing in the security boundary
moves: merges still need your authorization at the prompt, `--admin` and `--auto` stay denied, the
manifest and `.claude/` stay denied, the reviewer stays read-only at the `tools:` layer, and
`scope_guard` still fails closed. Only brief discipline degrades — caught by diff review before
anything can merge.

---

## 5. Remaining setup decisions, before the loop starts

Grouped by whether they block the pilot.

### 5.1 Blocking — the pilot cannot start until these are settled

| # | Decision | Note |
|---|---|---|
| **1** | **Merge construction** — §2.2 `ask` (recommended) or §2.3 exact-match allow? | determines whether the authorized merge prompts |
| **2** | **`main` protection shape** — confirm §2.4: require a PR, **no** required approvals, block force-push and deletion, include administrators. | required-approvals is unsatisfiable with one account |
| **3** | **CI** — add a minimal workflow running the suite on PRs, or proceed with `ci: none; local evidence only` recorded in each checkpoint? | there is no workflow at all today |
| **4** | **State branch visibility** — public `kronos/loop-state` in this repo, or a separate private state repository? | the repo is public |
| **5** | **Model availability** — `/model` must confirm `claude-opus-5` and `claude-sonnet-5` are selectable. If not, name the substitutes. | aliases give 5.5, not 5 |
| **6** | **Claude Code version** — `claude --version`. Gates 2.1.234 auto-continue and 2.1.257 behaviours. | only you can run this |

### 5.2 Non-blocking — defaults applied unless you say otherwise

| # | Decision | My default |
|---|---|---|
| 7 | Merge strategy | `--squash` |
| 8 | Delete the branch on merge | no — keep it until issue #2 is closed with the merge-commit link |
| 9 | `gh pr ready` | prompts (one per brief) |
| 10 | `git commit` | prompts once per session, then silent |
| 11 | Iteration bounds | RESEARCH 3 / BUILD 3 / REVIEW 2 |
| 12 | Stale branches | reconcile and delete the five unmerged ones — but **what is `claude/sweet-gauss-x4l1wi`?** |
| 13 | Kickoff durability | move §6 into `.claude/commands/kronos-continue.md` plus a `CLAUDE.md` line, so compaction can't lose the contract |

---

## 6. Kickoff — merge clause updated

Paste into `claude -n kronos-loop --model claude-opus-5`, run in `~/KRONOS`, after §5.1 is settled and
the Phase-0 checks pass.

```
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

STAGE: FORK-2. Six of the ten MERGE-GATE prerequisites currently fail. First action:
independently review PR #13 at head d2ad51e against SPEC_BRIEF10.3 section 6, returning
PASS/FAIL per criterion with evidence. Then report which prerequisites remain unmet and
stop. Do not merge.
```

Resume after a usage limit:

```
continue
```

---

## 7. Sources

**Claude Code documentation**, fetched 2026-10-17:
[Permissions](https://code.claude.com/docs/en/permissions.md) ·
[Hooks](https://code.claude.com/docs/en/hooks?frame=0) ·
[Subagents](https://code.claude.com/docs/en/subagents) ·
[Sessions](https://code.claude.com/docs/en/sessions) ·
[CLI reference](https://code.claude.com/docs/en/cli) ·
[Model configuration](https://code.claude.com/docs/en/model-config.md) ·
[Checkpointing](https://code.claude.com/docs/en/checkpointing) ·
[Interactive mode](https://code.claude.com/docs/en/interactive-mode.md) ·
[Agent teams](https://code.claude.com/docs/en/agent-teams.md) ·
[Costs](https://code.claude.com/docs/en/costs.md)

**Repository evidence**, GitHub API, 2026-10-17T13:32:02Z — PR #13 `open`, `draft: true`,
`merged: false`, `mergeable_state: clean`, head `d2ad51e611927525780b9069db2bc16b0a7209b2`, **author
`Aks2812`**, **0 reviews** · head check-runs `total_count: 0`, combined status `pending`/0 ·
`/actions/workflows` `total_count: 0` · `/branches/main` **`protected: false`**, `/rulesets` empty ·
issue #2 `open` · repository `private: false`, owner `Aks2812`.

**`gh` evidence**, `gh pr merge --help` — `--match-head-commit SHA` ("Commit SHA that the pull request
head must match to allow merge"), `--admin`, `--auto`, `--squash`, `--delete-branch`.

**Unverified:** Claude Code version on Kali; whether `claude-opus-5` and `claude-sonnet-5` are
selectable on your account; whether offensive MCP servers are visible to a KRONOS session. MCP service
isolation left intact — not inspected, not weakened.
