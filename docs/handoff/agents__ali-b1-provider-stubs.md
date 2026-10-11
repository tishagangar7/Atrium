# Handoff: agents/ali-b1-provider-stubs

| Field | Value |
|---|---|
| Branch | `agents/ali-b1-provider-stubs` |
| Owner | ali |
| Workstream / queue item | agents / B1 (T05, T03 review, T11 prep) |
| PRD sections | §3.5, §4.4, §5.9, §6.2, §6.5, §7.5–7.7, §10.1, §11.5, §12.2, D-17 |
| Created | 2026-10-10T07:38Z |

## Goal

B1 (PRD §12.3): specify WS-B contracts, implement both provider adapters with structured smoke calls, the
labeled test provider and a typed simulator stub, so B2 (actor) can start without Tisha's scaffold or Madhav's
simulator. Done = `tests/test_actor_*.py` green, `python -m app.agents.smoke` records latency for each provider
that has a key (or reports PENDING), and Tisha has the WS-B field spec for `models.py`.

## Current state  (REWRITE this whole section at every handoff)

**Status:** ready for PR (live smoke calls pending credentials)

**Done:**
- `backend/app/agents/contracts.py` — §7 classes WS-B needs (WS-B spec: `AssignmentDraft`, `Objection`, `TurnMessage`,
  `AgentTurn`, `AgentMessage`, `Acceptance`, `TargetRevision`, `Commit`, `EscalationPackage`; plus consumed A/C types).
  **Temporary shim** until `app/models.py` exists; then every class becomes a re-export.
- `backend/app/agents/schema.py` — `turn_output_schema()` (sentinel schema, D-17: no nulls/unions/bounds, all
  required, `additionalProperties:false`), `parse_turn()` (sentinels → `None`, fills `TargetRevision.by/dp_id`),
  `validate_turn()` (§6.5 per-type rules, ≤3 msgs, ≤1 plan, rationale ≤280, `UNKNOWN_EVIDENCE`,
  `INVALID_REFERENCE`, `TARGET_BELOW_FLOOR`, FR-026 `caused_by`), `TurnContext`.
- `backend/app/agents/provider.py` — provider-neutral `ProviderRequest/Response`, `ToolSpec/ToolCall/ToolResult`,
  `Settings.from_env()` (`RESCUEMESH_PROVIDER|MODEL|EFFORT|TEST`), `load_backend_env()` (no dotenv dep),
  `get_provider()` (refuses fake outside `RESCUEMESH_TEST=1`), `CallLedgerRow` shape (§10.5).
- `provider_anthropic.py` (`output_config.format` json_schema + `strict` tools), `provider_openai.py` (Responses
  `text.format` json_schema strict + function tools). Both: 1 SDK retry, timeout = turn deadline, response kinds
  `output|tool_calls|refusal|truncated`, typed exceptions → `ProviderError(retryable)`. Injected-client tests only.
- `provider_fake.py` — TEST PROVIDER, labeled, scripted by `(agent_id, round)`, supports tool-call rounds and
  failure kinds, records every request (for the AC-025 leak test later).
- `sim_stub.py` — `SimService` Protocol (A→B contract) + `StubSim`: §5.2 map, §5.3 resources, §5.9 evidence with
  belief masking, `find_routes` (≤3 simple paths on the view), `validate_plan` (structural codes only),
  `evaluate_plan` on a deep copy with zero placeholder metrics, `apply_event` bumps `state_version`, `disclose()`.
- `tools.py` — the four §6.2 tool specs (schemas only; strict-compatible).
- `smoke.py` — T05: `python -m app.agents.smoke --provider all --n 3` → p50/p95/tokens/parse-ok per provider,
  writes `runs/provider_smoke.json`; prints PENDING for a provider without a key.
- Tests: `tests/test_actor_schema.py` (18), `test_actor_provider_fake.py` (8), `test_actor_sim_stub.py` (9),
  `test_actor_providers.py` (7) — 42 passing on Python 3.12.11 / pydantic 2.14.0 / anthropic 1.13.0 / openai 3.28.0.
- `chore`: committed the executable bit on `.githooks/*` and `scripts/*.sh` (they were 100644, so hooks never ran
  on a fresh clone/worktree).

- **G0 contract review done** (PRD §12.2): Tisha's `models.py` in PR #2 matches §7.5–7.7 and `contracts.py`
  field-for-field; signed off in a PR #2 comment with the deps ask. Her C1 also commits the exec bit on
  hooks/scripts — identical to the chore commit here, so the two PRs merge in either order without conflict.

**In progress (exact file/function, what's half-finished):**
- Nothing half-written. Live smoke calls not run: no credentials exist yet (OPEN-05).

**Next steps (ordered, concrete):**
1. **Ali (T01/OPEN-05):** obtain a key; in `backend/.env` set the provider key variable (`ANTHROPIC_API_KEY` or
   `OPENAI_API_KEY`), `RESCUEMESH_PROVIDER` and `RESCUEMESH_MODEL` (fast tier id); run
   `cd backend && uv run --python 3.12 --with 'pydantic>=2' --with anthropic --with openai python -m app.agents.smoke --provider all --n 3`;
   paste the p50/p95 table here; pick the provider per §3.5 (1)–(4). G0 for WS-B passes on the first OK row.
2. Open PR `agents/ali-b1-provider-stubs` → main (squash). Review: Tisha (contracts) or a Fable review pass.
3. **B2** on a new branch `agents/ali-b2-actor`: `actor.py` (lifecycle §6.3: ≤2 tool iterations, ≤1 repair, turn
   deadline, cancellation), `prompt.py` (`build_prompt(actor_state, belief_view, inbox)` per §6.13 — inputs are typed
   and hold only held evidence, §4.4), tool implementations in `tools.py` with `ToolContext(agent_id)` over `SimService`,
   call ledger writer. Use `FakeProvider` + `StubSim` for tests; `test_actor_isolation` (AC-001).
4. When C1 merges: replace `contracts.py` bodies with `from app.models import …` re-exports; delete the duplicated
   A/C types. When A3 merges: swap `StubSim` for `app.sim` behind `SimService`.

**Decisions and why:**
- Sentinels, not nullable unions, in the model-facing schema (D-17): Anthropic strict mode caps union-typed params at 16
  and bans bounds/`maxLength`; OpenAI strict requires every property. All bounds live in `validate_turn()` (§3.5).
- One provider interface with a tool loop (`tool_calls` kind + `AssistantToolCalls`/`ToolResults` items) rather than
  "JSON only": §6.3 needs CALLING_MODEL ⇄ RUNNING_TOOL inside one turn.
- No `thinking` parameter, `effort` only when configured: the runtime tier is unknown until H+1 and these knobs are
  not accepted uniformly. No server-side `fallbacks`: §10.1 already treats refusal as malformed → one repair.
- Refusal/truncation/non-JSON → response kinds, never exceptions: the actor decides (repair once, then failed turn).
- Contracts duplicated into `agents/contracts.py` instead of creating `models.py`: `models.py` is Tisha's sole-edit
  file (AGENTS.md §2). The duplication is explicit, marked, and removed at C1.
- No `pyproject.toml` from WS-B (Tisha's). Tests run via ad-hoc `uv run --with …` until C1 lands.
- Stub `evaluate_plan` returns all-zero `Metrics` and empty `target_checks`, never fake forecasts (invariants 3, 9).

**Gotchas / traps:**
- `FakeProvider` needs `provider.set_round(agent, n)` to pick the scripted turn; unscripted turns are silence.
- `turn_output_schema()` strips `$defs` by inlining; adding a recursive type to `AgentTurn` would break strict mode.
- `Observation.world` is a plain dict (belief-view world); `Observation.model_rebuild()` is needed because
  `Assignment` is defined after it.
- `load_backend_env()` never overrides existing env vars — a stale shell export wins over `backend/.env`.
- `smoke.py` exits 1 when no provider returns OK (including the all-PENDING case).
- `scripts/check.sh` flags any `sk-ant-…`/`sk-…` string, even in test fixtures. Don't write key-shaped strings.
- The worktree is `../rotation-wt/agents__ali-b1-provider-stubs`; the main checkout stays on `main`.

**How to verify:**
```bash
cd ../rotation-wt/agents__ali-b1-provider-stubs/backend
uv run --python 3.12 --with pytest --with 'pydantic>=2' --with anthropic --with openai python -m pytest -q tests/test_actor_*.py
# live (needs backend/.env): both rows should show status OK, p50 < 4000 ms (§3.5 criterion 3)
uv run --python 3.12 --with 'pydantic>=2' --with anthropic --with openai python -m app.agents.smoke --provider all --n 3
cd .. && scripts/check.sh
```

**Asks for other owners (file, owner, what, why):**
- `backend/app/models.py`, **Tisha (C1)**: adopt the classes in `backend/app/agents/contracts.py` verbatim (they are the
  §7.1/§7.3–7.7 transcription; WS-B fields reviewed). Keep `extra="forbid"` or tell me if C needs `extra="ignore"`.
- `backend/pyproject.toml`, **Tisha (C1)**: add deps `anthropic` (1.13.0 tested), `openai` (3.28.0), `pydantic>=2`
  (2.14.0), `pytest`; `requires-python = ">=3.12"`. Also add to `.env.example`: `RESCUEMESH_PROVIDER`,
  `RESCUEMESH_MODEL`, `RESCUEMESH_EFFORT` (optional), `RESCUEMESH_TEST`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`.
- `.githooks/*`, `scripts/*.sh`, **Rohaan**: this branch commits the exec bit (`chore` commit `4940a8a`); no content
  change. Without it the pre-commit hook is silently skipped on every fresh clone.
- `backend/app/sim/**`, **Madhav (A1/A3)**: please implement the `SimService` Protocol in `sim_stub.py` (method names and
  argument order), returning `Violation`/`Evaluation`/`Leg` from `models.py`, with `evaluate_plan` taking a view and a
  `plan_hash`. Anything you need changed in that signature, tell me before G0.

**Open questions (with the PRD's provisional answer if any):**
- OPEN-05 provider/credits: none yet. Provisional: build on the labeled TEST PROVIDER; both live checks are
  **explicitly pending** (PRD §12.3 B1, §12.5 G0 "If missed"). Not a scope change.
- Whether `TargetRevision.by/dp_id` should stay runtime-filled (my reading of §6.11) or be model output. Current:
  runtime-filled; the model-facing revision has only `metric, old_aspiration, new_aspiration, reason`.

## Session log  (append-only; `scripts/handoff.sh` adds entries)

### 2026-10-10T07:59Z · claude-code · aliharyanawalla
**Status:** B1 done: contracts shim, sentinel schema, 2 adapters, TEST PROVIDER, sim stub, smoke script; 42 tests green; live smoke PENDING (no keys)
```text
HEAD b6d2f56 · behind origin/main: 0
-- commits on branch --
b6d2f56 feat(agents): Anthropic and OpenAI adapters, tool specs and T05 smoke script (PRD §3.5, D-03)
ae40315 feat(agents): typed simulator stub with belief masking and structural validation (PRD §12.2, §5.9)
27a4081 feat(agents): provider interface, settings and labeled TEST PROVIDER (PRD §3.5, §11.5)
4940a8a chore: commit executable bit on git hooks and scripts
4beca7a feat(agents): WS-B contracts and sentinel turn schema (PRD §7.5, D-17)
-- uncommitted --
 M backend/tests/test_actor_provider_fake.py
 M docs/handoff/agents__ali-b1-provider-stubs.md
-- diffstat vs main --
 backend/app/agents/smoke.py                   | 166 ++++++++++++
 backend/app/agents/tools.py                   |  63 +++++
 backend/tests/test_actor_provider_fake.py     | 120 +++++++++
 backend/tests/test_actor_providers.py         | 152 +++++++++++
 backend/tests/test_actor_schema.py            | 235 +++++++++++++++++
 backend/tests/test_actor_sim_stub.py          | 119 +++++++++
 docs/handoff/agents__ali-b1-provider-stubs.md | 130 ++++++++++
 scripts/check.sh                              |   0
 scripts/claude-guard-branch.sh                |   0
 scripts/claude-session-start.sh               |   0
 scripts/handoff.sh                            |   0
 scripts/lib.sh                                |   0
 scripts/setup.sh                              |   0
 scripts/start-task.sh                         |   0
 24 files changed, 2496 insertions(+)
```
