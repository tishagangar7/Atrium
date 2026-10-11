#!/usr/bin/env bash
# Create a feature branch from origin/main (optionally in its own worktree) plus its handoff doc.
# Usage: scripts/start-task.sh <area> <name> <slug> [--worktree]
set -euo pipefail
source "$(dirname "$0")/lib.sh"

[[ $# -ge 3 ]] || { echo "usage: $0 <area> <name> <slug> [--worktree]"; exit 1; }
area="$1"; name="$2"; slug="$3"; mode="${4:-}"
branch="$area/$name-$slug"
[[ "$branch" =~ $BRANCH_RE ]] || { echo "Bad branch name '$branch'. See AGENTS.md section 3."; exit 1; }

root="$(git rev-parse --show-toplevel)"
cd "$root"
git fetch --quiet origin main
git show-ref --verify --quiet "refs/heads/$branch" && { echo "Branch $branch already exists. Resume it: git switch $branch"; exit 1; }

if [[ "$mode" == "--worktree" ]]; then
  wt="$(dirname "$root")/rotation-wt/${branch//\//__}"
  git worktree add --no-track -b "$branch" "$wt" origin/main
  cd "$wt"
  git config core.hooksPath .githooks
else
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "Working tree not clean. Commit/stash first, or use --worktree."; exit 1
  fi
  git switch --no-track -c "$branch" origin/main
fi

hf="$(handoff_path "$branch")"
mkdir -p "$(dirname "$hf")"
if [[ ! -f "$hf" ]]; then
  sed -e "s|{{BRANCH}}|$branch|g" -e "s|{{NAME}}|$name|g" -e "s|{{AREA}}|$area|g" \
      -e "s|{{DATE}}|$(date -u +%Y-%m-%dT%H:%MZ)|g" docs/handoff/TEMPLATE.md > "$hf"
fi

echo
echo "Ready: $branch"
echo "  dir:     $(pwd)"
echo "  handoff: ${hf#$(pwd)/}  (fill in Goal + PRD sections now)"
echo "  first push: git push -u origin HEAD"
