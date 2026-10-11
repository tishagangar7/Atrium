#!/usr/bin/env bash
# Shared helpers for workflow scripts and git hooks.
BRANCH_RE='^(sim|agents|backend|frontend|contracts|docs|fix|chore|spike)/(ali|tisha|rohaan|madhav)-[a-z0-9][a-z0-9-]*$'

current_branch() { git symbolic-ref --quiet --short HEAD 2>/dev/null || echo "(detached)"; }

handoff_path() {
  local root; root="$(git rev-parse --show-toplevel)"
  echo "$root/docs/handoff/${1//\//__}.md"
}

# Path globs each branch area may touch without a warning (AGENTS.md section 2).
area_globs() {
  case "$1" in
    sim)       echo 'backend/app/sim/* backend/app/baselines/fixed_rule.py scenarios/* frontend/src/simulation/* backend/tests/test_sim* backend/tests/test_validate.py backend/tests/test_metrics.py backend/tests/test_beliefs.py' ;;
    agents)    echo 'backend/app/agents/* backend/app/negotiation/* backend/app/baselines/single_agent.py backend/tests/test_protocol.py backend/tests/test_hash.py backend/tests/test_actor*' ;;
    backend)   echo 'backend/app/main.py backend/app/run.py backend/app/store.py backend/app/models.py backend/app/bench/* backend/pyproject.toml backend/uv.lock backend/.env.example backend/tests/* frontend/src/types.ts backend/scripts/*' ;;
    frontend)  echo 'frontend/package.json frontend/package-lock.json frontend/*.config.* frontend/tsconfig* frontend/index.html frontend/src/App.tsx frontend/src/api.ts frontend/src/stream.ts frontend/src/main.tsx frontend/src/components/* frontend/src/*.css frontend/e2e/* frontend/public/*' ;;
    contracts) echo 'backend/app/models.py frontend/src/types.ts backend/scripts/* runs/fixtures/* scenarios/fixtures/*' ;;
    *)         echo '*' ;;
  esac
}
