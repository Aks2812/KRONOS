# Source migration map

Purpose: prove that no still-binding rule was silently dropped when consolidating R&D governance into `docs/governance/KRONOS_RND_CONTRACT.md`. Every source rule is listed; each still-binding rule names the contract section where it now lives. Superseded rows name the superseding rule_id.

The v7, CE and RAILS files (`docs/loop/KRONOS_LOOP_ARCHITECTURE_v7.md`, `docs/loop/CE.md`, `.claude/RAILS.md`) are preserved unchanged as provenance (RAILS.md gains only a pointer note to the contract).

| rule_id | category | rule | source(file:line) | still_binding | consolidated_in(contract §) |
|---|---|---|---|---|---|
| R001 | roles-and-models | v7 step table (Opus init / Sonnet researcher / Sonnet builder / Haiku Gate1 / Opus Gate2) | v7.md:16-22 | superseded (by R002) | superseded by R002 |
| R002 | roles-and-models | Opus orchestrator (steps 1&5); Sonnet researcher claude-sonnet-5 (step 2, returns findings not files); builder (step 3; live pin claude-sonnet-5-5); Haiku reviewer claude-haiku-5-5 (step 4, bounded Bash) | v7.md:168-174 | yes | §2 |
| R003 | delegation | Zero context between steps 2,3,4; handoff is files on disk not conversation | v7.md:24 | yes | §1 |
| R004 | circuit-breaker | max 3 attempts then HALT and escalate to maintainer | v7.md:32 | yes | §4 |
| R005 | circuit-breaker | 3-attempt Haiku-builder cycle is BUILD bound; exhausting it is a PAUSE-DECISION not a retry | v7.md:38-40 | yes | §4 |
| R006 | delegation | expensive model never reads raw terminal errors | v7.md:36 | yes | §1 |
| R007 | section6 | §8 acceptance criteria, §6 live-use gate; never conflated; section number named in every dispatch | v7.md:106-107 | yes | §6 |
| R008 | section6 | CyberGym only, no live targets | v7.md:108 | yes | §6 |
| R009 | section6 | do not enable live-target work or expand scope | CE.md:30 | yes | §6 |
| R010 | auth-boundaries | Never edit manifest.py, .claude/, .github/ or cybergym/ | v7.md:109 | yes | §5 |
| R011 | auth-boundaries | NEVER edit signed manifest, .claude/, .github/, cybergym/; never use network outside approved brief | kronos-continue.md:55-56 | yes | §5 |
| R012 | auth-boundaries | Do not modify KRONOS product code, signed scope data, or external repo settings | CE.md:34 | yes | §5 |
| R013 | merge-gate | Ten-item MERGE-GATE (main protected; PR not draft; open and unmerged; head SHA equals authorized SHA; independent reviewer PASS on brief §8 AC; CI green or `ci: none`; local test evidence re-measured; scope-guard/seal-tax audit green; orchestrator Gate-2 review PASS; no hard-boundary/out-of-scope file touched) | kronos-continue.md:43-50 | yes | §7 |
| R014 | merge-gate | Merge only `gh pr merge <PR> --squash --match-head-commit <operator-authorized-SHA>`; never --admin, never --auto | kronos-continue.md:49-50 | yes | §7 |
| R015 | merge-gate | Do not mark a PR ready or close an issue without asking | kronos-continue.md:50 | yes | §7 |
| R016 | pause | prose silence is a PAUSE-DECISION; expected values derive from brief prose never observed behaviour | v7.md:107-108 | yes | §4 |
| R017 | pause | Excluded-first default-deny | v7.md:108 | yes | §4 |
| R018 | pause | STOP AND ASK when next action outside approved brief, ambiguous, scope-sensitive, needs authorization not yet given, or iteration bound reached; record pending_action + recommendation first | kronos-continue.md:38-39 | yes | §4 |
| R019 | pause | STOP WITHOUT ASKING at usage limit; do not switch models/start another session/wait for reset | kronos-continue.md:52-53 | yes | §4 |
| R020 | pause | Usage limit means stop, not switch models | v7.md:110 | yes | §4 |
| R021 | pause | FAIL CLOSED: checkpoint pending_action with no recorded outcome, or re-derived fact contradicts checkpoint: STOP and report | kronos-continue.md:18-20 | yes | §4 |
| R022 | pause/auth | A scope or authorization violation halts; no approval overrides it | kronos-continue.md:56-57 | yes | §4, §5 |
| R023 | write-ahead | Write-ahead checkpointing to kronos/loop-state before every consequential action | v7.md:105 | yes | §8 |
| R024 | write-ahead | write next checkpoint (seq+1) with pending_action, push, confirm, write outcome after; never proceed on unpushed checkpoint; checkpoints public | kronos-continue.md:29-32 | yes | §8 |
| R025 | stop-report | Five-item hand-up, mandatory on every pause/finish (extended by 9-field 5W+1H schema, superset) | v7.md:192-207 | yes | §9 |
| R026 | pause | Within approved scope, continue without asking routine confirmations | v7.md:211-212 | yes | §4 |
| R027 | auth | A recommendation or `continue` is never authorization to cross a human gate, expand scope, push, or merge | v7.md:213-214 | yes | §3 |
| R028 | auth | GATE-1 and GATE-2 are the maintainer's, neither produced nor unlocked by the loop | v7.md:214-215 | yes | §0, §3 |
| R029 | auth | Crossing a human gate requires explicit maintainer instruction naming what is authorized (merge: PR number + exact head SHA, ten-item MERGE-GATE re-measured same turn) | v7.md:215-217 | yes | §3 |
| R030 | gates/artifact | GATE-1 is maintainer approval of a brief; reviewer output is review-evidence.json not gate1.json | v7.md:154-159 | yes | §3 |
| R031 | roles/delegation | researcher must not be told to write files while read-only; prefer returning findings | v7.md:146-150; CE.md:18 | yes | §1, §2 |
| R032 | roles | reviewer may run only project-approved local tests; not read-only if it has Bash; not unrestricted shell | CE.md:18 | yes | §2 |
| R033 | roles/delegation | don't create an unused orchestrator subagent | CE.md:11; v7.md:161-164 | yes | §1 |
| R034 | gates | Every review finding becomes a test | v7.md:80-83 | yes | §11 |
| R035 | gates | Full-window file audit hard gate: `git diff --name-only <brief-base>..HEAD` asserts every path in §3 | v7.md:84-86 | yes | §11 |
| R036 | scope/seal | Explicit-path staging; never `git add -A` on a brief-scoped branch | v7.md:87-88 | yes | §11 |
| R037 | scope/seal | Totals refreshed last, as final edit after last suite run | v7.md:89-90 | yes | §11 |
| R038 | gates | Claims must be enforced or softened | v7.md:91-93 | yes | §11 |
| R039 | gates | maintainer is the remaining independent check; final step hands up measured evidence not conclusions | v7.md:94-97 | yes | §3 |
| R040 | gates | Escape hatch: one-off independent Opus review when orchestrator materially changed code it reviews or deliverable is a judgment; never a failure | v7.md:99-101 | yes | §2 |
| R041 | roles | Haiku reviewer independently reviews approved brief and diff, reports evidence + test results | v7.md:136-137; CE.md:14 | yes | §2 |
| R042 | scope/artifact | Durable checkpoint is docs/loop/PROGRESS.md; .claude/pipeline/ is per-iteration working state only | v7.md:176-178 | yes | §10 |
| R043 | delegation | Dispatch builder and reviewer as foreground subagents, never forks | kronos-continue.md:25-26 | yes | §1 |
| R044 | delegation | Never pass builder's report/reasoning to reviewer | kronos-continue.md:26-27 | yes | §1 |
| R045 | delegation | ACT WITHOUT ASKING list (reads; named tests; named CyberGym stack; feature/state branch commits+pushes; draft PR; permitted edits) | kronos-continue.md:34-36 | yes | §1 |
| R046 | artifact/precedence | Binding contract was v7 + CE on origin/kronos/loop-state; v7 superseded v6 role model only (now: this contract supersedes v7/CE as sole binding) | kronos-continue.md:6-10 | yes | §0, §10 |
| R047 | artifact/precedence | Where checkpoint disagrees with live Git/GitHub, LIVE WINS and report mismatch | kronos-continue.md:17-18 | yes | §10 |
| R048 | other | Headroom compression ~0.7% average, not a lever | v7.md:117-118 | yes | §1 |
| R049 | other | `rtk test` returns exit 0 on failure: read SUMMARY line never `$?` | v7.md:114-116 | yes | §1 |
| R050 | auth | gh pr merge --admin/--auto/--disable-auto nine deny entries; real boundary is `ask` + branch protection incl administrators | RAILS.md:9-29 | yes | §5 |
| R051 | auth | git push --force/--delete three-shape deny patterns | RAILS.md:31-36 | yes | §5 |
| R052 | auth | git push origin HEAD:refs/heads/claude/* removed from allow; feature-branch pushes fall to ask | RAILS.md:38-53 | yes | §5 |
| R053 | auth | git push origin *:refs/heads/kronos/loop-state stays in allow (anchored tail) | RAILS.md:55-58 | yes | §5 |
| R054 | auth | GET-only allow narrowing for the GitHub API; brief-scope.sh denies mutating calls, fails closed on unparseable | RAILS.md:61-96 | yes | §5 |
| R055 | artifact/precedence | repo .claude/ sole canonical/executable source, no mirror; check_rails_drift.sh | RAILS.md:102-115 | yes | §10 |
| R056 | artifact | three agent defs only in .claude/agents/; no orchestrator agent file | agents/*.md:1-8 | yes | §2 |
| R057 | roles | Researcher tools Read,Glob,Grep; disallowed Write,Edit,Bash,WebFetch,WebSearch | kronos-researcher.md:5-7 | yes | §2 |
| R058 | roles | Builder tools Read,Edit,Write,Bash,Glob,Grep; disallowed WebFetch,WebSearch | kronos-builder.md:5-6 | yes | §2 |
| R059 | roles | Reviewer tools Read,Bash,Glob,Grep; disallowed Write,Edit,WebFetch,WebSearch | kronos-reviewer.md:5-6 | yes | §2 |
| R060 | scope/seal | Builder edits only dispatch-authorized files else NEEDS-DECISION | kronos-builder.md:15-17 | yes | §2, §11 |
| R061 | scope/seal | Builder never `git add -A`; explicit paths only | kronos-builder.md:22-23 | yes | §2, §11 |
| R062 | gates | Builder decides pass/fail from runner's summary line not exit code | kronos-builder.md:26-27 | yes | §2 |
| R063 | auth | Builder does not open/modify/mark-ready/comment/merge any PR unless dispatch says so | kronos-builder.md:24-25 | yes | §2 |
| R064 | section6 | Builder: no live targets or network beyond instructed | kronos-builder.md:31-32 | yes | §2, §6 |
| R065 | gates | Reviewer Bash bounded (test command, git diff/log/show/archive, sha256sum, grep, wc, reads); no checkout/reset/switch/install/network/PR actions | kronos-reviewer.md:22-30 | yes | §2 |
| R066 | gates | Reviewer never rounds UNVERIFIABLE up to PASS; assertion is not evidence | kronos-reviewer.md:34-36 | yes | §2 |
| R067 | scope/seal | Reviewer audits full file window, confirms every changed path authorized | kronos-reviewer.md:40-42 | yes | §2, §11 |
| R068 | gates | Reviewer isolated from builder's report/reasoning | kronos-reviewer.md:18-20 | yes | §2 |
| R069 | other | Researcher: facts only, no conclusions/recommendations/summaries of intent | kronos-researcher.md:29-30 | yes | §2 |
