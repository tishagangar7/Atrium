# Handoff: backend/tisha-c6-real-methods-fix

| Branch | `backend/tisha-c6-real-methods-fix` |
| Workstream / queue item | Backend / C6 integration follow-up |
| PRD sections | §8.2, §10.5, §11.1–§11.3, §12.3 |

## Current state

**Status:** Implementation complete for the fixes described below, stacked on Rohaan's PR #31 (`backend/rohaan-c6-real-methods`). Merge #25 and #26 before #31, then merge this branch after #31. No live-model benchmark has been run or claimed.

**Done:**
- `backend/app/bench/methods.py`: model methods are async and run on the server's existing event loop, so a live provider no longer hits nested `asyncio.run()`; RescueMesh call rows are totaled once after all decision points; same-DP authoritative forecasts count inappropriate consensus and justified escalation under PRD §11.1.
- `backend/app/bench/runner.py`: awaits model dispatch, clears the active slot after unexpected errors, emits a generic failed status without exposing provider exception text, uses unique IDs for rapid consecutive batches, and writes the two consensus-quality counters into result rows.
- `backend/app/main.py`: `GET /benchmarks/{id}` exposes skipped methods/reasons and a generic error code.
- `backend/tests/test_bench.py`: verifies skip status, awaited model dispatch, failure recovery, and consensus-quality counting.

**Verification:** `scripts/check.sh` passes: 264 backend tests, frontend typecheck/build, secret scan. The first run stopped because this new worktree lacked `frontend/node_modules`; `npm ci` installed its locked dependencies and the rerun passed.

## Next steps

1. Merge #25 (B6) and #26 (fixed rule), then #31 (real method dispatch), after their required reviews.
2. Rebase this branch on the merged #31/main, rerun `scripts/check.sh`, and merge its PR.
3. With a configured live provider, run the 4-preset paired batch, inspect `runs/results.csv`, JSONL logs, and `docs/results.md`; report only observed outcomes.

## Gotchas

- Tests exercise the async dispatch seam with an injected method and fixed-rule runs. They do not exercise paid live model calls.
- `runs/results.csv` does not contain a completed paired live batch, so no comparative claim is supported.
- This branch is based on #31 and does not include Tisha's separate #21/#22 shared-world transport stack; integrate those PRs separately.

## Asks for other owners

- Reviewers of #25, #26, and #31: land those dependencies in order before this follow-up PR.

### 2026-10-10T18:40Z · codex · Tisha Gangar
**Status:** C6 async dispatch, status, and consensus counters complete; full check passed
```text
HEAD d2164a7 · behind origin/main: 1
-- commits on branch --
d2164a7 feat(bench): real benchmark methods; skip, never stub, what cannot run
8393693 Merge remote-tracking branch 'origin/sim/rohaan-a4-fixed-rule' into backend/rohaan-c6-real-methods
d5992f9 feat(baselines): fixed-rule baseline (PRD §11.2, FR-060)
c7aa552 feat(baselines): land B6 single-agent baseline on main with a stale-world guard
-- uncommitted --
 M backend/app/bench/methods.py
 M backend/app/bench/runner.py
 M backend/app/main.py
 M backend/tests/test_bench.py
?? docs/handoff/backend__tisha-c6-real-methods-fix.md
-- diffstat vs main --
 backend/app/bench/report.py                        |   4 +-
 backend/app/bench/runner.py                        | 123 ++++----
 backend/app/main.py                                |   2 +
 backend/app/negotiation/escalation.py              |  17 +-
 backend/tests/test_actor.py                        |   2 +-
 backend/tests/test_actor_baseline.py               | 186 ++++++++++++
 backend/tests/test_actor_schema.py                 |   8 +-
 backend/tests/test_bench.py                        | 125 +++++++-
 backend/tests/test_fixed_rule.py                   |  69 +++++
 docs/handoff/agents__ali-b5-models-reexport.md     | 105 +++++++
 docs/handoff/agents__ali-b6-single-agent.md        | 117 +++++++
 .../handoff/agents__rohaan-b6-single-agent-main.md |  27 ++
 docs/handoff/backend__rohaan-c6-real-methods.md    |  28 ++
 docs/handoff/sim__rohaan-a4-fixed-rule.md          |  30 ++
 20 files changed, 1568 insertions(+), 374 deletions(-)
```
