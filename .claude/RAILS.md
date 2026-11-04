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
