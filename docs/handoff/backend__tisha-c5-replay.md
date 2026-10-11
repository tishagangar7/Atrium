# Handoff: backend/tisha-c5-replay

| Field | Value |
|---|---|
| Branch | `backend/tisha-c5-replay` |
| Owner | tisha |
| Workstream / queue item | WS-C / C5 |
| PRD sections | §4.7, §8.2, §13.3, §12.3; original task included in T22 |
| Created | 2026-10-10T08:37Z |

## Goal

Implement C5: replay endpoints and stored run retrieval (PRD §12.3). Done means:
`POST /replay/{run_id}` replaces the active run with a labeled, paced replay of a saved
`runs/<run_id>/events.jsonl`; `GET /runs`/`GET /runs/{id}`/`GET /runs/{id}/events` let a client
list and inspect historical runs; stepping is rejected during replay (`REPLAY_READ_ONLY`); a
reset still cancels an active replay. Proven by `backend/tests/test_replay.py` (8 tests) plus
manual curl verification.

## Current state

**Status:** complete; ready for PR.

**Done:**
- `backend/app/store.py`: `read_events(run_id)`, `list_run_ids()`, `run_summary(run_id)` — pure
  filesystem reads over `runs/**`, no dependency on the active `RunController`.
- `backend/app/run.py`: `RunController` gained a `self._mode: RunMode` (`"live"`/`"replay"`),
  used by `snapshot()` instead of a hardcoded `"live"`. New `start_replay(run_id, speed)`: closes
  the current live run via a new shared `_close_active_run()` helper (also used by `reset()`),
  rehydrates `self._world` from the last recorded `state.snapshot` envelope's `data.world`,
  relabels every loaded envelope's `run_id`/`mode` to the new `replay-of-{run_id}`/`"replay"`.
  `step()` now raises `ReplayReadOnly` (→ `409 REPLAY_READ_ONLY`, a code `models.ErrorObject`
  already defined per §7.8 but unused until now) while in replay mode. `_emit()` skips
  `store.append_event` during replay — it re-serves an existing recording, it doesn't create a
  new on-disk one.
- `backend/app/main.py`: `POST /replay/{run_id}`, `GET /runs`, `GET /runs/{run_id}`,
  `GET /runs/{run_id}/events`. `/events/stream` now paces envelope delivery by the real `ts` delta
  between consecutive recorded envelopes, divided by the chosen replay speed, while
  `controller.mode == "replay"` (§4.7 "original relative timing"); live streaming is unaffected.
- **Fixed a pre-existing break on `main` affecting everyone, not just this branch:** Ali's merged
  B1 (`backend/app/agents/provider_anthropic.py`/`provider_openai.py`) imports `anthropic`/`openai`
  unconditionally at module level, but neither was ever added to `backend/pyproject.toml`'s
  dependencies (Ali tested with ephemeral `uv run --with anthropic --with openai`, not the shared
  lockfile). A plain `uv sync` + `pytest` on `main` right now fails at test *collection* for
  everyone. Added both as real dependencies (pinned to the exact versions Ali's own handoff
  recorded testing against: `anthropic>=1.13.0`, `openai>=3.28.0`) and re-ran `uv sync` —
  `pyproject.toml`/`uv.lock` are explicitly Tisha/WS-C's files, so this is mine to fix, and it's a
  minimal, version-matched addition, not a new dependency choice.
- 80 backend tests pass (72 before this branch — 30 WS-C + 42 Ali's agent tests, the latter only
  collectible now — plus 8 new in `test_replay.py`): unknown-run 404, mode switch + envelope
  relabeling, `GET /state` reflects replay mode + rehydrated world, step blocked during replay,
  reset cancels replay, `GET /runs` open-vs-closed `final_state_hash`, run detail/events/404, and
  a deterministic pacing test (hand-rewritten `ts` gaps, asserts speed 4 is meaningfully faster
  than speed 1).
- Manually verified end-to-end over a live server: reset → step → `GET /runs` →
  `POST /replay/{id}` → `GET /state` shows `mode: "replay"` → step → `409 REPLAY_READ_ONLY` →
  paced `/events/stream`. `scripts/check.sh` passes.

**In progress:**
- None. C5 scope is done.

**Next steps:**
1. Commit, push, `gh pr create` (base `main` — this branch started from an up-to-date `main` via
   `scripts/start-task.sh`, so it's a normal, non-stacked PR, unlike C2/C3).
2. C4 (negotiation wiring, `/events/inject`, `/negotiate/cancel`, escalation resolve) still can't
   start for real: depends on Madhav's A3/A4 (PR #5 still open) and Ali's B3/B4 (router/gate/
   escalation — only B1/B2 exist). Revisit once those land.
3. C6 (benchmark runner, baseline integration) is the other C-owned item that doesn't block on
   A3/A4/B3/B4 — reasonable next pick if C4's dependencies are still not ready.

**Decisions and why:**
- `GET /state` right after `start_replay` shows the recording's *initial* world (step 0 in this
  stub), not a reconstructed mid-run state: this exactly mirrors how live mode behaves right after
  a reset (step 0, then the stream delivers subsequent `state.step` envelopes). It's not a gap
  specific to C5 — the real cause is that `step()` (C2) doesn't yet emit a fresh `state.snapshot`
  every 10 steps per §8.3's table, so a recording only ever has the one snapshot from its reset.
  Revisit once periodic snapshots exist.
- Replay doesn't persist a `replay-of-{id}` folder under `runs/`: it's explicitly "a recording,"
  not a new run (§4.7); writing a near-duplicate copy would be noise.
- `final_state_hash` in `run_summary()` is `None` until a run is closed by a later reset — matches
  `run.closed` only being emitted when something else replaces the active run, not speculatively.

**Gotchas / traps:**
- The `anthropic`/`openai` dependency fix above is unrelated to C5's actual feature work but was
  necessary to get a clean `scripts/check.sh` run; flagged clearly in the PR so a reviewer doesn't
  mistake it for scope creep.
- `start_replay` requires at least one recorded `state.snapshot` envelope in the run; a run that
  somehow has none (shouldn't happen via this controller's own `reset()`) is treated as
  `RunNotFound` rather than a different error code — there's no real-world case yet that produces
  such a file, so this hasn't been tested with one.

**How to verify:**
```bash
cd backend && uv run pytest -q          # 80 passed
cd .. && bash scripts/check.sh
```

**Asks for other owners:**
- None new. Same standing asks as C1/C2: Madhav/Ali review `models.py` fields they depend on;
  Rohaan builds the frontend against `frontend/src/types.ts`.
- Flagging for Ali (informational, not a request to act): `backend/pyproject.toml` now declares
  `anthropic`/`openai` as real dependencies so `uv sync` alone is enough for anyone to run the
  full suite — no action needed unless a different pinned version is intended later.

**Open questions:**
- None new.

## Session log  (append-only; `scripts/handoff.sh` adds entries)

### 2026-10-10T08:43Z · claude-code · Tisha Gangar
**Status:** C5 complete: replay/runs endpoints, paced SSE, REPLAY_READ_ONLY; fixed missing anthropic/openai deps; 80 tests green
```text
HEAD 874f39d · behind origin/main: 0
-- commits on branch --
-- uncommitted --
 M backend/app/main.py
 M backend/app/run.py
 M backend/app/store.py
 M backend/pyproject.toml
 M backend/uv.lock
?? backend/tests/test_replay.py
?? docs/handoff/backend__tisha-c5-replay.md
-- diffstat vs main --
 backend/app/main.py    |  56 +++++++++++++++++++++
 backend/app/run.py     |  66 +++++++++++++++++++++++--
 backend/app/store.py   |  42 ++++++++++++++--
 backend/pyproject.toml |   2 +
 backend/uv.lock        | 131 +++++++++++++++++++++++++++++++++++++++++++++++++
 5 files changed, 290 insertions(+), 7 deletions(-)
```
