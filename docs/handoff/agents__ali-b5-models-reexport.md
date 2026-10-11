# Handoff: agents/ali-b5-models-reexport

| Field | Value |
|---|---|
| Branch | `agents/ali-b5-models-reexport` (stacked on `agents/ali-b4-commit-gate` → PR #11 → #8 → main) |
| Owner | ali |
| Workstream / queue item | agents / follow-up to B1 (contracts shim retirement), prep for B5 |
| PRD sections | §7 (contracts), §3.5 (bounds enforced after parse), §12.2 (models.py sole editor) |
| Created | 2026-10-10T09:45Z |

## Goal

Retire the temporary `backend/app/agents/contracts.py` shim now that Tisha's `app/models.py` (PR #2) is on `main`:
WS-B imports the shared contracts from one source of truth and no longer carries duplicate class definitions.

## Current state  (REWRITE this whole section at every handoff)

**Status:** ready for PR (base `agents/ali-b4-commit-gate` until #11 merges)

**Done:**
- `backend/app/agents/contracts.py` is now re-exports from `app.models` plus three WS-B-only names:
  `AGENT_IDS` (canonical order), `MetricName`, `SCHEMA_VERSION`. No Pydantic classes are defined in `agents/`.
- Two tests adjusted for the one behavioural difference: `app.models` enforces `rationale ≤ 280` and
  `proposed_amendment ≤ 200` with Pydantic `max_length`, so an over-long rationale now fails at `parse_turn`
  (ValidationError, surfaced via `validation_error_lines` to the repair prompt) instead of only in `validate_turn`.
  Both paths still produce the one repair attempt (§10.1); `turn_output_schema()` strips `maxLength` as before.
- Full backend suite (Tisha's + WS-B): 150 passed with SDKs; 143 passed, 1 skipped via the project venv.

**In progress (exact file/function, what's half-finished):**
- Nothing.

**Next steps (ordered, concrete):**
1. Merge chain #8 → #11 → this PR (retarget bases as predecessors merge).
2. **B5 / C4 integration:** once Tisha wires `NegotiationService` (see `docs/handoff/agents__ali-b4-commit-gate.md`
   → Asks) and a key exists in `backend/.env`, run `python -m app.agents.smoke --provider all --n 3`, then one live
   `normal` decision point through `/negotiate`; tune `prompt.py` wording only (structure fixed by §6.13).
3. **B6:** `backend/app/baselines/single_agent.py` (one `Actor` on the union view; matched 48-call and natural
   8-call budgets; same tools/schema; output one plan → authoritative validate → apply) + tests.

**Decisions and why:**
- Kept the module name `app.agents.contracts` as the WS-B import point instead of rewriting ~15 import sites: the
  module is now a thin re-export, so there is one definition of every class and no divergence risk.
- Did not add `extra="forbid"` to Tisha's models (her file): WS-B parsing goes through the sentinel schema, which
  already sets `additionalProperties: false` for the model, so unknown keys cannot arrive from a strict provider.

**Gotchas / traps:**
- `Observation.public_events` is `list[ScheduledEvent]` in `app.models` (the shim had `list[dict]`); pass model
  instances or `[]`.
- `Evidence.summary` has `max_length=160` — scenario evidence summaries must respect it (the stub's do).

**How to verify:**
```bash
cd ../rotation-wt/agents__ali-b5-models-reexport/backend
uv run --with pytest --with anthropic --with openai pytest -q     # 150 passed
uv run pytest -q                                                   # 143 passed, 1 skipped (adapters need SDKs)
cd .. && scripts/check.sh
```

**Asks for other owners (file, owner, what, why):**
- `backend/pyproject.toml`, **Tisha**: still needs `anthropic` and `openai` in `dependencies` (asked on #2 and #9).

**Open questions (with the PRD's provisional answer if any):**
- None new.

## Session log  (append-only; `scripts/handoff.sh` adds entries)

### 2026-10-10T09:01Z · claude-code · aliharyanawalla
**Status:** contracts shim retired: WS-B imports app.models; 150 tests green
```text
HEAD 0ac2fcd · behind origin/main: 0
-- commits on branch --
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
d483fe8 feat(agents): prompt contract per role with structural evidence isolation (PRD §6.13, §4.4)
63e09ae feat(agents): tool implementations on the caller's belief view with injected ToolContext (PRD §6.2, §4.4)
-- uncommitted --
?? docs/handoff/agents__ali-b5-models-reexport.md
-- diffstat vs main --
 backend/app/negotiation/hash.py            |  66 ++++
 backend/app/negotiation/normalize.py       |  64 ++++
 backend/app/negotiation/router.py          | 462 +++++++++++++++++++++++
 backend/app/negotiation/service.py         | 243 ++++++++++++
 backend/tests/test_actor.py                | 259 +++++++++++++
 backend/tests/test_actor_prompt.py         | 102 +++++
 backend/tests/test_actor_providers.py      |   9 +-
 backend/tests/test_actor_schema.py         |   8 +-
 backend/tests/test_actor_tools.py          | 114 ++++++
 backend/tests/test_hash.py                 |  90 +++++
 backend/tests/test_protocol.py             | 587 +++++++++++++++++++++++++++++
 docs/handoff/agents__ali-b2-actor.md       | 147 ++++++++
 docs/handoff/agents__ali-b3-router.md      | 137 +++++++
 docs/handoff/agents__ali-b4-commit-gate.md | 155 ++++++++
 27 files changed, 3628 insertions(+), 373 deletions(-)
```
