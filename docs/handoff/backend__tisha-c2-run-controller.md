# Handoff: backend/tisha-c2-run-controller

| Field | Value |
|---|---|
| Branch | `backend/tisha-c2-run-controller` |
| Owner | Tisha |
| Workstream / queue item | WS-C / C2 |
| PRD sections | §4.7, §8.1, §8.2, §8.3, §8.4, §12.3; original task T12 |
| Created | 2026-10-10T07:30Z |

## Goal

Implement C2: run controller, `reset`/`state`/`step` endpoints, SSE now sourced from the live run,
and JSONL event logging (PRD §12.3). Done means: `POST /scenarios/{id}/reset` builds a world from a
local stub scenario and returns a run_id + snapshot; `GET /state` and `POST /simulation/step` work
against it with state-version/run-id guards; `GET /events/stream` serves the live run's envelopes
after a reset; every envelope is also appended to `runs/<run_id>/events.jsonl`; all of this against
a Tisha-owned stub world, not Madhav's real simulator (swapped in later without changing the HTTP
layer).

**C3 folded into this same branch/PR** (small, direct extension of C2's own files, and PR #4 was
still unreviewed, so nothing to rebase onto mid-stream): sequence/version guards, real
reconnect/resume per §8.4 (`Last-Event-ID` `run_id` comparison + `snapshot.required`), the
`GET /events` polling fallback (§8.2), and NFR-010 bounds. See the second dated entry below for
what changed.

**Important:** this branch is stacked on top of `backend/tisha-c1-scaffold` (PR #2,
https://github.com/tishagangar7/rotation/pull/2), which is **not yet merged** — the team decided to
wait for a review before merging C1 rather than block C2. This branch must be rebased onto
`origin/main` once #2 merges, before its own PR is opened/merged.

## Current state

**Status:** C2 + C3 complete; ready for review (stacked on unmerged #2, see below).

**C3 additions (this entry):**
- `app/main.py`'s `/events/stream` now parses the full `Last-Event-ID: <run_id>:<seq>` (C2 only
  read the `seq` half). If the header's `run_id` doesn't match the effective active run (the real
  one, or the virtual `run-fixture-hello-s1` pre-reset), the server sends one `snapshot.required`
  envelope (`data: {active_run_id}`) and ends the stream, per §8.4, instead of resending stale
  envelopes. If it matches, resumes the backlog after `seq` exactly as before.
- New `GET /events?run_id=&after_seq=` (§8.2 ➕, polling/resume fallback): `200 Envelope[]` capped
  at 500, `409 RUN_MISMATCH` if `run_id` isn't the active run (including "no run yet").
- NFR-010 bounds: `RunController._envelopes` is now `collections.deque(maxlen=10_000)` (in-memory
  buffer cap); `store.append_event` asserts `events.jsonl` stays under 20 MB after each write
  (matches the PRD traceability table's own "assertion in store" for this NFR).
- 9 new tests in `backend/tests/test_reconnect.py` (30 total now): stale-run-id → `snapshot.required`
  before and after a reset; matching-run-id resume (including the pre-reset hello-fixture case,
  preserving C1's original test contract); `GET /events` happy path + `after_seq` filtering + both
  409 cases; an explicit reset → `GET /state` → `GET /events?after_seq=<last_seq>` → `step` →
  re-query reconciliation flow; a direct unit check that the envelope deque's `maxlen` is 10,000.
- Manually verified: stale `Last-Event-ID` against a real run returns `snapshot.required` with the
  real `active_run_id`; `GET /events` happy path and wrong-run-id 409 both correct over a live
  server. `scripts/check.sh` passes (30 tests).

**Done:**
- `backend/app/fixtures/scenario_stub.json`: a `Scenario`-shaped fixture (Tisha's stub, not `scenarios/**`) -- road R1, zone VJ, shelter SS, cells C00/C01/C09, resource B1. Validates against `models.Scenario`.
- `backend/app/store.py`: `start_run(run_id)` (creates/truncates `runs/<run_id>/events.jsonl`) + `append_event(run_id, envelope)`.
- `backend/app/run.py`: `RunController` -- `reset`/`snapshot`/`step`, an `asyncio.Lock` serializing commands (§8.1), a 200-entry request-id idempotency cache, typed errors (`ScenarioNotFound`, `NoActiveRun`, `RunMismatch`, `StateVersionMismatch`, `InvalidRequest`) that `main.py` maps to HTTP status + `ErrorObject`. `step()` only advances a step counter -- no fire/road/resource physics (A2/A3's scope). `until` is explicitly not implemented (422) rather than silently ignored.
- `backend/app/main.py`: reworked into a `create_app()` factory (each call gets its own `RunController` -- needed once `run.py` added mutable state, so tests stay isolated). New endpoints: `POST /scenarios/{id}/reset`, `GET /state`, `POST /simulation/step`. `GET /events/stream` is now run-aware: streams the active run's live envelopes once one exists, falls back to C1's hello fixture before any reset.
- 21 backend tests pass (11 from C1 + 10 new in `test_run_controller.py`, covering reset/404/idempotency/step version+run guards/422 on `until`/live-stream-after-reset). `test_health.py`/`test_stream_fixture.py` switched to `create_app()` for isolation.
- Verified manually end-to-end (uvicorn + curl): reset → state → step → wrong-version 409 → wrong-run 409 → unknown-scenario 404 → `/events/stream` now live → `runs/<run_id>/events.jsonl` has exactly the 3 expected lines. `scripts/check.sh` passes.
- **Bug found and fixed during testing:** the PRD's `run_id` format (§7) has minute granularity, so two resets with the same scenario+seed within the same clock-minute (e.g. a quick server restart) generate the *same* `run_id`. `store.append_event` was blindly appending, so a new run could silently inherit and interleave with a stale `events.jsonl` from an earlier process. Fixed by adding `store.start_run()`, which truncates/creates the file fresh, called once at the top of every `reset()` before any envelope is written for the new run.
- **Second bug found and fixed:** in `reset()`, the `Snapshot` embedded inside the `state.snapshot` envelope's own `data` had `last_seq` one less than its own envelope's `seq` (computed before that envelope's seq was reserved). Fixed by reserving the seq first (`self._seq += 1`), then building the snapshot with that exact seq, then emitting with the pre-reserved seq -- `test_state_matches_last_reset_snapshot` caught this.

**In progress:**
- None. C2 scope (T12's run-controller half) is done.

**Next steps:**
1. Commit and push this C3 addition to the same PR #4 (no new PR). PR body already notes the
   stacked-on-#2 dependency; still true. **Do not merge #4 before #2.**
2. Once #2 merges: `git fetch origin && git rebase origin/main` on this branch, re-run
   `scripts/check.sh`, then merge #4.
3. Start C4 (PRD §12.3): connect negotiation, `/events/inject`, `/negotiate/cancel`,
   `/escalations/{dp_id}/resolve` endpoints and atomic execution -- depends on A3/A4 (Madhav) and
   B3/B4 (Ali) existing first; until then, keep using fixtures/stubs per the independent-start
   principle.
4. When Madhav's `app.sim` exists, replace `_build_world`/the step-counter body in `run.py` with
   calls into his `reset`/`step` service (seam is already isolated there per the plan).

**Decisions and why:**
- Stub scenario under `backend/app/fixtures/`, not `scenarios/**`: that directory is Madhav's exclusive scope (AGENTS.md §2/§12.2); a local stub keeps WS-C independent per the PRD's "independent start" principle without touching another owner's files.
- `step` only advances a step counter, no fire/road/resource physics: that's explicitly A2/A3's scope ("None of the three core coders duplicates simulation rules").
- `state_version` is untouched by plain `step()` calls: per §7, it only increments on event application or commit, neither of which exist yet. Confirmed this is correct PRD behavior, not a gap, via a manual smoke test that initially (wrongly) expected otherwise.
- App factory (`create_app()`) introduced because `run.py` adds mutable state; needed for test isolation (each test gets a fresh `RunController`).
- `final_state_hash` in `run.closed` envelopes is a plain SHA-256 content fingerprint of the world, explicitly *not* the canonical plan hash from §6.7 (that's Ali/WS-B's algorithm, with its own canonicalization rules) -- kept clearly distinct in a code comment.
- `snapshot.required` (C3) is a synthesized envelope, not persisted to `events.jsonl`: it's a transient reconnect signal about the client's state of knowledge, not a fact about the world (§4.7 only logs facts). It still follows the general Envelope shape (§8.3) for consistency.
- The pre-reset hello fixture is treated as a fixed "virtual run" (`run-fixture-hello-s1`, matching the id already hardcoded in `hello_stream.json`) purely so `Last-Event-ID` comparison has something to match against before any real run exists -- this preserves C1's original resume test unchanged while still giving a real `snapshot.required` once a reset actually happens.

**Gotchas / traps:**
- `scripts/start-task.sh` always branches from `origin/main`, which doesn't have C1 yet -- this branch was created manually with `git switch -c`, not the script.
- Rebase onto `origin/main` once PR #2 merges, before merging this branch's PR.
- Keep `/events/stream`'s pre-reset fallback (hello fixture) working -- C1's tests depend on it.
- `run_id` collision risk (see "Bug found" above) is inherent to the PRD's own minute-granularity ID format, not something I changed -- `store.start_run()` makes it harmless (fresh file every reset) but the *same* `run_id` string can still legitimately recur across process restarts within a minute. Don't be surprised by that when reading logs.

**How to verify:**
```bash
cd backend && uv run pytest -q          # 21 passed
uv run uvicorn app.main:app --port 8010 &
curl -s -X POST localhost:8010/scenarios/hello-fixture/reset -H 'content-type: application/json' -d '{"seed":1}'
curl -s localhost:8010/state
curl -s -X POST localhost:8010/simulation/step -H 'content-type: application/json' -d '{"run_id":"<run_id>","expected_state_version":0,"steps":3}'
curl -s -N --max-time 3 localhost:8010/events/stream
kill %1
cd .. && bash scripts/check.sh
```

**Asks for other owners:**
- None new this branch (same asks as C1's handoff: Madhav/Ali review their `models.py` fields; Rohaan builds frontend scaffold against `frontend/src/types.ts`).

**Open questions:**
- None new.

## Session log

### 2026-10-10T07:44Z · claude-code · Tisha Gangar
**Status:** C2 complete: run controller, reset/state/step endpoints, live SSE, JSONL; 21 tests green
```text
HEAD 5985726 · behind origin/main: 0
-- commits on branch --
5985726 feat(backend): C1 scaffold, shared schemas/type export, SSE hello stream
5d5e3eb chore(backend): prepare Tisha task workflow
-- uncommitted --
 M backend/app/main.py
 M backend/tests/test_health.py
 M backend/tests/test_stream_fixture.py
?? backend/app/fixtures/scenario_stub.json
?? backend/app/run.py
?? backend/app/store.py
?? backend/tests/test_run_controller.py
?? docs/handoff/backend__tisha-c2-run-controller.md
-- diffstat vs main --
 backend/tests/__init__.py                  |   0
 backend/tests/test_health.py               |  17 +
 backend/tests/test_models.py               | 147 ++++++++
 backend/tests/test_stream_fixture.py       |  42 +++
 backend/uv.lock                            | 435 +++++++++++++++++++++++
 docs/handoff/backend__tisha-c1-scaffold.md | 123 +++++++
 frontend/src/types.ts                      | 444 +++++++++++++++++++++++
 scripts/check.sh                           |   0
 scripts/claude-guard-branch.sh             |   0
 scripts/claude-session-start.sh            |   0
 scripts/handoff.sh                         |   0
 scripts/lib.sh                             |   0
 scripts/setup.sh                           |   0
 scripts/start-task.sh                      |   0
 25 files changed, 2277 insertions(+)
```

### 2026-10-10T07:53Z · claude-code · Tisha Gangar
**Status:** C3 complete: reconnect/resume, snapshot.required, GET /events, NFR-010 bounds; 30 tests green
```text
HEAD a2f955d · behind origin/main: 0
-- commits on branch --
a2f955d feat(backend): C2 run controller, reset/state/step endpoints, live SSE+JSONL
5985726 feat(backend): C1 scaffold, shared schemas/type export, SSE hello stream
5d5e3eb chore(backend): prepare Tisha task workflow
-- uncommitted --
 M backend/app/main.py
 M backend/app/run.py
 M backend/app/store.py
 M docs/handoff/backend__tisha-c2-run-controller.md
?? backend/tests/test_reconnect.py
-- diffstat vs main --
 backend/tests/test_models.py                     | 147 ++++++
 backend/tests/test_run_controller.py             | 142 ++++++
 backend/tests/test_stream_fixture.py             |  42 ++
 backend/uv.lock                                  | 435 ++++++++++++++++++
 docs/handoff/backend__tisha-c1-scaffold.md       | 123 +++++
 docs/handoff/backend__tisha-c2-run-controller.md | 164 +++++++
 frontend/src/types.ts                            | 444 ++++++++++++++++++
 scripts/check.sh                                 |   0
 scripts/claude-guard-branch.sh                   |   0
 scripts/claude-session-start.sh                  |   0
 scripts/handoff.sh                               |   0
 scripts/lib.sh                                   |   0
 scripts/setup.sh                                 |   0
 scripts/start-task.sh                            |   0
 30 files changed, 3022 insertions(+)
```
