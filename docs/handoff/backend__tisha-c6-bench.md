# Handoff: backend/tisha-c6-bench

| Field | Value |
|---|---|
| Branch | `backend/tisha-c6-bench` |
| Owner | tisha |
| Workstream / queue item | WS-C / C6 |
| PRD sections | §4.7, §8.1, §8.2, §11.3, §12.3, §12.7; original task T21 |
| Created | 2026-10-10T08:48Z |

## Goal

Implement C6: benchmark runner/report export, with both baselines stubbed (PRD §12.3). Done
means: `POST /benchmarks/run` runs a headless batch of (preset x seed x method) stub runs in
the background, independent of the live `RunController`; `GET /benchmarks/{id}` is pollable
to `status: "done"`; each run appends a labeled-stub `RunResult` row to a results CSV;
`runs/summary.json` and a markdown report generator exist. Proven by
`backend/tests/test_bench.py` (6 tests) plus manual curl verification.

## Current state

**Status:** complete; ready for PR.

**Done:**
- `backend/app/bench/report.py`: `append_result_row`, `write_summary_json`, `render_markdown`
  (the latter with a bold "STUB DATA -- not a comparative result" banner). Every function takes
  an explicit output path; nothing writes to the real `runs/results.csv`/`docs/results.md`
  automatically -- see Decisions below.
- `backend/app/bench/runner.py`: `BenchmarkRunner`. `start()` validates `presets` against
  `run.SCENARIO_FIXTURES`, refuses a second concurrent run (`AlreadyRunning`), and schedules the
  batch as a detached `asyncio.create_task` so the HTTP call returns immediately. Each stub run
  builds its own world (reusing `run.py`'s `_build_world`/`_new_run_id`/`_state_hash`/
  `_now_iso_ms`), jumps straight to `horizon`, writes its own `events.jsonl`, and records a
  `RunResult` whose `notes` field states plainly that no real negotiation/baseline logic exists
  yet (every method runs the identical stub loop).
- `backend/app/run.py`: `RunController.emit_external(run_id, envelope_type, data)` -- lets the
  benchmark runner push `benchmark.progress`/`.done` envelopes into the live controller's shared
  buffer (so `/events/stream` delivers them) without touching live-run state. New
  `has_buffered_envelopes` property.
- `backend/app/models.py`: added `"BENCHMARK_IN_PROGRESS"` to `ErrorObject.code` -- §8.2 specifies
  "409 if one is running" for `POST /benchmarks/run` but never names a code for it, and the
  existing `NEGOTIATION_IN_PROGRESS` is specifically about the `/negotiate` lifecycle, not
  benchmarks.
- `backend/app/main.py`: `create_app()` now accepts optional `results_csv_path`/
  `summary_json_path` overrides (defaults to the real `runs/results.csv`/`summary.json`; tests
  override with `tmp_path`). `POST /benchmarks/run`, `GET /benchmarks/{benchmark_id}`.
- **Fixed a real bug surfaced by this feature, not pre-existing:** `/events/stream` decided its
  envelope source purely from `controller.is_active` (whether a *live* run exists), so a
  benchmark-only session (no reset ever called) fell back to replaying the static hello fixture
  and silently dropped the benchmark envelopes that were actually sitting in the buffer. Fixed
  with the new `has_buffered_envelopes` property; `/events/stream` now checks
  `is_active or has_buffered_envelopes`.
- **Root-caused a real test-infra trap, not a flaky test:** my first pass of `test_bench.py`
  used a bare `TestClient(create_app())`, and the benchmark polling loop *never* reached
  `"done"` -- not flaky, 100% reproducible. Cause: Starlette's `TestClient` only keeps one
  persistent event loop ("blocking portal") alive across calls when used as `with
  TestClient(...) as client:`; a bare `TestClient()` spins up and tears down a *fresh* loop for
  every single call, silently orphaning any `asyncio.create_task` scheduled on a previous call's
  loop before it ever gets to run again. Fixed by wrapping every test in `with
  TestClient(...) as client:`. Documented at the top of `test_bench.py` since this will bite the
  next person who writes a test against background work.
- 78 backend tests pass (72 before this branch, plus 6 new in `test_bench.py`): unknown-preset
  404, correct row count/columns/notes in the results CSV, concurrent-run 409, unknown-benchmark
  404, summary.json correctness, and benchmark envelopes reaching `/events/stream`.
- Manually verified end-to-end over a live server: start → immediate second POST → 409 → poll →
  done → `runs/results.csv`/`summary.json` inspected and correct → cleaned up (not committed).
  `scripts/check.sh` passes.
- Re-applied the same `anthropic`/`openai` dependency fix from C5 (PR #9, still unmerged) to
  `pyproject.toml`/`uv.lock` on this branch too, since it was branched from `origin/main` which
  doesn't have that fix yet. Will be a trivial, identical-content merge once #9 lands.

**In progress:**
- None. C6 scope is done.

**Next steps:**
1. Commit, push, `gh pr create` (base `main`).
2. C4 (negotiation wiring) and T23 (the real 36-run comparative benchmark batch) both still
   depend on Madhav's A3/A4 (PR #5 open) and Ali's B3/B4/B6 (only B1/B2/B3-in-review exist).
   Revisit once those land -- this PR's `BenchmarkRunner._run_one` is exactly where the real
   per-method dispatch goes in.
3. Once PRs #4/#9/#this merge, rebase and resolve the (trivial, identical) `pyproject.toml`
   dependency-fix duplication.

**Decisions and why:**
- No `runs/results.csv` or `docs/results.md` is committed in this PR: `.gitignore` specifically
  un-ignores `runs/results.csv`, meaning if one existed and were staged it would read as a real
  artifact. Since every row here is explicitly stub data, committing one risked being
  misread as real results despite the `notes` column. Running and committing the real batch is
  T23, once A4/B6 exist.
- Benchmark runs never touch the live `RunController`'s own state (`self._world`/`self._run_id`):
  §8.1 explicitly separates "one active run (live or replay)" from benchmarks, which "run
  headless in the background with their own runs." Reusing `run.py`'s private `_build_world` etc.
  helpers directly (same owner, internal reuse) avoids duplicating that logic a third time.
  `method` doesn't change behavior yet (`fixed_rule`/`single_agent`/`rescuemesh` all run the
  identical stub loop) -- `_run_one` is the seam where real per-method dispatch plugs in later.
- `results_csv_url` in `GET /benchmarks/{id}` reports the *actual* configured path (relative to
  repo root when possible), not a hardcoded `/runs/results.csv` guess -- it's informational, not
  yet a servable download route (unlike C5's `GET /runs/{id}/events`, which is a real route).
  Noted as a small, known gap below.

**Gotchas / traps:**
- See the `TestClient` context-manager trap above -- applies to any future test of background
  work (replay pacing in C5 didn't hit this because it never polled a *separate* call while a
  background task was still running).
- `results_csv_url` isn't a working HTTP route yet, just the real path as a string -- a client
  can't `GET` it today. Building an actual `GET /runs/results.csv` download route is a small,
  easy follow-up if the frontend needs it before C7.
- `emit_external`'s known reconnect limitation (documented in its own docstring in `run.py`):
  if a client's `Last-Event-ID` references a benchmark envelope specifically, the server's
  stale-run check doesn't know about it and may send `snapshot.required` unnecessarily. Per
  §8.4 this is explicitly the client's job to handle ("drop ... except `benchmark.*`"), so not
  solved server-side.

**How to verify:**
```bash
cd backend && uv run pytest -q          # 78 passed
cd .. && bash scripts/check.sh
```

**Asks for other owners:**
- None new. Same standing asks as C1/C2/C5: Madhav/Ali review `models.py` fields they depend on
  (including the new `BENCHMARK_IN_PROGRESS` error code -- purely additive, no existing field
  changed). Regenerated `frontend/src/types.ts` (`uv run python scripts/gen_types.py`) and
  confirmed the diff is exactly the one new literal on `ErrorObject.code` -- Rohaan's build
  already has it, no action needed from him.

**Open questions:**
- None new.

## Session log  (append-only; `scripts/handoff.sh` adds entries)

### 2026-10-10T08:57Z · claude-code · Tisha Gangar
**Status:** C6 complete: benchmark runner/report (stubbed), BENCHMARK_IN_PROGRESS code, TestClient portal gotcha documented; 78 tests green
```text
HEAD 874f39d · behind origin/main: 0
-- commits on branch --
-- uncommitted --
 M backend/app/main.py
 M backend/app/models.py
 M backend/app/run.py
 M backend/pyproject.toml
 M backend/uv.lock
 M frontend/src/types.ts
?? backend/app/bench/
?? backend/tests/test_bench.py
?? docs/handoff/backend__tisha-c6-bench.md
-- diffstat vs main --
 backend/app/main.py    |  63 +++++++++++++++++++++++-
 backend/app/models.py  |   4 ++
 backend/app/run.py     |  39 +++++++++++++++
 backend/pyproject.toml |   2 +
 backend/uv.lock        | 131 +++++++++++++++++++++++++++++++++++++++++++++++++
 frontend/src/types.ts  |   2 +-
 6 files changed, 238 insertions(+), 3 deletions(-)
```

### 2026-10-10T09:37Z · claude-code · Tisha Gangar
**Status:** Rebased onto main (C5 + Ali B3-B6 all merged); resolved run.py/main.py conflicts by keeping both C5's replay additions and C6's benchmark additions side by side; 150 tests green; PR #12 now MERGEABLE/CLEAN
```text
HEAD ad77526 · behind origin/main: 0
-- commits on branch --
ad77526 feat(backend): C6 benchmark runner/report export, baselines stubbed
-- uncommitted --
 M docs/handoff/backend__tisha-c6-bench.md
-- diffstat vs main --
 backend/app/bench/__init__.py           |   0
 backend/app/bench/report.py             |  67 +++++++++++++
 backend/app/bench/runner.py             | 169 ++++++++++++++++++++++++++++++++
 backend/app/main.py                     |  62 +++++++++++-
 backend/app/models.py                   |   4 +
 backend/app/run.py                      |  39 ++++++++
 backend/tests/test_bench.py             | 131 +++++++++++++++++++++++++
 docs/handoff/backend__tisha-c6-bench.md | 165 +++++++++++++++++++++++++++++++
 frontend/src/types.ts                   |   2 +-
 9 files changed, 636 insertions(+), 3 deletions(-)
```
