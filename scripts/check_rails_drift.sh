#!/usr/bin/env bash
# check_rails_drift.sh — KRONOS rails duplicate detector.
#
# Policy: the repository .claude/ directory is the SOLE canonical and executable source
# for KRONOS commands and agents. They are NOT mirrored into ~/.claude or any other scope.
# A copy of a KRONOS command or agent in user scope (~/.claude) or in a second, out-of-repo
# project scope can silently shadow or compete with the repo copy, so this script FAILS
# (exit 1) if it finds any such duplicate, or if a repo canonical copy is missing. It only
# reads; it never copies and never deletes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_CLAUDE="${REPO_ROOT}/.claude"

# Canonical KRONOS rail files, relative to a .claude/ directory.
CANONICAL=(
  "commands/kronos-continue.md"
  "agents/kronos-researcher.md"
  "agents/kronos-builder.md"
  "agents/kronos-reviewer.md"
)

rc=0

# 1. Repo canonical copies must exist.
for rel in "${CANONICAL[@]}"; do
  if [[ ! -f "${REPO_CLAUDE}/${rel}" ]]; then
    echo "MISSING: repo canonical copy absent: .claude/${rel}"; rc=1
  fi
done

# 2. User scope (~/.claude) must not duplicate any KRONOS command or agent.
USER_CLAUDE="${HOME}/.claude"
if [[ -d "$USER_CLAUDE" && "$USER_CLAUDE" != "$REPO_CLAUDE" ]]; then
  while IFS= read -r dup; do
    [[ -n "$dup" ]] || continue
    echo "DUPLICATE (user scope): ${dup} shadows repo canonical"; rc=1
  done < <(find "$USER_CLAUDE/commands" "$USER_CLAUDE/agents" -maxdepth 1 -name 'kronos-*.md' 2>/dev/null)
fi

# 3. Project scope: no second .claude/ inside the repo tree may carry KRONOS rails.
while IFS= read -r f; do
  [[ -n "$f" ]] || continue
  case "$f" in
    "${REPO_CLAUDE}"/*) : ;;  # the canonical copy itself — fine
    *) echo "DUPLICATE (project scope): ${f} shadows repo canonical"; rc=1 ;;
  esac
done < <(find "$REPO_ROOT" \( -path '*/.claude/commands/kronos-*.md' -o -path '*/.claude/agents/kronos-*.md' \) 2>/dev/null)

if [[ $rc -ne 0 ]]; then
  echo "KRONOS rails duplicate/absence detected — repo .claude/ is canonical; remove out-of-repo copies (never copy repo -> global)." >&2
fi
exit $rc
