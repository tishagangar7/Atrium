# Handoff: agents/ali-b6-single-agent

| Field | Value |
|---|---|
| Branch | `agents/ali-b6-single-agent` (stacked on `agents/ali-b5-models-reexport` → #13 → #11 → #8 → main) |
| Owner | ali |
| Workstream / queue item | agents / B6 (T20) |
| PRD sections | §11.2, §11.3, §5.9 (union view), FR-061, AC-010, D-14 |
| Created | 2026-10-10T10:00Z |

## Goal

B6 (PRD §12.3): the single-agent baseline — one model on the union of all evidence, the same tools and output
schema as the three agents, one plan — in matched (48 calls / 120k tokens) and natural (8 calls) budget
configurations, with budgets disclosed and benchmark-style F0 fallback. Done = `tests/test_actor_baseline.py` green
and `SingleAgentBaseline.decide()` callable by Tisha's bench runner (C6).

## Current state  (REWRITE this whole section at every handoff)

**Status:** ready for PR (base `agents/ali-b5-models-reexport` until #13 merges)

**Done:**
- `backend/app/baselines/single_agent.py` — `BaselineBudget` (`MATCHED` 48/120k, `NATURAL` 8/120k),
  `BaselineDecision` (+ `summary()` row fragment for `RunResult`/`results.csv`), `build_baseline_prompts()`
  (§6.13 structure; single decision maker; all five targets as its own; union observation dict),
  `SingleAgentBaseline(provider, sim, run_id, scenario_id, budget, targets, apply, sink, settings).decide(state_version,
  locked)`: loops `Actor` turns (same tool loop / repair / deadline / DEGRADED) until a plan passes authoritative
  validation → `apply` → `status="committed"`; budget, wall clock or DEGRADED → F0 via `build_fallback_from` →
  `status="fallback", resolution="AUTO_FALLBACK"` (D-14). Counts `invalid_attempted` (§11.1). Never exceeds the call
  cap mid-turn (`actor.max_model_calls` is clamped to the remaining budget). Emits `agent.turn`, `tool.called`,
  `baseline.decision` via the same `RouterEvent` sink.
- `backend/app/agents/actor.py` — `Actor(prompt_builder=...)` hook; `default_prompt_builder` is the §6.13 builder;
  `agent_id` typed `str` (three agents or `"single_agent"`). No behaviour change for the negotiating actors.
- `backend/app/negotiation/escalation.py` — `build_fallback_from(locked, last_committed, sim, run_id, scenario_id,
  state_version)`; `build_fallback(rec, …)` is a thin wrapper. One F0 rule for escalation and baselines.
- `backend/app/baselines/__init__.py` (shared package with Madhav's `fixed_rule.py`).
- Tests `tests/test_actor_baseline.py` (11): union view sees all evidence; same tool list + schema (AC-010); valid plan
  applied with disclosed budget; tools on the union view; notice on a plan-less turn; natural budget → exactly 8 calls
  → F0 = locked legs; configurable cap exact; cap never exceeded mid-turn; deadline ×2 → DEGRADED → F0; empty F0 =
  hold; determinism. Whole backend suite green (see verify).

**In progress (exact file/function, what's half-finished):**
- Nothing.

**Next steps (ordered, concrete):**
1. Merge chain #8 → #11 → #13 → this PR (retarget bases as predecessors merge).
2. **C6 integration (Tisha):** for `method == "single_agent"` the runner builds
   `SingleAgentBaseline(get_provider(Settings.from_env()), sim, run_id=…, scenario_id=preset, budget=MATCHED|NATURAL,
   targets=scenario.targets, apply=<run-lock apply>, sink=<envelope writer>)` and calls `await decide(state_version,
   locked=<A's locked legs>)` at step 0 and after each event; `decision.summary()` gives `budget_calls`,
   `budget_tokens`, `model_calls`, `tokens_*`, `invalid_attempted`, `resolution`. Run both budgets; report both rows
   when they differ (§11.2).
3. **B5/B7 (with a key):** live smoke, one live `normal` negotiation, one live baseline decision; tune prompt wording.

**Decisions and why:**
- The baseline reuses `Actor` verbatim and swaps only the prompt builder, so "same tools, same schema, same
  deadlines, same repair rule" is true by construction rather than by re-implementation (AC-010).
- The baseline prompt lives in `baselines/single_agent.py` (not `prompt.py`) to avoid an import cycle
  (`prompt` ← `actor` ← builder types) and to keep the §6.13 per-role prompt untouched.
- The observation is a plain dict with `agent_id: "single_agent", basis: "union"` because `models.Observation.agent_id`
  is the three-agent `AgentId` literal; the baseline is deliberately not one of them.
- No `Commit` object: `Commit.authority` has no baseline value; the runner records the decision via `summary()`.
- `invalid_attempted` counts plans that reached authoritative validation and failed (plus normalization failures).
  Plans the actor bounced on its own (union) view during repair are not counted — on the union view that validation
  equals the authoritative statics, so the count would double. Documented in the results limitations if it matters.

**Gotchas / traps:**
- `FakeProvider` keys scripts by `(agent_id, round)`; the baseline uses `agent_id == "single_agent"` and `round == turn`.
- `decide()` increments `state_version` via `apply` on **both** outcomes (commit and fallback), like the gate.
- `last_committed` persists across `decide()` calls on the same instance → F0 after a disruption includes still-valid
  remaining legs of the previous baseline plan (§6.9), matching the negotiation path.
- Token caps only bind when the provider reports usage; the TEST PROVIDER reports 0 tokens, so tests exercise the
  call cap.

**How to verify:**
```bash
cd ../rotation-wt/agents__ali-b6-single-agent/backend
uv run --with pytest --with anthropic --with openai pytest -q
uv run pytest -q tests/test_actor_baseline.py
cd .. && scripts/check.sh
```

**Asks for other owners (file, owner, what, why):**
- `backend/app/bench/**`, **Tisha (C6)**: call shape above; both budgets per preset×seed; `RunResult.budget_calls/
  budget_tokens` from `decision.summary()`; `model` from `Settings.from_env().model`.
- `backend/app/models.py`, **Tisha** (`[contract]`, non-blocking): `Commit.authority` has no value for baselines —
  either add `"single_agent" | "fixed_rule"` or let `RunResult` carry the baseline decision without a `Commit`.
- `backend/app/baselines/fixed_rule.py`, **Madhav (A4)**: shares `baselines/__init__.py` (created here, one docstring
  line). Suggest the same return shape (`plan_hash`, `assignments`, `invalid_attempted`, `resolution`) so C6 treats
  the two baselines alike.

**Open questions (with the PRD's provisional answer if any):**
- Whether the natural budget should also cap tool iterations differently (§11.2 only names the call cap).
  Provisional: same per-turn limits as RescueMesh, only the per-decision call cap differs.

## Session log  (append-only; `scripts/handoff.sh` adds entries)

### 2026-10-10T09:11Z · claude-code · aliharyanawalla
**Status:** B6 done: single-agent baseline (matched/natural), F0 fallback shared with escalation; 161 tests green
```text
HEAD 4db1f93 · behind origin/main: 0
-- commits on branch --
4db1f93 feat(baselines): single-agent baseline with matched and natural budgets on the union view (PRD §11.2, FR-061, AC-010)
b2d925c docs(agents): handoff for contracts re-export
0ac2fcd refactor(agents): retire the contracts shim; re-export shared models from app.models (PRD §7, §12.2)
236ad73 docs(agents): B4 handoff — rebase onto main, test counts, merge-order note
9c88e61 fix(agents): skip adapter tests when SDKs are absent; accept MODEL_PROVIDER alias from .env.example
608b624 docs(agents): B4 handoff — state, C4 wiring asks, B5/B6 next
313061d feat(negotiation): unanimous commit gate, escalation package with F0, negotiation service (PRD §6.8, §6.9, §8.2)
998d93a feat(agents): apply_accepted_plan contract, router notices and stale marking for the commit gate (PRD §6.2, §4.3, FR-040)
4ae148e docs(agents): B3 handoff — state, B4 plan, asks for A/C
6c6d5d4 feat(negotiation): router — synchronous rounds, canonical delivery, evidence disclosure, own-view delivery evaluations (PRD §6.4–6.7, §6.10, §4.3)
581c8b2 feat(agents): validate a new plan on the proposer's own view before submitting (PRD §6.4 bounce-as-repair)
66b1c53 feat(negotiation): canonical plan hash and delivery-time normalization (PRD §6.7, D-08)
a1ad755 test(agents): keep redaction fixture below the secret-scan threshold
55108d1 docs(agents): B2 handoff — state, next steps for B3, asks for A/C
f23e0f3 feat(agents): single actor turn lifecycle with tool loop, repair, deadline, cancellation and ledgers (PRD §6.3, §6.4, §10.1)
