#!/usr/bin/env bash
# One-time setup per clone or worktree: enable repo git hooks.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
chmod +x .githooks/* scripts/*.sh
echo "Git hooks enabled (core.hooksPath=.githooks)."
echo "Branch now: $(git symbolic-ref --quiet --short HEAD || echo detached)"
echo "Next: scripts/start-task.sh <area> <name> <slug> [--worktree]"
