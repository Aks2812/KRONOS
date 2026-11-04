#!/usr/bin/env bash
# PreToolUse hook — supplemental enforcement of brief scope, gh api method filtering, and
# reviewer isolation.
#
# This hook is supplemental, not the security boundary: .claude/settings.json's
# deny/ask/allow rules and each agent's `tools:`/`disallowedTools:` lists hold even if
# this hook is disabled entirely. This hook: (1) denies any `gh api` call carrying a
# non-GET method, for every caller regardless of agent type — settings.json's path-based
# allow patterns cannot express "GET only", see .claude/RAILS.md; (2) tightens the
# kronos-builder's edits down to the single approved brief's permitted-files list; and
# (3) belt-and-suspenders denies any write or network call attempted by kronos-reviewer.
#
# Expected PreToolUse stdin JSON (Claude Code hook protocol): fields include at least
# tool_name, tool_input, and — when the caller is a dispatched subagent — an identifier
# of which subagent is calling (checked below under a few plausible field names, since
# this is not standardized across Claude Code versions). The active brief's sha256 and
# permitted-files glob list are read from .claude/current-brief.json, written by the
# parent orchestrator before each builder dispatch — never inferred by this hook.
#
# On anything this hook cannot parse (missing fields, malformed JSON, no current-brief
# record), it emits nothing and exits 0 — i.e. defers entirely to the normal permission
# system, per spec: "return nothing on anything it cannot parse."

set -euo pipefail

INPUT="$(cat)"

ALLOW='{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"}}'

deny() {
  local reason="$1"
  jq -n --arg reason "$reason" \
    '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":$reason}}'
  exit 0
}

ask() {
  local reason="$1"
  jq -n --arg reason "$reason" \
    '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":$reason}}'
  exit 0
}

# Return nothing (defer to normal permission flow) — used whenever we cannot
# confidently parse enough to make a scoped decision.
defer() {
  exit 0
}

TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || true)"
[ -n "$TOOL_NAME" ] || defer

# Global, agent-type-independent check: no `gh api` call may mutate. Pattern rules in
# settings.json cannot express "GET only" (a path match and a method match are
# orthogonal), so this is enforced here instead, for every caller — the parent
# orchestrator included, not just dispatched subagents.
#
# Method filter: `gh api` is detected anywhere in the command (line start, after ; & |,
# inside $(...) or backticks, inside sh -c "..." strings). It is DENIED if it carries
# any field/body flag (-f, -F, --field, --raw-field, --input; spaced, =, or glued forms
# such as -ffoo=bar and --input=f.json — gh turns these into a POST), or any method
# flag (-XPOST, -X POST, --method POST, --method=POST) naming anything but GET/HEAD.
# It passes to normal permissions only when provably read-only: no field/input flags
# and either no method flag or an explicit GET/HEAD. Anything unparseable, any unknown
# flag, or any unrecognized/missing method token fails CLOSED (deny).
if [ "$TOOL_NAME" = "Bash" ]; then
  COMMAND="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
  if [ -n "$COMMAND" ]; then
    GH_API_VERDICT="$(python3 - "$COMMAND" <<'PY'
import re
import shlex
import sys

GH_API_RE = re.compile(r'\bgh\b[^\n]*?\bapi\b')
OPS = set(";&|()<>") | {"&&", "||", ";;", "|&", "$("}
SHORT_VALUE = set("HqtpT")          # value-taking short flags (value is rest or next arg)
LONG_VALUE = {"--cache", "--header", "--hostname", "--jq", "--preview", "--template"}
LONG_NOVALUE = {"--include", "--paginate", "--silent", "--slurp", "--verbose", "--help"}
LONG_FIELD = {"--field", "--raw-field", "--input"}
OK_METHODS = {"GET", "HEAD"}


def analyze_args(args):
    """Return None if provably read-only, else a deny reason."""
    i = 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--":
            continue
        if a.startswith("--"):
            name, eq, val = a.partition("=")
            if name in LONG_FIELD:
                return "field/body flag %s" % name
            if name == "--method":
                if not eq:
                    if i >= len(args):
                        return "--method without a value"
                    val = args[i]
                    i += 1
                if val.upper() not in OK_METHODS:
                    return "method %r" % val
            elif name in LONG_VALUE:
                if not eq:
                    i += 1
            elif name in LONG_NOVALUE and not eq:
                pass
            else:
                return "unknown flag %s" % a
        elif a.startswith("-") and len(a) > 1:
            j = 1
            while j < len(a):
                c = a[j]
                if c in "fF":
                    return "field flag -%s" % c
                if c == "X":
                    val = a[j + 1:]
                    if val.startswith("="):
                        val = val[1:]
                    if not val:
                        if i >= len(args):
                            return "-X without a value"
                        val = args[i]
                        i += 1
                    if val.upper() not in OK_METHODS:
                        return "method %r" % val
                    break
                if c in SHORT_VALUE:
                    if j + 1 >= len(a):
                        i += 1
                    break
                if c in "ih":
                    j += 1
                    continue
                return "unknown flag %s" % a
        # else: positional (endpoint)
    return None


def scan(text, depth=0):
    """Return None if no mutating gh api found, else a deny reason."""
    if depth > 5:
        return "nesting too deep to analyze"
    try:
        lex = shlex.shlex(text.replace("`", " ; "), posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError as e:
        return "unparseable command (%s)" % e
    n = len(toks)
    for idx, t in enumerate(toks):
        if t != "gh":
            # quoted payload (sh -c "...") mentioning gh api: analyze recursively
            if GH_API_RE.search(t) and t != text:
                r = scan(t, depth + 1)
                if r:
                    return r
            continue
        end = idx + 1
        while end < n and not (set(toks[end]) <= OPS):
            end += 1
        seg = toks[idx + 1:end]
        if "api" not in seg:
            continue
        r = analyze_args(seg[seg.index("api") + 1:])
        if r:
            return r
    return None


cmd = sys.argv[1]
if not GH_API_RE.search(cmd):
    print("")
else:
    r = scan(cmd)
    print("DENY:" + r if r else "GET")
PY
)"
    case "$GH_API_VERDICT" in
      "" | "GET") ;;
      *)
        deny "gh api calls must be provably read-only (GET/HEAD, no field/input flags); blocked: ${GH_API_VERDICT#DENY:}. Discipline layer per RAILS.md, not the merge boundary — merge still requires ask + branch protection."
        ;;
    esac
  fi
fi

# Identify the dispatching agent type under any of the field names different Claude Code
# versions have used for this. If none is present, this call did not come from a
# dispatched subagent (or we cannot tell) — defer, do not guess.
AGENT_TYPE="$(printf '%s' "$INPUT" | jq -r \
  '.agent_type // .subagent_type // .agentType // empty' 2>/dev/null || true)"
[ -n "$AGENT_TYPE" ] || defer

case "$AGENT_TYPE" in
  kronos-reviewer)
    case "$TOOL_NAME" in
      Write|Edit|MultiEdit|NotebookEdit)
        deny "kronos-reviewer is read-only; it must never write or edit files."
        ;;
      WebFetch|WebSearch)
        deny "kronos-reviewer has no network access; its only inputs are the diff and the brief."
        ;;
      *)
        defer
        ;;
    esac
    ;;

  kronos-builder)
    case "$TOOL_NAME" in
      Write|Edit|MultiEdit)
        ;;
      *)
        defer
        ;;
    esac

    FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)"
    [ -n "$FILE_PATH" ] || defer

    PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
    BRIEF_RECORD="$PROJECT_DIR/.claude/current-brief.json"
    [ -f "$BRIEF_RECORD" ] || defer

    BRIEF_PATH="$(jq -r '.brief_path // empty' "$BRIEF_RECORD" 2>/dev/null || true)"
    RECORDED_SHA="$(jq -r '.sha256 // empty' "$BRIEF_RECORD" 2>/dev/null || true)"
    [ -n "$BRIEF_PATH" ] && [ -n "$RECORDED_SHA" ] || defer
    [ -f "$PROJECT_DIR/$BRIEF_PATH" ] || defer

    ACTUAL_SHA="$(sha256sum "$PROJECT_DIR/$BRIEF_PATH" | awk '{print $1}')"
    if [ "$ACTUAL_SHA" != "$RECORDED_SHA" ]; then
      ask "Brief sha256 drift: $BRIEF_PATH is now $ACTUAL_SHA, checkpoint recorded $RECORDED_SHA."
    fi

    # Path relative to the project dir, for matching against the brief's own globs.
    case "$FILE_PATH" in
      "$PROJECT_DIR"/*) REL_PATH="${FILE_PATH#"$PROJECT_DIR"/}" ;;
      /*) REL_PATH="$FILE_PATH" ;;
      *) REL_PATH="$FILE_PATH" ;;
    esac

    MATCHED="$(jq -r --arg p "$REL_PATH" \
      '(.permitted_files // []) | map(select(. as $g | $p | test($g |
          sub("\\*\\*"; ".*") | sub("\\*"; "[^/]*") ))) | length' \
      "$BRIEF_RECORD" 2>/dev/null || echo 0)"

    if [ "${MATCHED:-0}" -gt 0 ] 2>/dev/null; then
      printf '%s\n' "$ALLOW"
      exit 0
    else
      PERMITTED="$(jq -r '(.permitted_files // []) | join(", ")' "$BRIEF_RECORD" 2>/dev/null || echo '(none recorded)')"
      deny "kronos-builder may only edit files the approved brief permits: $PERMITTED. Requested: $REL_PATH."
    fi
    ;;

  *)
    defer
    ;;
esac
