# Handoff: agents/ali-b3-router

| Field | Value |
|---|---|
| Branch | `agents/ali-b3-router` (stacked on `agents/ali-b2-actor` → `agents/ali-b1-provider-stubs` → main; PRs #7, #6) |
| Owner | ali |
| Workstream / queue item | agents / B3 (T15 part 1) + §6.7 hash/normalize pulled forward from B4 |
| PRD sections | §6.4–§6.7, §6.10, §4.3, §8.3, D-06, D-08, D-09; FR-024, FR-025, FR-031; AC-003/004/005/024/027/029 |
| Created | 2026-10-10T09:05Z |

## Goal

B3 (PRD §12.3): three actor states, peer routing, evidence disclosure and delivery-time evaluations, working with
the simulator stub. Done = `tests/test_protocol.py` + `test_hash.py` green; the router never ranks; B4 can add the
commit gate and escalation by reading `DecisionPointRecord` in `on_round_end` without touching delivery.

## Current state  (REWRITE this whole section at every handoff)

**Status:** ready for PR (base `agents/ali-b2-actor` until #7 merges; then retarget to `main`)

**Done:**
- `backend/app/negotiation/hash.py` — §6.7 steps 2–4: `hash_input()` reproduces the PRD example byte-for-byte,
  `plan_hash()`, `short()`; covered fields only (no `order/end_step/wait_steps`); assignments sorted by
  `(start_step, resource_id, order)`; `HashInputError` for un-normalized drafts.
- `backend/app/negotiation/normalize.py` — §6.7 step 1 on the **proposer's view**: prepend locked legs, fill empty
  routes with `sim.find_routes(...)[0]`, timing from `sim.plan_timing` (new `SimService` method; stub implemented).
- `backend/app/negotiation/router.py` — `Router.run_decision_point(dp_id, state_version, locked, on_round_end)`:
  rounds via `asyncio.gather`, each actor enforces its own deadline; `deliver()` in canonical order with
  `message_id = {dp}:r{n}:{agent}:{i}`; drop rules DUPLICATE / STALE / UNKNOWN_EVIDENCE / INVALID_REFERENCE /
  NO_CHANGE / INVALID_PLAN / NOT_ALLOWED (round 1); PROPOSE/COUNTERPROPOSE → normalize → hash → `plan_id` in
  delivery order → proposer `Acceptance` (D-09) → per-recipient own-view `evaluate_plan` attached only to that
  recipient's `InboxItem` → authoritative evaluation emitted for the dashboard only; cited/shared evidence →
  `sim.disclose` + `evidence.disclosed`; CHALLENGE/ACCEPT/WITHDRAW/ESCALATE bookkeeping; plan-state counting
  (EVALUATED → CHALLENGED / PARTIALLY_ACCEPTED / UNANIMOUS / WITHDRAWN); `cancel(reason)`; `history_for(agent)`;
  `RouterEvent` sink (types per §8.3 plus `target.revised`).
- `backend/app/agents/actor.py` — a new plan is validated on the proposer's own view inside the turn
  (§6.4 bounce = the one repair). Router keeps a safety-net bounce (`plan.bounced`).
- `backend/app/agents/sim_stub.py` — `SimService.plan_timing(view, assignments, current_step=None)`.
- Tests: `test_hash.py` (16), `test_protocol.py` (17), `test_actor.py` +2 → **106 passing** across WS-B.

**In progress (exact file/function, what's half-finished):**
- Nothing half-written.

**Next steps (ordered, concrete):**
1. Merge chain: #6 → #7 → this PR (retarget each to `main` after its base merges; `git rebase origin/main`).
2. **B4** on `agents/ali-b4-commit-gate` (`negotiation/gate.py`, `negotiation/escalation.py`):
   - `on_round_end(rec)`: `live = rec.live_acceptances(h)` for each open plan; unanimous = 3 distinct agents; order
     by `PlanRecord.first_proposed_seq`; `sim.validate_plan(authoritative view)` → commit via a C-provided
     `apply_accepted_plan` under the run lock with `assert state_version == rec.state_version`; else
     `REJECTED_AT_COMMIT`, void acceptances (`revoked=True`), broadcast violations as `evidence.disclosed via
     commit_rejection` (§4.3). Return `"stop"` on commit. Log `ordering_rule: first_proposed_seq` (§6.8).
   - Escalation triggers (§6.9): round 4 ends without commit; `rec.budget_exceeded`; `rec.escalate_votes[round]`
     ⊇ non-degraded agents; `rec.degraded_agents` non-empty → `AGENT_UNAVAILABLE`. Build `EscalationPackage` from
     `rec.plans[*].evaluations["authoritative"]` (candidates valid on authoritative), F0 from `rec.locked` +
     remaining legs of the last committed plan (needs the committed plan from C).
   - STALE on version change: C calls `router.cancel("event injected")`; the new DP starts at `state_version+1`;
     `deliver(..., current_state_version=sim.world["state_version"])` drops leftovers (hook exists).
   - `test_protocol.py` additions: `test_unanimous_identical_hash`, `test_stale_acceptance`, `test_two_unanimous`
     (AC-028), `test_late_accept`, `test_event_voids_acceptances`, `test_degraded_escalates`, `test_budget_exceeded`.
3. Replace `contracts.py` with `app.models` re-exports when #2 merges; swap `StubSim` for `app.sim` when A3 lands.

**Decisions and why:**
- §6.7 hash + normalization moved from B4 to B3: the router needs `plan_id`/`plan_hash` at delivery (§6.6).
- Proposer-view validation happens **in the actor** (as the repair attempt, inside the deadline) because §6.4 says
  the bounce "is that turn's repair attempt"; doing it only at the boundary would require a model call after the
  deadline. The router still bounces as a safety net so a misbehaving actor cannot deliver an invalid plan.
- INVALID_REFERENCE notices are delivered as the sender's own dropped `AgentMessage` in its next inbox (no new
  prompt block needed; the agent sees `status: dropped, drop_reason`).
- Identical assignments from two agents → same hash → **one** plan with two acceptances (§6.7 step 5).
- ACCEPT may name the 12-char short hash (what the UI shows); resolved to the full hash if unique.
- Delivery `ts` is wall-clock (router is not in `sim/`); `step` comes from the sender's view.
- `target.revised` event type is not in §8.3; emitted anyway (ask below).

**Gotchas / traps:**
- `FakeProvider` infers the round from the prompt's `ROUND: n of 4` line; `prompt.ROUNDS` is 4 even when
  `RouterSettings.rounds` is smaller in tests.
- `Router.deliver()` is public so tests can inject `TurnOutcome`s; it must only be called at a round boundary.
- The actor validates ACCEPT hashes against `open_plans` — pass `open_plans` or the check is skipped (empty set).
- `pending_inbox` is cleared when a round starts; anything the router adds during delivery goes to the *next* round.
- `rec.seq` is the router's local ordering counter (for `first_proposed_seq`), not the §8.3 envelope `seq` (C's).

**How to verify:**
```bash
cd ../rotation-wt/agents__ali-b3-router/backend
uv run --python 3.12 --with pytest --with 'pydantic>=2' --with anthropic --with openai python -m pytest -q tests/test_actor*.py tests/test_hash.py tests/test_protocol.py
cd .. && scripts/check.sh
```

**Asks for other owners (file, owner, what, why):**
- `backend/app/sim/**`, **Madhav**: implement `SimService.plan_timing(view, assignments, *, current_step=None) ->
  list[{start_step, end_step, wait_steps}]` (§7.6 "computed by runtime"; the router must not re-implement travel
  rules) and `disclose(evidence_id, to)` on the evidence store (or tell me where disclosure lives in your service).
- `backend/app/run.py`, **Tisha (C4)**: wire `Router(actors, sim, run_id, scenario_id, sink=<envelope writer>)`;
  `RouterEvent` → §8.3 envelope (`seq`, `ts`, `trace_id = run/dp/r{round}/agent`). On `/events/inject` call
  `router.cancel("event injected")`, apply the event, open the next DP at `state_version+1`. Add `target.revised`
  to the envelope type list (or tell me to fold it into `agent.turn` data) — **Rohaan** shows it as "Target relaxed".
- `backend/app/models.py`, **Tisha**: no field changes needed by B3.

**Open questions (with the PRD's provisional answer if any):**
- Where `apply_accepted_plan` lives (§6.2 says "called only by the commit gate", §12.2 says C applies under the run
  lock). Provisional: gate calls a C-provided callable; B4 defines the signature.
- OPEN-05 credentials still pending; nothing in B3 has run against a live model.

## Session log  (append-only; `scripts/handoff.sh` adds entries)

### 2026-10-10T08:39Z · claude-code · aliharyanawalla
**Status:** B3 done: canonical hash, normalization, router (rounds/delivery/disclosure/own-view evals/drop rules), proposer-view bounce; 106 tests green
```text
HEAD 7fd4967 · behind origin/main: 7
-- commits on branch --
7fd4967 feat(negotiation): router — synchronous rounds, canonical delivery, evidence disclosure, own-view delivery evaluations (PRD §6.4–6.7, §6.10, §4.3)
28d925d feat(agents): validate a new plan on the proposer's own view before submitting (PRD §6.4 bounce-as-repair)
daed503 feat(negotiation): canonical plan hash and delivery-time normalization (PRD §6.7, D-08)
153c63b test(agents): keep redaction fixture below the secret-scan threshold
a038457 docs(agents): B2 handoff — state, next steps for B3, asks for A/C
ee4f827 feat(agents): single actor turn lifecycle with tool loop, repair, deadline, cancellation and ledgers (PRD §6.3, §6.4, §10.1)
c15db53 feat(agents): prompt contract per role with structural evidence isolation (PRD §6.13, §4.4)
7ab3e3e feat(agents): tool implementations on the caller's belief view with injected ToolContext (PRD §6.2, §4.4)
-- uncommitted --
 M docs/handoff/agents__ali-b3-router.md
-- diffstat vs main --
 backend/app/agents/sim_stub.py        |  24 +-
 backend/app/agents/smoke.py           |  53 ++--
 backend/app/agents/tools.py           | 172 ++++++++++++-
 backend/app/negotiation/__init__.py   |   1 +
 backend/app/negotiation/hash.py       |  66 +++++
 backend/app/negotiation/normalize.py  |  64 +++++
 backend/app/negotiation/router.py     | 440 ++++++++++++++++++++++++++++++++++
 backend/tests/test_actor.py           | 259 ++++++++++++++++++++
 backend/tests/test_actor_prompt.py    | 102 ++++++++
 backend/tests/test_actor_tools.py     | 114 +++++++++
 backend/tests/test_hash.py            |  90 +++++++
 backend/tests/test_protocol.py        | 330 +++++++++++++++++++++++++
 docs/handoff/agents__ali-b2-actor.md  | 147 ++++++++++++
 docs/handoff/agents__ali-b3-router.md | 121 ++++++++++
 19 files changed, 2604 insertions(+), 79 deletions(-)
```
