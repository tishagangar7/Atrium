# Handoff: backend/tisha-c1-scaffold

| Field | Value |
|---|---|
| Branch | `backend/tisha-c1-scaffold` |
| Owner | Tisha |
| Workstream / queue item | WS-C / C1 |
| PRD sections | §3.4, §7, §8, §12; original tasks T02, T03, T06 |

## Goal

Prepare Tisha's local workflow, then implement C1: backend scaffold, shared schema/type exports and a fixture event stream. This session completes workflow setup only; application implementation has not started.

## Current state

**Status:** C1 complete; ready for PR.

**Done:**
- `backend/pyproject.toml` (fastapi>=0.135, uvicorn[standard], pydantic>=2.9; pytest+httpx dev group), `backend/uv.lock`, `backend/.python-version` (3.12). `uv sync` resolves cleanly (fastapi 0.143.0, pydantic 2.14.0, starlette 1.7.0).
- `backend/app/models.py`: full PRD §7 + §8.5 contracts (enums, Scenario/WorldState, Evidence/Target, Observation, AgentTurn/AgentMessage, Plan/Assignment/Leg/Evaluation/Metrics/Violation/TargetCheck, Acceptance/TargetRevision/Commit/EscalationPackage, SimulationEvent/RunResult/ErrorObject, Snapshot). Every PRD worked example (§7.3, §7.5-§7.8) round-trips through these models (`backend/tests/test_models.py`).
- `backend/scripts/gen_types.py`: dependency-free generator (walks `models.py` field annotations directly, no pydantic-to-ts package) that emits `frontend/src/types.ts`. Deterministic (confirmed: re-running twice produces byte-identical output). Run it after any `models.py` change.
- `backend/app/main.py`: `GET /health` (PRD §8.2, honestly reports `model_available: false` / `provider: null` since no provider is wired yet) and `GET /events/stream`, an SSE hello stream (`fastapi.sse.EventSourceResponse`) replaying `backend/app/fixtures/hello_stream.json` (hand-written `run.reset` + `state.snapshot` envelopes, labeled "Synthetic simulation", validates against `Snapshot`). Honors `Last-Event-ID` to skip already-seen `seq` (full reconnect/resume is C3). CORS allows only `localhost:5173`/`127.0.0.1:5173` (Rohaan's future Vite dev server).
- `backend/tests/`: `test_health.py`, `test_models.py`, `test_stream_fixture.py` — 11 tests, all green.
- Root `README.md`: Backend section (`uv sync`, run, test, type-regen commands); left a one-line Frontend stub for Rohaan.
- Verified manually end-to-end: `uv run uvicorn app.main:app` + curl on `/health` and `/events/stream` (fresh and with `Last-Event-ID`), and `scripts/check.sh` from repo root (branch check, secret scan, backend pytest) — all pass.

**In progress:**
- None. C1 scope (T02/T03/T06) is done; not yet pushed/PR'd (see Next steps).

**Next steps:**
1. `git add backend frontend/src/types.ts README.md docs/handoff/backend__tisha-c1-scaffold.md`, commit, push, `gh pr create --fill` into `main`. Get one review before merge (AGENTS.md §3).
2. Start C2 (PRD §12.3): run controller (`app/run.py`), reset/step/state endpoints, SSE, JSONL snapshot/event storage — replaces the `app/main.py` fixture stream with the real event feed.
3. When Madhav (WS-A) and Ali (WS-B) have their services, confirm `models.py` fields against their actual usage; any change after this PR merges needs a `contracts/tisha-*` branch + `[contract]` PR title and both owners' agreement (AGENTS.md §2).

**Decisions and why:**
- Wrote a ~150-line dependency-free `gen_types.py` instead of pulling in a pydantic→TypeScript package: keeps generation deterministic/offline and avoids adding a dependency outside this one workstream's config mid-event (AGENTS.md §4/§5 guidance against unnecessary new deps).
- TS fields never use `?:` — every field is required but may be `| null` — matching PRD §7's "optional fields are None, never missing" convention exactly.
- `/health.model_available` is `false` and `provider` is `null`: no runtime provider is wired yet (that's Ali's B1), so this reports reality rather than a placeholder `true`.
- SSE hello stream closes after replaying the two fixture envelopes rather than looping forever; `fastapi.sse.EventSourceResponse`'s routing-layer keep-alive/`Cache-Control`/`X-Accel-Buffering` headers are automatic (confirmed by reading `fastapi/sse.py` and `fastapi/routing.py` in the installed package) so C2's real stream gets these for free without extra code.

**Gotchas / traps:**
- `fastapi.sse.EventSourceResponse` is used as `response_class=` on a path operation that `yield`s `ServerSentEvent`s — not instantiated directly with a generator argument. The routing layer does the keep-alive/header work; don't re-implement it in `app/main.py`.
- Port 8000 may already be occupied by an unrelated local process on this machine; manual verification here used port 8010. Don't assume 8000 is free when testing.
- `backend/.venv` and `uv.lock`'s resolved Python was 3.12.2 (Anaconda's `python3.12`), not the Framework 3.12.6 build also present on this machine — both satisfy the `>=3.12,<3.13` pin, no action needed.
- Ali owns agents/negotiation; Rohaan owns dashboard; Madhav owns simulation backend and scene — nothing in this PR touches those paths.

**How to verify:**
```bash
cd backend
uv sync
uv run pytest -q                                   # 11 passed
uv run python scripts/gen_types.py                  # regenerates frontend/src/types.ts; re-run to confirm no diff
uv run uvicorn app.main:app --port 8010 &
curl -s localhost:8010/health
curl -s -N --max-time 5 localhost:8010/events/stream
kill %1
cd .. && bash scripts/check.sh
```

**Asks for other owners:**
- Madhav: review world/cell/resource/evidence/target field shapes in `models.py` against A1's scenario contracts before G0.
- Ali: review AgentTurn/TurnMessage/Plan/Acceptance/Commit/EscalationPackage field shapes against B1's provider adapter output before G0.
- Rohaan: `frontend/src/types.ts` now exists (generated); build D1 against it. `frontend/` only has `src/types.ts` so far — the rest of the scaffold (package.json, Vite config, App.tsx) is still yours to create.

**Open questions:**
- Runtime provider is Ali's decision under PRD §3.5; coding-model access does not select it. Still open, not blocking C1.

## Session log

### 2026-10-10T06:59Z · codex · Tisha Gangar
**Status:** Local hooks enabled; C1 branch prepared; application implementation not started
```text
HEAD 6c9c12d · behind origin/main: 0
-- commits on branch --
-- uncommitted --
 M .githooks/pre-commit
 M .githooks/pre-push
 M scripts/check.sh
 M scripts/claude-guard-branch.sh
 M scripts/claude-session-start.sh
 M scripts/handoff.sh
 M scripts/lib.sh
 M scripts/setup.sh
 M scripts/start-task.sh
?? docs/handoff/backend__tisha-c1-scaffold.md
-- diffstat vs main --
 .githooks/pre-commit            | 0
 .githooks/pre-push              | 0
 scripts/check.sh                | 0
 scripts/claude-guard-branch.sh  | 0
 scripts/claude-session-start.sh | 0
 scripts/handoff.sh              | 0
 scripts/lib.sh                  | 0
 scripts/setup.sh                | 0
 scripts/start-task.sh           | 0
 9 files changed, 0 insertions(+), 0 deletions(-)
```

### 2026-10-10T07:15Z · claude-code · Tisha Gangar
**Status:** C1 complete: backend scaffold, models.py, type export, SSE hello stream, tests all green
```text
HEAD 5d5e3eb · behind origin/main: 0
-- commits on branch --
5d5e3eb chore(backend): prepare Tisha task workflow
-- uncommitted --
 M README.md
 M docs/handoff/backend__tisha-c1-scaffold.md
?? backend/
?? frontend/
-- diffstat vs main --
 .githooks/pre-commit                       |   0
 .githooks/pre-push                         |   0
 README.md                                  |  33 +++++++++
 docs/handoff/backend__tisha-c1-scaffold.md | 110 +++++++++++++++++++++++++++++
 scripts/check.sh                           |   0
 scripts/claude-guard-branch.sh             |   0
 scripts/claude-session-start.sh            |   0
 scripts/handoff.sh                         |   0
 scripts/lib.sh                             |   0
 scripts/setup.sh                           |   0
 scripts/start-task.sh                      |   0
 11 files changed, 143 insertions(+)
```
