#!/usr/bin/env bash
# Append a git snapshot to this branch's handoff doc. Run before stopping or switching tools.
# Usage: scripts/handoff.sh <tool: claude-code|codex|cursor|human> "<one-line status>"
set -euo pipefail
source "$(dirname "$0")/lib.sh"
tool="${1:-unknown}"; note="${2:-}"
branch="$(current_branch)"
case "$branch" in main|master|"(detached)") echo "On $branch: no handoff doc. Start a task branch."; exit 1;; esac
hf="$(handoff_path "$branch")"
[[ -f "$hf" ]] || sed -e "s|{{BRANCH}}|$branch|g" -e "s|{{NAME}}|${branch#*/}|g" -e "s|{{AREA}}|${branch%%/*}|g" \
  -e "s|{{DATE}}|$(date -u +%Y-%m-%dT%H:%MZ)|g" "$(git rev-parse --show-toplevel)/docs/handoff/TEMPLATE.md" > "$hf"

base="$(git merge-base HEAD origin/main 2>/dev/null || echo HEAD)"
{
  echo
  echo "### $(date -u +%Y-%m-%dT%H:%MZ) · $tool · $(git config user.name || whoami)"
  [[ -n "$note" ]] && echo "**Status:** $note"
  echo '```text'
  echo "HEAD $(git rev-parse --short HEAD) · behind origin/main: $(git rev-list --count HEAD..origin/main 2>/dev/null || echo ?)"
  echo "-- commits on branch --"; git log --oneline "$base"..HEAD | head -15
  echo "-- uncommitted --"; git status -s | head -30
  echo "-- diffstat vs main --"; git diff --stat "$base" | tail -15
  echo '```'
} >> "$hf"
echo "Appended snapshot to ${hf#$(git rev-parse --show-toplevel)/}"
echo "Reminder: rewrite 'Current state', then: git add -A && git commit -m 'wip(${branch%%/*}): handoff' && git push"
