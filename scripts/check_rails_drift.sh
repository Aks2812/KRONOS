#!/usr/bin/env bash
# check_rails_drift.sh — repo -> global SHA-256 drift check for the KRONOS rails that are
# mirrored into ~/.claude (the agent definitions and the resume command).
#
# The repository is canonical. ~/.claude is a convenience mirror. This script compares each
# repo copy against its global counterpart and FAILS (exit 1) on any drift or missing mirror,
# so a stale global copy cannot silently shadow the repo. It only reads; it never copies.
# To update the mirror after the repo copies pass review, copy repo -> global (never the
# reverse) and re-run this until it reports OK.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GLOBAL_DIR="${HOME}/.claude"

# Only the files that are mirrored to the global dir. settings.json, hooks/ and RAILS.md are
# repo-only (not mirrored) and are intentionally not checked here.
MIRRORED=(
  "commands/kronos-continue.md"
  "agents/kronos-researcher.md"
  "agents/kronos-builder.md"
  "agents/kronos-reviewer.md"
)

rc=0
for rel in "${MIRRORED[@]}"; do
  repo_f="${REPO_ROOT}/.claude/${rel}"
  glob_f="${GLOBAL_DIR}/${rel}"
  if [[ ! -f "$repo_f" ]]; then
    echo "DRIFT: repo copy missing: .claude/${rel}"; rc=1; continue
  fi
  if [[ ! -f "$glob_f" ]]; then
    echo "DRIFT: global mirror missing: ~/.claude/${rel}"; rc=1; continue
  fi
  repo_h="$(sha256sum "$repo_f" | cut -d' ' -f1)"
  glob_h="$(sha256sum "$glob_f" | cut -d' ' -f1)"
  if [[ "$repo_h" != "$glob_h" ]]; then
    echo "DRIFT: ${rel}"
    echo "  repo   ${repo_h}"
    echo "  global ${glob_h}"
    rc=1
  else
    echo "OK: ${rel} (${repo_h})"
  fi
done

if [[ $rc -ne 0 ]]; then
  echo "rails drift detected — reconcile repo -> global (repo is canonical), then re-run." >&2
fi
exit $rc
