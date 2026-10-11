#!/usr/bin/env bash
# Claude Code SessionStart hook: inject branch + handoff state into context.
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
source scripts/lib.sh
b="$(current_branch)"
echo "== RescueMesh session start =="
echo "Branch: $b"
case "$b" in
  main|master|"(detached)")
    echo "WARNING: on $b. Edits are blocked. Ask the user which task, then run scripts/start-task.sh <area> <name> <slug> [--worktree]."
    [[ "$(git config core.hooksPath)" == ".githooks" ]] || echo "Git hooks not enabled here: run scripts/setup.sh"
    exit 0;;
esac
[[ "$(git config core.hooksPath)" == ".githooks" ]] || echo "NOTE: git hooks not enabled in this checkout. Run scripts/setup.sh"
echo "Behind origin/main (last fetch): $(git rev-list --count HEAD..origin/main 2>/dev/null || echo ?)"
echo "Uncommitted:"; git status -s | head -20
hf="$(handoff_path "$b")"
if [[ -f "$hf" ]]; then
  echo "Handoff doc: ${hf#$(pwd)/}"
  echo "----"; sed -n '1,/^## Session log/p' "$hf" | head -120
  echo "---- last session log entry ----"; awk '/^### /{buf=""} {buf=buf $0 "\n"} END{printf "%s", buf}' "$hf" | tail -25
else
  echo "No handoff doc for this branch. Create one: scripts/handoff.sh claude-code \"start\""
fi
