# Handoff: agents/ali-b2-actor

| Field | Value |
|---|---|
| Branch | `agents/ali-b2-actor` (stacked on `agents/ali-b1-provider-stubs`, PR #6) |
| Owner | ali |
| Workstream / queue item | agents / B2 (T11) |
| PRD sections | §6.3, §6.4, §6.13, §4.3–4.4, §10.1–10.5, §6.2; AC-001, AC-024, AC-029 |
| Created | 2026-10-10T08:07Z |

## Goal

B2 (PRD §12.3): one actor runs a complete §6.3 turn — prompt from typed inputs, ≤ 2 tool iterations on its own
belief view, parse, ≤ 1 repair, deadline, cancellation, DEGRADED after two failed turns — against the TEST
PROVIDER and the simulator stub, with call/tool ledgers. Done = `tests/test_actor*.py` green; B3 can compose three
actors without touching this module's internals.

## Current state  (REWRITE this whole section at every handoff)

**Status:** ready for PR (base `agents/ali-b1-provider-stubs` until #6 merges, then retarget to `main`)

**Done:**
- `backend/app/agents/tools.py` — `ToolContext(agent_id, sim, view, run_id, dp_id, history)`, `execute_tool()` →
  `(ToolResult, ToolLedgerRow)`; implementations of `find_routes`, `validate_plan`, `evaluate_plan`,
  `get_negotiation_history` on the caller's view; bad args / unknown ids fail closed as error tool results (§10.3);
  a model-supplied `agent_id` is dropped and recorded in `ToolLedgerRow.ignored_args` (§4.4 #2);
  `draft_plan_hash()` for tool-call evaluation ids (B4's canonical hash replaces it at delivery).
- `backend/app/agents/prompt.py` — `ROLE_SPECS` (§6.1), `DEFAULT_TARGETS` (§5.12), `build_system_prompt()`
  (§6.13 SYSTEM incl. relaxed aspirations), `build_observation()` (§7.4 from a `BeliefView`),
  `build_user_prompt()` (OBSERVATION / INBOX / OPEN PLANS / ROUND / OUTPUT), `build_repair_prompt()`,
  `no_more_tools_note()`, `InboxItem`, `OpenPlan`.
- `backend/app/agents/actor.py` — `ActorState` (private; aspirations, failures, degraded, revisions),
  `TurnInput`, `TurnOutcome` (status `submitted|silent|failed|degraded|late|cancelled`, turn, errors, ledger rows,
  transcript), `Actor.run_turn()`: ≤ 4 model calls, ≤ 2 tool iterations, ≤ 4 tool executions, 1 repair, 1 provider
  retry, `asyncio.timeout(deadline)` → `late`, `CancelledError` recorded then re-raised, 2 failed turns → DEGRADED.
- `backend/app/agents/ledger.py` — `CallLedger`, `ToolLedger` (`append/extend/totals/write_jsonl`), `redact()` for
  `sk-…` patterns (§10.4). Actors return rows; persistence belongs to the run controller/router.
- `provider_fake.py` — scripts are now per-call step lists: dict output, `ToolCalls`, `Refuse`, `Truncate`, `Fail`;
  `delay_s` for deadline/cancellation tests; round parsed from the prompt's `ROUND:` line (no `set_round` needed).
- `smoke.py` — uses the real `prompt.py` builders (T05 measures the production prompt). Still PENDING: no keys.
- `schema.py` — `parse_assignment_drafts()` public.
- Tests: `test_actor_tools.py` (8), `test_actor_prompt.py` (6), `test_actor.py` (15) + B1's 42 = **71 passing**.
  Covers: tool loop on caller's view (AC-024), tool-budget cap, repair, un-held evidence, DEGRADED (AC-029),
  refusal/truncation, deadline → late, cancellation recorded, retry, three-actor isolation (AC-001/AC-025 slice),
  ledgers + redaction.

**In progress (exact file/function, what's half-finished):**
- Nothing half-written.

**Next steps (ordered, concrete):**
1. Merge #6 (B1), then retarget this PR to `main` and rebase (`git rebase origin/main`).
2. When Tisha's C1 (#2) merges: `contracts.py` → re-exports from `app.models`; delete duplicated A/C types; run the
   suite. When A3 merges: pass `app.sim`'s service in place of `StubSim` (same `SimService` signature).
3. **B3** on `agents/ali-b3-router`: `negotiation/router.py` — three `Actor`s, synchronous rounds via
   `asyncio.gather` with per-task deadlines (§6.4), canonical delivery order, dedupe by `message_id`
   (`{dp_id}:r{round}:{agent}:{index}`), §6.10 drop rules (LATE/DUPLICATE/STALE/INVALID_REFERENCE), evidence
   disclosure on cite/share (`StubSim.disclose`), delivery-time validate+evaluate on **each recipient's** view
   (FR-024, attach as `InboxItem.evaluation`), `plan.bounced` for proposer-view-invalid plans, `get_negotiation_history`
   callable restricted to sent/received. Router must not import evaluator/metrics for ranking (FR-031 lint test).
   `negotiation/normalize.py` (§6.7 step 1) + `negotiation/hash.py` (§6.7 steps 2–4, `test_hash.py`) are B4 but the
   router needs plan ids/hashes at delivery — do hash first in B4 or pull it forward.
4. With a key: run smoke, then one real `Actor.run_turn` against the live provider (`provider=get_provider(...)`)
   and tune `prompt.py` wording only (structure is fixed by §6.13).

**Decisions and why:**
- Prompt isolation is structural: `build_user_prompt` takes an `Observation` built from the `BeliefView` plus
  own-view evaluations; it cannot reach the evidence store (§4.4 #1). The leak test checks per-agent private markers
  (`E-LOG-01`, `CLOSED_CLEARABLE`, `"firebreak_bonus":true`, …) across all three prompts.
- Refusal / truncation / non-JSON / tool-call-after-budget are all "malformed" → one repair → failed turn (§10.1).
  Nothing synthesizes a turn.
- The actor returns ledger rows instead of writing files: `runs/<run_id>/` layout is WS-C's (`store.py`).
- Timeout is the turn deadline via `asyncio.timeout`; the in-flight call row is relabeled `timeout`. Cancellation
  re-raises after recording so the router's `gather` sees a real cancellation (§4.6, FR-041).
- Target revisions are *returned* in the turn and applied by the router at the round boundary
  (`ActorState.apply_revision`), per §6.11 "take effect for evaluations delivered after the round boundary".
- `TurnInput.history` is a callable the router supplies, already filtered to the caller's sent/received messages.

**Gotchas / traps:**
- `FakeProvider` step lists repeat their last step once exhausted; call `reset_progress()` between turns in tests
  that reuse one provider and expect the sequence to restart.
- `TurnContext.known_plan_ids` / `current_plan_hashes` come from `TurnInput.open_plans`; with no open plans the
  reference checks are skipped (empty set = "unknown universe"), so the router must always pass the open plans.
- `Actor.run_turn` on a DEGRADED actor returns immediately with status `degraded`; the router must treat it as
  "unanimity impossible" (§6.9 trigger 4), not as silence.
- `ActorState.turns_run` counts attempts including late/cancelled; `consecutive_failures` counts only failed/late.
- `horizon` is read from `view.world["horizon"]` (stub puts it there); the real belief view must carry it too, or
  pass 60.

**How to verify:**
```bash
cd ../rotation-wt/agents__ali-b2-actor/backend
uv run --python 3.12 --with pytest --with 'pydantic>=2' --with anthropic --with openai python -m pytest -q tests/test_actor*.py
cd .. && scripts/check.sh
```

**Asks for other owners (file, owner, what, why):**
- `backend/app/sim/**`, **Madhav**: the belief view your service returns must expose `basis`, `state_version`,
  `step`, `held_evidence`, and a `world` dict that includes `horizon`, `nodes`, `resources` — the actor reads those
  (`actor.py::_turn`, `tools.py::_find_routes`). Keep the `SimService` method signatures from `sim_stub.py`.
- `backend/app/store.py`, **Tisha**: `ledger.CallLedger.write_jsonl(runs/<run_id>/calls.jsonl)` and
  `ToolLedger.write_jsonl(runs/<run_id>/tools.jsonl)` produce the §10.5 rows; call them from the run controller
  instead of defining a second row format. `TurnOutcome.transcript` is the prompt-capture payload for
  `runs/<run_id>/prompts/` in benchmark/debug mode.

**Open questions (with the PRD's provisional answer if any):**
- §6.4 says "Messages per turn ≤ 3, of which ≤ 1 PROPOSE or COUNTERPROPOSE"; the sentinel schema cannot enforce
  counts, so both are post-parse semantic errors → repair. Confirmed by §3.5 ("all bounds enforced by Pydantic after
  parsing"). No open question remains.
- OPEN-05 credentials still pending; the actor has not run against a live model.

## Session log  (append-only; `scripts/handoff.sh` adds entries)

### 2026-10-10T08:20Z · claude-code · aliharyanawalla
**Status:** B2 done: tools on belief view, prompt contract, actor lifecycle (tool loop/repair/deadline/cancel/degraded), ledgers; 71 tests green
```text
HEAD ee4f827 · behind origin/main: 0
-- commits on branch --
ee4f827 feat(agents): single actor turn lifecycle with tool loop, repair, deadline, cancellation and ledgers (PRD §6.3, §6.4, §10.1)
c15db53 feat(agents): prompt contract per role with structural evidence isolation (PRD §6.13, §4.4)
7ab3e3e feat(agents): tool implementations on the caller's belief view with injected ToolContext (PRD §6.2, §4.4)
50911df docs(agents): record G0 contract review of C1 models.py
c74c0c2 docs(agents): reword key variable names so the secret scan passes
ef2cab0 docs(agents): B1 handoff — state, asks for C1/A1, pending live smoke
b6d2f56 feat(agents): Anthropic and OpenAI adapters, tool specs and T05 smoke script (PRD §3.5, D-03)
ae40315 feat(agents): typed simulator stub with belief masking and structural validation (PRD §12.2, §5.9)
27a4081 feat(agents): provider interface, settings and labeled TEST PROVIDER (PRD §3.5, §11.5)
4940a8a chore: commit executable bit on git hooks and scripts
4beca7a feat(agents): WS-B contracts and sentinel turn schema (PRD §7.5, D-17)
-- uncommitted --
 M docs/handoff/agents__ali-b2-actor.md
-- diffstat vs main --
 backend/tests/test_actor_provider_fake.py     | 120 +++++++++
 backend/tests/test_actor_providers.py         | 152 +++++++++++
 backend/tests/test_actor_schema.py            | 235 +++++++++++++++++
 backend/tests/test_actor_sim_stub.py          | 119 +++++++++
 backend/tests/test_actor_tools.py             | 114 +++++++++
 docs/handoff/agents__ali-b1-provider-stubs.md | 150 +++++++++++
 docs/handoff/agents__ali-b2-actor.md          | 131 ++++++++++
 scripts/check.sh                              |   0
 scripts/claude-guard-branch.sh                |   0
 scripts/claude-session-start.sh               |   0
 scripts/handoff.sh                            |   0
 scripts/lib.sh                                |   0
 scripts/setup.sh                              |   0
 scripts/start-task.sh                         |   0
 31 files changed, 3868 insertions(+)
```
