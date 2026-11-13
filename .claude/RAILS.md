# RAILS.md — why `.claude/settings.json` is shaped the way it is

> These rails operationalize docs/governance/KRONOS_RND_CONTRACT.md (canonical, sole binding R&D governance); RAILS.md is enforcement implementation, not an independent authority.

`settings.json` is strict JSON: a `//` comment or a trailing comma is a syntax error, and
Claude Code reports the file as a Settings Error at the next start — whose dialog offers
"fix the file with Claude's help, exit, or **continue without the broken settings**," one
keystroke from running with no rails at all. So this file, not the settings file itself,
carries every explanation. Keyed by rule, below.

## `gh pr merge --admin / --auto / --disable-auto` (nine deny entries, three shapes each)

Bash permission rules are literal string-prefix / fixed-position matches, not argv-aware
parsing — a flag's position in the command line matters to the pattern even though `gh`
itself accepts flags in any position. A single wildcard pattern only catches one argument
order; without all three shapes (flag-first, flag-last, flag-middle), `gh pr merge 13
--admin` slips past a pattern written only as `gh pr merge --admin *`. Same reasoning for
`--auto` and `--disable-auto`.

These flag-position denies are **defence in depth, not the real boundary**, and they are
inherently incomplete — any Bash permission pattern can in principle be defeated by an
argument order, alias, or shell-metacharacter form nobody enumerated. The controls that
actually hold the line are:

- the `ask` rule on `Bash(gh pr merge *)`, which surfaces the exact, full command text
  for a human decision every time, regardless of which deny pattern did or didn't match
  first; and
- GitHub branch protection on `main` with "include administrators" turned on
  (server-side, done by the human, not the loop) — the one control no client-side Bash
  pattern can route around, because `--admin`'s only purpose is to bypass branch
  protection, and there is nothing to bypass once it's on.

## `git push --force / --delete` (three shapes each, same reasoning)

Same flag-position gap as above. `git push origin main --force` (flag at the end)
matches none of `Bash(git push --force *)` alone; the three shapes
(`--force *`, `* --force`, `* --force *`) are needed so the flag is caught regardless of
where it lands in the argument list. Same three shapes for `--delete`.

## Why `git push origin HEAD:refs/heads/claude/*` is **not** in `allow`

It was in an earlier draft of this file and was removed. A `*` in a Bash rule matches any
text, **including spaces** — so the wildcard on `claude/*` absorbs `" --force"` whole, the
allow matches `git push origin HEAD:refs/heads/claude/foo --force`, and the `--force` deny
does not catch it, because that deny requires the literal prefix `"git push --force "`
(or, now, one of the three shapes above — none of which match either, since `--force`
here comes after a `:refs/...` argument, not immediately after `git push`). An over-broad
allow **fails open**; an under-broad deny only falls through to a prompt. That asymmetry is
why this allow is gone rather than patched: it would have been a silent force-push to the
branch carrying a feature branch's PR's head.

Feature-branch pushes were never on the no-prompt list in the first place — checkpoint
pushes to `kronos/loop-state`, the brief's named tests, and draft-PR creation were. A
feature-branch push now falls through to the default `ask`, and it prompts with the full
command text every time. That is the intended behavior, not a gap to close.

`git push origin *:refs/heads/kronos/loop-state` **stays** in `allow`. Its wildcard sits
mid-string with an exact, unwildcarded tail (`:refs/heads/kronos/loop-state`) — anything
appended after the refspec breaks the literal match and falls through to `ask` (or to the
`--force`/`--delete` denies, if the flag lands right after `git push`). The tail is what
anchors it; the `claude/*` rule had no tail to anchor against.

## `gh api` reads: narrowed allow list + method filter in the hook, not in the pattern

The generic `gh api repos/.../pulls *`, `...issues *`, `...commits *` allows were removed.
Two independent problems, not one:

1. **Too narrow for actual reads.** The pattern requires a literal space immediately after
   `pulls`/`issues`/`commits`. Path-nested reads like `.../pulls/13` or `.../issues/2` have
   a `/` there instead, so they never matched the old allow anyway — every real
   re-derivation call was already falling through to a prompt.
2. **Too broad for safety.** The bare-collection form (literally `.../pulls` or
   `.../issues` followed by a space) *did* match, with the trailing wildcard absorbing
   anything after — including `-X POST -f draft=false ...`, which creates a new,
   non-draft PR directly via the REST API, or a new issue, bypassing `gh pr create
   --draft` entirely without ever invoking a denied or ask-gated subcommand.

Pattern rules cannot express "GET only" — there is no wildcard shape that distinguishes a
read from a write at the same path. The allow list therefore contains only two GET-only
reads: `branches/main` and `commits/*/check-runs`. PR- and issue-scoped calls
(`pulls/...`, `issues/...`) are not in `allow` and fall through to the `ask` tier. On top of
that, `.claude/hooks/brief-scope.sh` inspects every `Bash` tool call containing a `gh api`
invocation (anywhere in the command, including inside `$(...)`, backticks, or `sh -c`
strings), regardless of agent type and regardless of which path matched, and denies it if it
is mutating by either route:

- field/body flags: `-f`, `-F`, `--field`, `--raw-field`, `--input` (spaced, `=`, or glued,
  e.g. `-ffoo=bar`, `--input=f.json`), since gh turns these into a POST; or
- a method flag naming anything other than GET/HEAD, in every form: `-XPOST`, `-X POST`,
  `--method POST`, `--method=POST` (likewise PATCH/PUT/DELETE).

It fails closed: an unparseable command, an unknown flag, or a missing/unrecognized method
token is denied. Only a plain read, or an explicit GET/HEAD with no field/input flags, passes
through to normal permissions. The command word is normalized statically (never executed or
expanded): any token whose `basename` is `gh` (`/usr/bin/gh`, `./gh`) is inspected as gh;
leading `NAME=value` assignments and `env`/`command` wrappers are skipped; and a dynamic
command word (`$G`, `${G}`, `$(...)`, backticks) followed by `api`, or `alias x=gh`, is denied
(fail closed). This is
**discipline, not a security boundary**: an API-created PR is still not a merge of #13, and
merging #13 remains gated on the `ask` rule plus `main`'s branch protection either way. The
hook closes the "quietly open a new PR/issue by a different door" gap; it does not and
cannot stand in for the merge-authorization model in the baseline doc.

## The repo `.claude/` is the sole canonical and executable source — no mirror

KRONOS commands and agents live only in this repository's `.claude/` directory. That copy is
both canonical and the one Claude Code executes; it is **not** mirrored into `~/.claude` or
any other scope. The earlier model kept a convenience mirror in `~/.claude` and had the drift
checker enforce repo→global parity — that is gone. A second copy in user scope (`~/.claude`)
or in an out-of-repo project scope does not help; it can silently shadow or compete with the
repo copy, so a duplicate is a hazard, not a convenience.

`scripts/check_rails_drift.sh` is now a **duplicate detector**, not a mirror check. It FAILS
(exit 1) if a repo canonical rail file is missing, or if it finds any `kronos-*.md` command or
agent in user scope (`~/.claude/commands`, `~/.claude/agents`) or in a second `.claude/` inside
the repo tree. It only reads; it never copies and never deletes. Reconcile by removing the
out-of-repo copy — never by copying the repo into a global scope.

## Terminal stop paths emit the canonical schema-validated stop-report; AUTO-NEXT is bounded

Every terminal path emits the canonical schema-validated 5W+1H stop-report (what, why, who, when, where, how,
next, recommendation, operator_action) validating against
`docs/governance/stop_report.schema.json` (contract §9): STOP AND ASK, PAUSE, BLOCKED,
COMPLETE, no-pending-action, circuit-breaker exhaustion (HALT), failed review (BLOCKED),
contract-integrity hash-mismatch (HALT), usage-limit HALT. A bare pending_action +
recommendation is insufficient.

AUTO-NEXT is bounded: within an approved brief's scope the loop executes the single safest,
highest-priority unblocked action without routine confirmation, but still pauses for merge
authorization, §6/§8 live execution, destructive actions, security-boundary changes,
protected-branch writes, production-impacting scope expansion, exhausted repair limits, and
material architecture ambiguity. Thin-Orchestrator delegation and all existing gates stand.

## Standing AUTO-BRIEF envelope (contract v1.2.0 §13.1)

When the top checkpoint's `pending_action` is NONE the loop no longer stops solely for want of a pre-approved brief: it selects the single highest-priority ELIGIBLE backlog/roadmap item, creates its scoped brief, and runs it end to end to a draft PR, still pausing before merge for GATE-2.

ELIGIBLE excludes governance (the contract, `contract_manifest.json`, `stop_report.schema.json`), `.claude/**`, secrets, permissions, security boundaries, and protected-branch writes. So this envelope can never auto-select a change to these rail files or to the contract — those stay human-gated and arrive only by external maintainer patch. The SEQ-272 four-item backlog therefore auto-selects only the two test-file follow-ups (#1 `test_rnd_contract.py` docstring, #2 bad-enum negative case); the two contract-edit follow-ups (#3, #4) are governance and stay ineligible.

The `.claude/**` hard deny is unchanged and is never weakened by AUTO-BRIEF. Every mandatory pause (merge authorization; §6/§8 live execution; destructive actions; governance changes; `.claude/**` changes; security-boundary changes; protected-branch writes; production-impacting scope expansion; exhausted repair limits; material or unresolved ambiguity) still holds and overrides selection.

Automated loop-state checkpoint commits MUST use the identity `kronos-loop <kronos-loop@users.noreply.github.com>`. A personal email must never appear in public checkpoint history.

## Canonical full-suite test runner — project `.venv`, disk-backed `TMPDIR`

The full suite runs ONLY through the project virtualenv interpreter:
`TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" rtk test .venv/bin/python -m pytest -q` (the focused form is the
same with the test path appended). `.venv/bin/python` carries this project's pinned
dependencies (e.g. `kuzu==0.11.3`, `pyproject.toml` / `requirements.txt`); the system
interpreter does not.

Prohibited: bare `rtk test pytest`, bare `pytest`, or any `/usr/bin/python` / system-Python
fallback. Those resolve to an interpreter without the project dependencies and surface as
spurious `ModuleNotFoundError` collection errors — a false red, never a real suite result.

Fail closed: if `.venv/bin/python` is missing or not runnable, STOP and emit the canonical schema-validated
stop-report (§9); never substitute the system interpreter, and never mask a missing dependency
with `--continue-on-collection-errors` or by ignoring collection errors.

pytest `tmp_path` scratch MUST point at a disk-backed `TMPDIR`, concretely
`${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp`, never the tmpfs `/tmp`: a full run writes
large per-test `kuzu` databases and will otherwise exhaust the volume mid-run and abort the
measurement. Create the directory first (`mkdir -p "${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp"`)
and verify it is disk-backed, not tmpfs — `findmnt -no FSTYPE --target "$TMPDIR"` (equivalently
`df -PT "$TMPDIR"`) MUST NOT report `tmpfs`. Fail closed: if that directory cannot be created, or
resolves to a tmpfs / non-disk-backed filesystem, STOP and emit the canonical schema-validated stop-report (§9);
never fall back to the tmpfs `/tmp`. Clear that scratch dir after the run.

## Decision classes & persistent terminal presentation (contract v1.4.1 §14–§16)

The contract is the sole semantic authority for the five decision classes (AUTO-CONTINUE, SAFE-TO-APPROVE,
REVIEW-REQUIRED, HOLD, NO-ACTION) and for the persistent GitHub-flavored-Markdown presentation of terminal
reports as an ordered sequence of bracket-labeled sections ([STATUS] first, then [WHY], [WHERE], [WHEN], [WHAT],
[WHO], [HOW], [HOW TO DO FOR NEXT STEP BASED ON SEVERITY], [MOST RECOMMENDED ACTION], [OPERATOR ACTION], [NEXT
PROMPT], and a final RECOMMENDED ORCHESTRATOR EFFORT line), read top to bottom; the [HOW TO DO FOR NEXT STEP
BASED ON SEVERITY] section renders as readable bullets (one per next-step entry), never a wide or box-drawing
table; no flat key/value report, internal breaks with `<br>`, a pre-response self-check before emitting, exactly
one preferred recommendation within three sentences and 60 words, a PR + full-head-SHA authorization line for
SAFE-TO-APPROVE, Opus effort defaulting to LOW. [NEXT PROMPT] is presentation-only: it renders the exact next
operator prompt derived from decision_class/operator_action/recommendation/where.pr/where.head_sha, as exactly
one fenced text block holding one single line of at most 200 Unicode code points when a prompt exists (never truncated; if no safe prompt fits the bound, the verbatim fallback line `REVIEW-REQUIRED: discuss the decision above; do not act.` is emitted instead, fail-closed), or NONE with a reason otherwise, per the contract §15
decision-class matrix; it never broadens scope, infers §6/§8 authority, weakens a blocker, or emits an
override/bypass prompt under HOLD, and the self-check rejects a truncated, merged, malformed, or incomplete
[NEXT PROMPT]. RESEARCH-ONLY, DEFERRED, and NO-OP must not appear in the Decision-Class position. This file
references and operationalizes §14–§16; it does not redefine any class or
label.
