# AGENTS.md — RescueMesh (team The Rotation)

This is the single source of rules for every coding agent: Claude Code, Codex, Cursor or anything else.
`CLAUDE.md` imports this file. If something here conflicts with a tool's defaults, this file wins.

## 1. What we are building (read before coding)

RescueMesh: three independent AI agents (Evacuation, Fire Operations, Logistics) negotiate a wildfire
response inside a **synthetic** deterministic simulator. A plan commits only when all three accept the
same plan hash at the same state version; otherwise the system escalates to a human.

- Spec: `docs/RescueMesh_Technical_PRD.md` (cite it as `PRD §n`). Background: `docs/RESCUEMESH_PROJECT_BRIEF.md`.
- Event: 24-hour hackathon. H+n = hours since coding start. Gates: **G0 H+2** contracts frozen,
  **G1 H+10** vertical slice, **G2 H+14** full three-agent disruption loop, **G3 H+21** feature freeze.
- Don't read the whole PRD every session. Read the section for your task: §5 simulator, §6 protocol,
  §7 data contracts, §8 API/SSE, §9 dashboard, §10 reliability, §11 tests, §12 ownership.

### Invariants you must never break (PRD Appendix A.3)

1. Exactly three actors. No supervisor. The router delivers, dedupes and enforces deadlines. It never ranks, scores or picks plans.
2. Commit only on unanimous acceptance of an identical canonical plan hash at the current `state_version`. Silence, timeouts and malformed output are never acceptance.
3. Every outcome number comes from a simulator `Evaluation`. Agent output schemas have no metric fields.
4. `evaluate_plan` runs on a clone and never mutates the authoritative world.
5. Private evidence is isolated **in code** (belief views, `ToolContext`), not by prompt wording. Prompts contain only held evidence.
6. New evidence or an event increments `state_version`, voids acceptances and discards in-flight results.
7. Hard constraints are never waived by agents or by humans. Target changes are logged.
8. Live mode never scripts agent messages. The test provider and replays are labeled (TEST PROVIDER / REPLAY).
9. Everything is labeled "Synthetic simulation". Don't claim results until `runs/results.csv` exists.
10. API keys live only in `backend/.env` (git-ignored). Never in the frontend, logs, commits or handoff docs.

## 2. Team, workstreams and file ownership (PRD §12)

| WS | Owner | Dev model access | Branch prefix | Owns (sole editor) |
|---|---|---|---|---|
| A Simulation | Madhav (separate track) | unspecified | `sim/` | `backend/app/sim/**`, `backend/app/baselines/fixed_rule.py`, `scenarios/**`, `frontend/src/simulation/**`, `backend/tests/test_sim*.py`, `test_validate.py`, `test_metrics.py`, `test_beliefs.py` |
| B Agents + negotiation | **Ali** | **Fable** (the Fable laptop) | `agents/` | `backend/app/agents/**`, `backend/app/negotiation/**`, `backend/app/baselines/single_agent.py`, `backend/tests/test_protocol.py`, `test_hash.py`, `test_actor*.py` |
| C Backend integration | **Tisha** | normal | `backend/` | `backend/app/{main,run,store,models}.py`, `backend/app/bench/**`, backend deps/config, schema export, generated `frontend/src/types.ts`, API/stream/replay tests |
| D Command-center UI | **Rohaan** | normal | `frontend/` | frontend deps/config, `frontend/src/{App.tsx,api.ts,stream.ts}`, `frontend/src/components/**`, `frontend/e2e/**` |

Rules:
- **Edit only files your workstream owns.** If you need a change in another owner's file, write it as a
  request in your handoff doc under "Asks for other owners" and tell that person. Don't patch it yourself.
- **`models.py` and `frontend/src/types.ts`:** only Tisha (WS-C) edits them. `types.ts` is generated and never
  hand-edited. After G0, a contract change needs the producer and consumer owners to agree first. Use a
  `contracts/<name>-<slug>` branch and put `[contract]` in the PR title.
- Work against fixtures and stubs so nobody blocks on anybody. Never present a stub as live output.

## 3. Branch rules (enforced)

**Never edit, commit or push on `main`.** Every change, including docs, goes on a feature branch and
reaches `main` through a PR.

Branch name: `<area>/<name>-<slug>`
- `area`: `sim` `agents` `backend` `frontend` `contracts` `docs` `fix` `chore` `spike`
- `name`: `ali` `tisha` `rohaan` `madhav`
- `slug`: lowercase kebab. Include the queue ID when there is one: `agents/ali-b4-commit-gate`, `frontend/rohaan-d2-timeline`.

Enforcement (run `scripts/setup.sh` once per clone or worktree):
- `.githooks/pre-commit` blocks commits on `main` or `master`, blocks bad branch names and blocks staged `.env` files. It **warns** when staged files fall outside the branch area's ownership.
- `.githooks/pre-push` blocks pushes to `main` or `master`.
- Claude Code: `.claude/settings.json` hooks block file edits on `main` and print branch and handoff state at session start.
- Codex and other tools: no hooks. **Before your first edit, run `git branch --show-current`. If it prints `main`, stop and start a task branch.**
- Never use `--no-verify`. Never force-push a branch someone else is working on.

### Task lifecycle

```bash
scripts/start-task.sh <area> <name> <slug>              # new branch from origin/main + handoff doc
scripts/start-task.sh <area> <name> <slug> --worktree   # same, in ../rotation-wt/<branch> (required on a shared laptop)
# ...work: small commits, each one leaves tests green...
git fetch origin && git rebase origin/main               # at least every ~2 h and before each PR
scripts/check.sh                                         # tests + typecheck + secret scan
scripts/handoff.sh <tool> "one-line status"              # before stopping or switching tools
git push -u origin HEAD && gh pr create --fill            # PR into main
```

- One branch = one queue item (or a slice of one). Aim for a PR every 1–3 hours. Small PRs merge without conflicts.
- Merge with **squash**. Delete the branch after merge. Don't keep long-lived personal branches.
- PR review: one other person (or a Fable review pass, see §5) looks at the PR before merge.
  `[contract]` PRs need both affected owners. Around a gate, merge only green PRs.
- After G3 (H+21): bug fixes only, on `fix/` branches.

## 4. Handoff protocol (switching tools, people or laptops)

Every branch has one handoff doc: `docs/handoff/<branch with "/" replaced by "__">.md`
(for example `docs/handoff/agents__ali-b4-commit-gate.md`). `start-task.sh` creates it from
`docs/handoff/TEMPLATE.md`. It lives and merges with the branch. Each file has a unique name, so files never conflict.

**On session start (any tool):**
1. `git branch --show-current`. If it prints `main`, stop (see §3).
2. Read this branch's handoff doc. Trust "Current state" and "Next steps" over guesses.
3. `git log --oneline origin/main..HEAD` and `git status -s` to confirm the doc matches reality.

**Before you stop, hand off, or switch between Claude Code, Codex or another tool:**
1. Rewrite the **Current state** section: status, done, in progress, next steps (concrete, ordered),
   decisions and why, gotchas, how to verify, asks for other owners.
2. Run `scripts/handoff.sh <tool> "<one-line status>"`. It appends a git snapshot to the session log.
3. Commit, including WIP: `git commit -am "wip(<area>): <what>"`. WIP commits are fine on feature branches. Push.
4. Never leave a handoff that depends on uncommitted local state or on chat history.

Write handoffs for a reader with **zero context**: name files, functions, PRD sections and the exact failing
test or command. Skip narration. Never paste secrets or full prompts with keys.

## 5. Model and tool routing (one Fable laptop, three active coders)

Fable is the scarce, highest-capability seat. It's Ali's laptop and Ali owns WS-B. Spend Fable on work
where judgment pays off. Use normal models, Codex and other tools for volume work.

| Use Fable for | Use normal Claude Code / Codex for |
|---|---|
| WS-B protocol core: router, hash, commit gate, cancellation, escalation (PRD §6) | Scaffolding, boilerplate endpoints, UI components, styling |
| G0 contract review of `models.py` against PRD §7 (all owners' fields) | Tests from a clear spec, fixtures, refactors inside one file |
| Pre-gate reviews (G1, G2, G3) of merged `main` against the invariants in §1 | Docs, README, scripts |
| Cross-workstream integration bugs: stale versions, SSE resume, leaks (AC-025) | Second opinions: ask Codex to review a Claude diff, or the reverse |

**Borrowing the Fable laptop** (Tisha, Rohaan or Madhav):
1. Agree on a time box with Ali (≤ 45 min). Ali's checkout is never touched.
2. Push your branch. On the Fable laptop: `git fetch && git worktree add ../rotation-wt/<branch__name> <branch> && cd ../rotation-wt/<branch__name> && scripts/setup.sh`.
3. Start the session with: "Read AGENTS.md and docs/handoff/<file>. Task: …". Commit with your identity:
   `git commit --author="Your Name <you@example.com>"`.
4. Finish with the handoff steps in §4, push, then `git worktree remove ../rotation-wt/<branch__name>`.

Agents in any tool should:
- Keep the session to the one task in the handoff doc. Don't refactor outside your ownership.
- Prefer tests that pin PRD acceptance criteria (cite `AC-0xx` or `FR-0xx` in the test name or docstring).
- Stop and record the open question in the handoff doc instead of guessing when the PRD is ambiguous. Use the PRD's provisional answers (§14.2) when it gives one.
- Don't add dependencies outside your workstream's config files. Don't upgrade pinned versions during the event.

The app's runtime model (what the three disaster agents call) is chosen in WS-B per PRD §3.5. It is a
fast tier set via `backend/.env`, separate from which model you code with. Don't hard-code a model ID in app code.

## 6. Stack and commands (PRD §3.4, planned until scaffolded at G0)

- Backend: Python 3.12, FastAPI (≥ 0.135 native SSE), Pydantic v2, `uv`. In `backend/`:
  `uv sync` · `uv run pytest -q` · `uv run uvicorn app.main:app --reload --port 8000`
- Frontend: Vite + React + TypeScript, SVG map, `EventSource`. In `frontend/`:
  `npm ci` · `npm run dev` · `npm run build` · `npx tsc --noEmit`
- Test provider: `RESCUEMESH_TEST=1` enables `provider_fake.py` (protocol tests only).
- Whole-repo gate before a PR: `scripts/check.sh`.
- Lock files are committed. Don't upgrade toolchains during the event (PRD §3.6).

## 7. Code conventions

- Contracts: every top-level object has `schema_version: "1"`. Optional fields are `None` and never missing. IDs follow PRD §7.
- Determinism: no wall-clock time or unseeded randomness inside `sim/`. Randomness follows the PRD §5.5 CRN formula.
- Scenario numbers live in `scenarios/*.json`, never as code constants. Record tuning changes in `scenarios/CHANGELOG.md`.
- Logs: every envelope carries `run_id`, `dp_id`, `trace_id`, `seq` (PRD §8.3, §10.5).
- Commits: Conventional Commits, `<type>(<area>): <summary>`, for example `feat(agents): unanimous gate with version check`.
- `runs/` is git-ignored except `runs/fixtures/` and `runs/results.csv`.
