#!/usr/bin/env bash
# Pre-PR gate: branch sanity, secret scan, backend tests, frontend typecheck/build (whatever exists yet).
set -uo pipefail
source "$(dirname "$0")/lib.sh"
cd "$(git rev-parse --show-toplevel)"
fail=0
b="$(current_branch)"
[[ "$b" =~ $BRANCH_RE ]] || { echo "✗ branch '$b' invalid (AGENTS.md §3)"; fail=1; }

if git grep -nE '(sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{20,}|ANTHROPIC_API_KEY=.+|OPENAI_API_KEY=.+)' -- . ':!*.example' ':!AGENTS.md' ':!scripts/check.sh' >/dev/null; then
  echo "✗ possible secret in tracked files:"; git grep -nlE 'sk-ant-|sk-[A-Za-z0-9]{20,}|_API_KEY=.+' -- . ':!*.example' ':!AGENTS.md' ':!scripts/check.sh'; fail=1
fi

if [[ -f backend/pyproject.toml ]]; then
  echo "→ backend tests"; (cd backend && uv run pytest -q) || fail=1
fi
if [[ -f frontend/package.json ]]; then
  echo "→ frontend typecheck + build"; (cd frontend && npx tsc --noEmit -p . && npm run build --silent) || fail=1
  if [[ -d frontend/dist ]] && grep -rqE 'sk-ant-|sk-[A-Za-z0-9]{20,}' frontend/dist; then echo "✗ key pattern in frontend/dist (NFR-006)"; fail=1; fi
fi
[[ $fail -eq 0 ]] && echo "✓ check passed" || { echo "✗ check failed"; exit 1; }
