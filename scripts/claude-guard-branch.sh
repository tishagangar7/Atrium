#!/usr/bin/env bash
# Claude Code PreToolUse hook: block file edits inside this repo while on main/master/detached.
input="$(cat)"
file="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty' 2>/dev/null)"
root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[[ -n "$file" && "$file" != "$root"/* ]] && exit 0   # outside repo (e.g. scratch, memory): allow
b="$(git -C "$root" symbolic-ref --quiet --short HEAD 2>/dev/null || echo '(detached)')"
case "$b" in
  main|master|"(detached)")
    echo "Blocked: repo is on '$b'. Never edit on main (AGENTS.md §3). Run scripts/start-task.sh <area> <name> <slug> [--worktree], then continue on that branch." >&2
    exit 2;;
esac
exit 0
