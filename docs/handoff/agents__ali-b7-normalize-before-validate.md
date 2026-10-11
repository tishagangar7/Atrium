# Handoff: agents/ali-b7-normalize-before-validate

| Field | Value |
|---|---|
| Branch | `agents/ali-b7-normalize-before-validate` |
| Owner | ali |
| Workstream / queue item | agents / B7 (answers the WS-B ask in `backend__tisha-first-live-benchmark.md`) |
| PRD sections | §6.4 (bounce-as-repair, budgets), §6.7 step 1 (normalization), §6.2 (tools), §6.5 (ACCEPT/CHALLENGE), §6.8 (gate), §6.9 (F0), §6.13 (prompt), §10.1 (one repair), §10.2 / NFR-004 (token cap), §11.2 (baseline fairness), §5.8 (locked legs), §4.3 (commit rejection) |
| Created | 2026-10-11T10:55Z |

## Goal

Three live agents negotiate through all four rounds and commit a plan the authoritative gate accepts, and
`runs/results.csv` carries a real batch produced by this code. **Commits reached on 2026-10-11**; the batch is
**11 of 36 rows done** (sonnet-5-5) and paused because the Anthropic credit balance ran out mid-batch.

## Current state  (REWRITE this whole section at every handoff)

**Status:** PR #54 open, ready for review/merge. 327 backend tests pass **with a real `backend/.env` present** (bench
and provider tests are now pinned to the TEST PROVIDER). `runs/results.csv` holds **19 real rows**: all 12
`fixed_rule` (free, deterministic), 4 `single_agent`, 3 `rescuemesh` (sonnet-5-5, **3/3 decision points committed**,
lowest civilian exposure on every normal seed). 17 model rows remain; they need any funded Anthropic key (≈ $1-2 on
haiku-5-5, ≈ $20-25 on sonnet-5-5), commands in `docs/bench/README.md`. Ali has no credits left.
**Demo is zero-cost and verified end to end**: the three committed negotiations ship in `runs/fixtures/` (tracked,
replayable on any clone; `store.py` reads fixtures), and I drove the real dashboard through the replay with
Playwright: REPLAY label + watermark, agent cards "Accepts P5/P6", Proposals 6, Activity 19 ending in "All three
accepted P4 – committed" (`docs/bench/dashboard-replay-normal-s2.png`).
Done on others' behalf (Ali's instruction, all flagged in the PR): Tisha's asks (commit counting, runner logging,
`.env.example`, test pinning, handoff correction, `docs/bench/results.md`), Rohaan's dashboard check plus a fix in
`frontend/src/App.tsx::connect` (a fresh backend has no run, so "Connect simulator" failed with "No active run was
found, start the backend"; it now resets the selected preset on NOT_FOUND).

| normal, per method (3 seeds) | commits/dps | mean assisted completion | mean civilian exposure |
|---|---|---|---|
| fixed_rule | 3/3 | 1.00 | 813 |
| single_agent (sonnet-5-5) | 3/3 | 0.88 | 713 |
| rescuemesh (sonnet-5-5) | 3/3 | 0.91 | 687 |

**What blocked a commit, in the order found (each reproduced live, each fixed on this branch):**

1. **Actor and tools validated the raw draft; the router validates the normalized plan** (§6.7). Every open-form
   plan bounced as `WRONG_LOCATION` / `RESOURCE_DOUBLE_BOOKED` before delivery; the one repair was wasted.
2. **The model was never told the plan format.**
3. **§6.4 budgets (120k tokens / 30 s) end every live decision point after round 1**; ACCEPT needs round ≥ 2.
4. **Model tier.** haiku-4-5 never wrote a valid plan; haiku-5-5 commits ~1 in 3 on normal/s1; sonnet-5-5 committed
   first try and 3/3 in the batch.
5. **Agents accepted plans their own evidence said would fail** → UNANIMOUS → `REJECTED_AT_COMMIT`. `OPEN PLANS` now
   carry `valid_on_my_view` / `my_view_violations`; prompt: never ACCEPT an invalid one, cite the evidence.
6. **Output cap 4096** truncated full plans on a thinking-by-default model → 16000.
7. "single_agent commits reliably" in the earlier handoff was a counting bug (`bench/methods.py:215`).
8. **Locked legs were projected to bare drafts before validation** (`_drafts()` in router, escalation, baseline,
   `PlanRecord.drafts`, and my `tools.drafts_of`). The validator recognizes a vehicle already on an edge only via
   `locked=True` + `end_step` (`sim/plans.py:95`); stripped, the leg is a drive from nowhere starting in the past.
   Live effect on `wind_shift` after the first commit: every plan of dp-2 bounced, three unanimous plans were
   rejected at the gate, and F0 itself failed validation so `_commit_fallback` raised `PlanInfeasible` and the whole
   benchmark died (`BENCHMARK_FAILED`, run 12). Fix: `tools.drafts_of` keeps locked `Assignment`s intact and every
   `_drafts` helper delegates to it. Regression test
   `test_actor.py::test_mid_edge_locked_legs_validate_and_f0_stays_feasible_after_a_commit` (real simulator).

**Done (files):**
- WS-B: `app/agents/{actor,tools,schema,prompt,provider}.py`, `app/baselines/single_agent.py`,
  `app/negotiation/router.py` (`_open_plans_for` fields, `_drafts` → `drafts_of`, `PlanRecord.drafts`),
  `app/negotiation/escalation.py` (`_drafts` → `drafts_of`).
- **Cross-ownership one-liners by Ali's explicit instruction** (flagged): `app/bench/methods.py:172` and
  `app/negotiation_session.py:142` pass `dp_budget_s` / `dp_max_tokens` into `RouterSettings`.
- Tests +13 (326 pass). `docs/bench/results-2026-10-11-pre-b7-haiku-4-5.csv`, `docs/bench/results-2026-10-11-partial-haiku-5-5.csv`.
- `runs/results.csv`: 11 sonnet rows (reset to header before the batch; the runner appends).

**Live config that produced the commits (`backend/.env`, never committed):** `MODEL_PROVIDER=anthropic`,
`RESCUEMESH_MODEL=claude-sonnet-5-5`, `RESCUEMESH_TURN_DEADLINE_S=90`, `RESCUEMESH_DP_BUDGET_S=480`,
`RESCUEMESH_DP_MAX_TOKENS=800000`. A decision point is 100-150 s, 300-450k tokens (≈ $0.85 on sonnet, ≈ $0.04 on
haiku-5-5). Batch so far: 1.45M input + 143k output tokens.

**Next steps (ordered, concrete):**
1. **Ali: add Anthropic credits** (≈ $20-25 covers the remaining 25 rows on sonnet-5-5; ≈ $1 on haiku-5-5 but it
   converges less reliably). Then, from `backend/` with `.env` in place:
   ```bash
   uv run uvicorn app.main:app --port 8000 &
   # rows missing from runs/results.csv; one POST at a time (409 while running), check GET /benchmarks/<id>
   curl -s -X POST localhost:8000/benchmarks/run -H 'content-type: application/json' \
     -d '{"presets":["wind_shift"],"seeds":[1],"methods":["rescuemesh"]}'
   curl -s -X POST localhost:8000/benchmarks/run -H 'content-type: application/json' \
     -d '{"presets":["wind_shift"],"seeds":[2,3],"methods":["fixed_rule","single_agent","rescuemesh"]}'
   curl -s -X POST localhost:8000/benchmarks/run -H 'content-type: application/json' \
     -d '{"presets":["road_closure","compound_failure"],"seeds":[1,2,3],"methods":["fixed_rule","single_agent","rescuemesh"]}'
   ```
   Discard any model row with zero tokens (invariant 9). Commit `runs/results.csv` on this branch.
2. Tisha: fix `bench/methods.py:215` (count only `decision.status == "committed"`), re-render the report, add the
   budget keys and the model line to `.env.example`, pin bench tests to the TEST PROVIDER.
3. Rohaan: dashboard check with a live decision point (100-150 s, 4 rounds; events already emitted: `plan.proposed`,
   `message.delivered` CHALLENGE/ACCEPT, `plan.state` PARTIALLY_ACCEPTED/UNANIMOUS/COMMITTED, `evidence.disclosed`).
   Record one clean run for REPLAY as the demo safety net (§13.3).
4. If `BenchmarkRunner` fails again: it swallows the exception (`runner.py:125`). Reproduce with
   `methods.run_model_method(...)` directly to see the traceback (the scratch script did exactly that).

**Decisions and why:** see PR #54 body. Key ones: normalize inside the actor/tools rather than relaxing §6.4; budget
knobs with PRD defaults (deviation recorded, not defaulted); `compact_cells` keeps active, firebreak and off-modal-fuel
cells in full (AC-025 markers); own-view validity on `OpenPlan` is data the router already computed; locked legs stay
`Assignment` objects everywhere the simulator validates.

**Gotchas / traps:**
- **Never run the full pytest suite with a real `backend/.env` present** (`test_bench.py` starts live rescuemesh
  runs). `mv .env .env.off; uv run pytest -q; mv .env.off .env`.
- The benchmark appends to `runs/results.csv`. Credit exhaustion shows up as `AGENT_UNAVAILABLE` after 1-call turns
  (HTTP 400 "credit balance is too low"), not as a clear error.
- `StubSim` does not check `origin != node`; use `SimulatorService` for location tests.
- Actor `consecutive_failures` persist across decision points (one failure in dp-1 + one in dp-2 = DEGRADED).

**How to verify:**
```bash
cd backend
mv .env .env.off; RESCUEMESH_TEST=1 uv run pytest -q; mv .env.off .env      # 326 passed
```

**Asks for other owners:** none. Per Ali, everything cross-workstream was fixed directly on this branch
(`bench/methods.py` counting + budget wiring, `bench/runner.py` logging, `store.py` fixtures, `.env.example`,
bench/health/negotiate/replay test pinning, `negotiation_session.py` budget wiring, `frontend/src/App.tsx` connect,
the benchmark handoff correction, `docs/bench/`).

**Demo without credits (Anthropic balance is 0; Gemini free tier 429s within one round):** use REPLAY (§13.3,
invariant 8: labeled). The recorded sonnet-5-5 runs are real negotiations with commits. Verified via the API: the
replay of `normal` s2 serves 101 envelopes, all `mode: replay`, incl. 6 `plan.proposed`, 10 `message.delivered`
(3 PROPOSE, 3 COUNTERPROPOSE, 4 ACCEPT), 18 `evidence.disclosed`, 1 `plan.committed`.
```bash
cd backend && uv run uvicorn app.main:app --port 8000 &          # needs no credits for replay
curl -s -X POST localhost:8000/replay/bench-20261011T115655Z-3ff42ddd-normal-s2-rescuemesh \
  -H 'content-type: application/json' -d '{"speed": 2}'            # speed 1|2|4; or pick the run in the dashboard
```
Best story: **normal s2** (LOG: "P1 and P2 route through closed R2 (E-LOG-01). C1 clears R2 first; B1 takes VJ to SS,
B2 takes VJ to SE" → EVAC and FIRE counter-propose on top → P4 unanimous → committed, 3 rounds). Alternatives:
normal s3 (4 rounds, 4 counter-proposals, P6 committed), normal s1 (LOG counter fixes R2 + shelter beds, P4 committed).
The run directories under `runs/` are git-ignored: **copy `runs/bench-20261011T115655Z-3ff42ddd-normal-s{1,2,3}-rescuemesh/`
to the demo laptop** (or add them under `runs/fixtures/`, Tisha's call) or the replays will not exist there.

**Open questions (with the PRD's provisional answer if any):**
- §6.4 / NFR-004 budgets vs. reality (100-150 s, 300-450k tokens): keep PRD defaults in code, run live with env
  knobs, state the deviation in results notes and the demo.
- §6.7 explicit `start_step` earlier than the resource is free: pushed, not flagged (router and actor agree).

## Session log  (append-only; `scripts/handoff.sh` adds entries)

### 2026-10-11T12:27Z · claude-code · aliharyanawalla
**Status:** B7: locked legs reach the validator intact (gate/F0/actor); 11 real sonnet-5-5 rows, rescuemesh 3/3 commits on normal; batch paused — Anthropic credits exhausted
```text
HEAD 9b41440 · behind origin/main: 0
-- commits on branch --
9b41440 fix(agents): evidence_ids hold held evidence only; keep partial haiku-5-5 batch rows
f4c017f feat(agents): live three-agent negotiation commits — budgets, plan-for-all prompt, own-view validity on open plans
6e52605 fix(agents): judge plans as delivered — normalize before the own-view check, tell the model the plan format
-- uncommitted --
 M app/agents/tools.py
 M app/baselines/single_agent.py
 M app/negotiation/escalation.py
 M app/negotiation/router.py
 M tests/test_actor.py
 M ../docs/handoff/agents__ali-b7-normalize-before-validate.md
 M ../runs/results.csv
-- diffstat vs main --
 backend/app/baselines/single_agent.py              |   8 +-
 backend/app/bench/methods.py                       |   5 +-
 backend/app/negotiation/escalation.py              |   6 +-
 backend/app/negotiation/router.py                  |  16 ++-
 backend/app/negotiation_session.py                 |   4 +-
 backend/tests/test_actor.py                        | 124 ++++++++++++++++++
 backend/tests/test_actor_prompt.py                 |  25 +++-
 backend/tests/test_actor_provider_fake.py          |   8 ++
 backend/tests/test_actor_schema.py                 |  25 ++++
 backend/tests/test_actor_tools.py                  |  48 +++++++
 .../bench/results-2026-10-11-partial-haiku-5-5.csv |   8 ++
 docs/bench/results-2026-10-11-pre-b7-haiku-4-5.csv |  37 ++++++
 .../agents__ali-b7-normalize-before-validate.md    | 139 +++++++++++++++++++++
 runs/results.csv                                   |  47 ++-----
 19 files changed, 633 insertions(+), 76 deletions(-)
```

### 2026-10-11T14:58Z · claude-code · aliharyanawalla
**Status:** B7 final: 19/36 real rows, fixtures + replay demo verified on the dashboard, Tisha's asks done, suite safe with real .env; remaining 17 model rows need any funded key
```text
HEAD 1bcc909 · behind origin/main: 0
-- commits on branch --
1bcc909 docs(agents): B7 handoff — zero-cost demo via replay of the recorded sonnet runs
6b2281e fix(negotiation): locked legs reach the validator intact; first real benchmark rows with rescuemesh commits
9b41440 fix(agents): evidence_ids hold held evidence only; keep partial haiku-5-5 batch rows
f4c017f feat(agents): live three-agent negotiation commits — budgets, plan-for-all prompt, own-view validity on open plans
6e52605 fix(agents): judge plans as delivered — normalize before the own-view check, tell the model the plan format
-- uncommitted --
 M .env.example
 M app/agents/provider.py
 M app/bench/methods.py
 M app/bench/runner.py
 M app/store.py
 M tests/test_actor_provider_fake.py
 M tests/test_bench.py
 M tests/test_health.py
 M tests/test_negotiate.py
 M tests/test_replay.py
 M ../docs/handoff/agents__ali-b7-normalize-before-validate.md
 M ../docs/handoff/backend__tisha-first-live-benchmark.md
 M ../frontend/src/App.tsx
 M ../runs/results.csv
?? ../docs/bench/README.md
?? ../docs/bench/dashboard-replay-normal-s2.png
?? ../docs/bench/results.md
?? ../runs/fixtures/
-- diffstat vs main --
 backend/tests/test_actor_prompt.py                 |  25 ++-
 backend/tests/test_actor_provider_fake.py          |  16 +-
 backend/tests/test_actor_schema.py                 |  25 +++
 backend/tests/test_actor_tools.py                  |  48 +++++
 backend/tests/test_bench.py                        |   7 +-
 backend/tests/test_health.py                       |   6 +-
 backend/tests/test_negotiate.py                    |   7 +-
 backend/tests/test_replay.py                       |  20 ++
 .../bench/results-2026-10-11-partial-haiku-5-5.csv |   8 +
 docs/bench/results-2026-10-11-pre-b7-haiku-4-5.csv |  37 ++++
 .../agents__ali-b7-normalize-before-validate.md    | 209 +++++++++++++++++++++
 .../handoff/backend__tisha-first-live-benchmark.md |   6 +
 frontend/src/App.tsx                               |  10 +-
 runs/results.csv                                   |  55 ++----
 28 files changed, 812 insertions(+), 92 deletions(-)
```
