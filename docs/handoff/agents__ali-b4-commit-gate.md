# Handoff: agents/ali-b4-commit-gate

| Field | Value |
|---|---|
| Branch | `agents/ali-b4-commit-gate` (stacked on `agents/ali-b3-router` → b2 → b1 → main; PRs #8, #7, #6) |
| Owner | ali |
| Workstream / queue item | agents / B4 (T15 part 2, T16/T17 agent side) |
| PRD sections | §6.8, §6.9, §6.10, §6.11, §5.8, §7.7, §8.2, D-14; FR-030/032/033/034/040/041/050/051/052; AC-006/007/027/028/029/032/033 |
| Created | 2026-10-10T09:20Z |

## Goal

B4 (PRD §12.3): unanimous commit gate, escalation package + F0, human/benchmark resolution, version voiding and
cancellation — as a `NegotiationService` WS-C can call from `/negotiate`, `/negotiate/cancel`, `/events/inject`
and `/escalations/{dp}/resolve`. Done = every decision point ends COMMITTED or ESCALATED (or is cancelled by an
event); stale/silent/late agents never count as acceptance; 120 WS-B tests green.

## Current state  (REWRITE this whole section at every handoff)

**Status:** PR #11 open (base `agents/ali-b3-router` until #8 merges into `main`; then retarget to `main`)

**Done:**
- `backend/app/negotiation/gate.py` — `CommitGate.check(rec, emit)`: live acceptances (dp, version, not revoked) →
  unanimous hashes → ordered by `first_proposed_seq` only → `sim.validate_plan(authoritative)` → version assert →
  `apply(assignments, hash)` → `Commit(authority="unanimous", ordering_rule="first_proposed_seq", 3 acceptances)`;
  invalid → `REJECTED_AT_COMMIT`, acceptances voided, violation codes broadcast as `rec.notices` (all agents) +
  `evidence.disclosed{via: commit_rejection}`. `StaleDecisionPoint` if the world moved. `gate.commit()` is reused
  for human choices.
- `backend/app/negotiation/escalation.py` — `escalation_trigger()` (PRD precedence: ROUNDS_EXHAUSTED,
  BUDGET_EXCEEDED, ALL_ESCALATED, AGENT_UNAVAILABLE), `build_fallback()` (F0 = locked + still-valid remaining legs of
  the last committed plan, else locked only), `build_package()` (candidates = plans valid authoritatively;
  per-candidate checks; unmet aspirations per agent; latest unanswered CHALLENGE per agent; blocking constraints
  from invalid plans, commit rejections and floors unmet by every candidate).
- `backend/app/negotiation/service.py` — `NegotiationService`: `start_decision_point(state_version, locked)` →
  `DecisionPointResult(status committed|escalated|cancelled|stale, commit, escalation, record)`; `cancel()`;
  `on_event_applied(new_version)` (cancel in-flight, `mark_stale`, close open escalation);
  `resolve(dp_id, choice, expected_state_version, plan_hash|target_revisions)` → `Commit` or `NewDecisionPoint`;
  `mode="benchmark"` auto-commits F0 with `authority="auto_fallback"` (D-14). Exceptions map to §8.2 errors:
  `NegotiationInProgress`→409, `NoActiveEscalation`→409, `PlanInfeasible`→422, `ValueError`→422 INVALID_REQUEST.
- Router: `DecisionPointRecord.{notices, outcome, commit, escalation, rejections, fallback_*}`, `mark_stale()`;
  actor/prompt: `TurnInput.notices` → `NOTICES:` block (only when non-empty); `SimService.apply_accepted_plan`.
- Tests (`test_protocol.py` +14): `test_unanimous_identical_hash`, `test_near_identical`, `test_two_unanimous`,
  `test_rejected_at_commit_broadcasts_violations`, `test_late_accept`, degraded → AGENT_UNAVAILABLE,
  ALL_ESCALATED, BUDGET_EXCEEDED, package + F0, `test_human_resolve_limits`, fallback + relax,
  `test_benchmark_auto_fallback`, `test_event_voids_acceptances`, `test_inject_mid_round`.
- Rebased onto `main` after #2/#4/#6 merged (Tisha's `pyproject.toml`, `models.py`, run controller now present).
  With the project venv (`cd backend && uv run pytest -q`): **143 passed, 1 skipped** (adapter tests skip until
  `anthropic`/`openai` are in `pyproject.toml`); with `uv run --with anthropic --with openai pytest -q`: **150 passed**.
- `test_actor_providers.py` uses `pytest.importorskip` so the team's `scripts/check.sh` doesn't fail on missing SDKs;
  `Settings.from_env` accepts `MODEL_PROVIDER` (the name in `.env.example`) as an alias for `RESCUEMESH_PROVIDER`.
- Merge-order note: #7 (B2) was merged into its stacked base, not `main`; #8 (B3) is retargeted to `main` and
  carries B2+B3 (`MERGEABLE/CLEAN`). This PR (#11) stays on #8's branch until #8 merges.

**In progress (exact file/function, what's half-finished):**
- Nothing half-written.

**Next steps (ordered, concrete):**
1. Merge chain #6 → #7 → #8 → this PR (retarget bases as predecessors merge; rebase on `origin/main`).
2. **B5 (live disruption integration, with Tisha's C4):** C4 wires `NegotiationService` into `run.py` — see
   "Asks". My side: a `backend/app/agents/health.py` helper for `/health.model_available` (reads
   `Settings.from_env()`), and once a key exists, one live run on `normal` through the service; tune prompt wording
   only.
3. **B6:** `backend/app/baselines/single_agent.py` — one `Actor` on `build_belief_view("union")` with the same
   tools/schema, matched (48 calls/120k) and natural (8 calls) budgets; outputs one plan → authoritative validate →
   apply; tests `test_actor_isolation`-style for budgets/deadlines.
4. Replace `contracts.py` with `app.models` re-exports when #2 merges; swap `StubSim` for `app.sim` when A3 lands.

**Decisions and why:**
- Gate ordering is `first_proposed_seq` only; no metric is read anywhere in `gate.py`/`escalation.py`'s choice of
  commit (escalation only *reports* target checks). Lint test for the router covers FR-031; the gate is reviewed by
  reading (it has no `Metrics` import either).
- Commit-rejection broadcast uses `TurnInput.notices` (a labeled data block) rather than fabricated inbox messages,
  so the fact reaches every agent without anyone "sending" it (§4.3 "a physical fact discovered by trying to act").
- `AGENT_UNAVAILABLE` and `ALL_ESCALATED` end the DP at the round boundary they occur in (unanimity impossible /
  everyone asked); `ROUNDS_EXHAUSTED`/`BUDGET_EXCEEDED` only after the last round / at a boundary (§6.9).
- `on_event_applied` marks the DP `stale` (distinct from operator `cancelled`) so C can tell "restart at
  version+1" from "user aborted".
- F0 is carried as `rec.fallback_assignments` + hash, not a `Plan` (needs a `proposer`, which F0 has no agent for).
  Commit for F0 uses `plan_id = "{dp_id}:F0"`.
- Human `relax` validates every revision before applying any (no partial state on a 422).

**Gotchas / traps:**
- `gate.check` must run under C's run lock together with `apply` (§6.8 "holding the run lock"); the service calls
  it synchronously inside `on_round_end`, so C should run `start_decision_point` while holding the lock or make
  `apply` acquire it.
- `escalation_trigger` reads `rec.round >= rounds`; `budget_exceeded` is set when a *new* round can't start, so the
  service computes the trigger after `run_decision_point` returns as well as at round ends.
- `resolve(..., plan_hash=)` accepts the 12-char short hash shown in the UI if it is unique.
- `results[dp_id].status` flips to `"stale"` when an event lands while its escalation is open — the UI's
  escalation panel must close (`plan.state STALE` events are emitted for every open plan).
- `DEFAULT_TARGETS` are used unless `targets=` is passed; the runtime must pass the scenario's targets.

**How to verify:**
```bash
cd ../rotation-wt/agents__ali-b4-commit-gate/backend
uv run --python 3.12 --with pytest --with 'pydantic>=2' --with anthropic --with openai python -m pytest -q tests/test_actor*.py tests/test_hash.py tests/test_protocol.py
cd .. && scripts/check.sh
```

**Asks for other owners (file, owner, what, why):**
- `backend/app/run.py` + `main.py`, **Tisha (C4)**: construct `NegotiationService(actors, sim, run_id=…,
  scenario_id=…, sink=<RouterEvent→envelope>, settings=RouterSettings(), mode="live"|"benchmark",
  apply=<your apply_accepted_plan under the run lock>, targets=scenario.targets)`. Endpoint mapping is in the
  `service.py` module docstring; exception → HTTP mapping above. `/events/inject`: apply event → `sim` version+1 →
  `service.on_event_applied(v)` → `start_decision_point(v, locked=<A's locked legs>)` if `auto_negotiate`.
  Envelope types to add to §8.3's list: `target.revised`; `evidence.disclosed` may carry `via: "commit_rejection"`.
- `backend/app/sim/**`, **Madhav**: implement `apply_accepted_plan(assignments, plan_hash) -> state_version`
  (expand legs §5.8, set `committed_plan_hash`, `state_version += 1`) and return the DP's **locked legs** at a pause
  so the service can pass `locked=`.
- `backend/app/models.py`, **Tisha** (post-G0 `[contract]`): F0 needs a `Plan` for `Snapshot.committed_plan`;
  `Plan.proposer` is `AgentId` only. Proposal: allow `Literal["fallback"]` or make `committed_plan` carry
  `assignments` + `plan_hash` without a proposer. Not blocking B4.

**Open questions (with the PRD's provisional answer if any):**
- Human-relaxed targets apply to the agent's `ActorState.aspirations` for the rest of the run (§6.11 says
  revisions "take effect for evaluations delivered after the round boundary"); provisional: persist until reset.
- OPEN-05 credentials still pending — no live model has run through the gate.

## Session log  (append-only; `scripts/handoff.sh` adds entries)

### 2026-10-10T08:52Z · claude-code · aliharyanawalla
**Status:** B4 done: unanimous gate, escalation package + F0, negotiation service, version voiding; 120 tests green
```text
HEAD e283e65 · behind origin/main: 7
-- commits on branch --
e283e65 feat(negotiation): unanimous commit gate, escalation package with F0, negotiation service (PRD §6.8, §6.9, §8.2)
8ac4c68 feat(agents): apply_accepted_plan contract, router notices and stale marking for the commit gate (PRD §6.2, §4.3, FR-040)
cf7a585 docs(agents): B3 handoff — state, B4 plan, asks for A/C
7fd4967 feat(negotiation): router — synchronous rounds, canonical delivery, evidence disclosure, own-view delivery evaluations (PRD §6.4–6.7, §6.10, §4.3)
28d925d feat(agents): validate a new plan on the proposer's own view before submitting (PRD §6.4 bounce-as-repair)
daed503 feat(negotiation): canonical plan hash and delivery-time normalization (PRD §6.7, D-08)
153c63b test(agents): keep redaction fixture below the secret-scan threshold
a038457 docs(agents): B2 handoff — state, next steps for B3, asks for A/C
ee4f827 feat(agents): single actor turn lifecycle with tool loop, repair, deadline, cancellation and ledgers (PRD §6.3, §6.4, §10.1)
c15db53 feat(agents): prompt contract per role with structural evidence isolation (PRD §6.13, §4.4)
7ab3e3e feat(agents): tool implementations on the caller's belief view with injected ToolContext (PRD §6.2, §4.4)
-- uncommitted --
?? docs/handoff/agents__ali-b4-commit-gate.md
-- diffstat vs main --
 backend/app/negotiation/__init__.py   |   1 +
 backend/app/negotiation/escalation.py | 135 ++++++++
 backend/app/negotiation/gate.py       | 116 +++++++
 backend/app/negotiation/hash.py       |  66 ++++
 backend/app/negotiation/normalize.py  |  64 ++++
 backend/app/negotiation/router.py     | 462 ++++++++++++++++++++++++++
 backend/app/negotiation/service.py    | 243 ++++++++++++++
 backend/tests/test_actor.py           | 259 +++++++++++++++
 backend/tests/test_actor_prompt.py    | 102 ++++++
 backend/tests/test_actor_tools.py     | 114 +++++++
 backend/tests/test_hash.py            |  90 ++++++
 backend/tests/test_protocol.py        | 587 ++++++++++++++++++++++++++++++++++
 docs/handoff/agents__ali-b2-actor.md  | 147 +++++++++
 docs/handoff/agents__ali-b3-router.md | 137 ++++++++
 22 files changed, 3410 insertions(+), 79 deletions(-)
```
