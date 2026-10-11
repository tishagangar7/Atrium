# Handoff: backend/tisha-c4-negotiate

| Field | Value |
|---|---|
| Branch | `backend/tisha-c4-negotiate` |
| Owner | Tisha |
| Workstream / queue item | WS-C / C4 |
| PRD sections | §8.2, §4.6, §6.8-§6.11, §5.11; original tasks T15-T17 (C side) |
| Created | 2026-10-10T09:00Z |

## Goal

Implement C4: connect negotiation (PRD §12.3). `POST /negotiate` opens a real decision point
through Ali's (WS-B) `NegotiationService`, running genuine three-actor negotiation under the
labeled TEST PROVIDER (no live model credentials exist anywhere -- OPEN-05). `POST
/negotiate/cancel`, `POST /events/inject`, `POST /escalations/{dp_id}/resolve`, `GET
/proposals` all wired the same way. Proven by `backend/tests/test_negotiate.py` (13 tests,
real commit and real escalation+fallback flows) plus manual curl verification.

## Current state

**Status:** complete; ready for PR (stacked on four unmerged PRs, see below -- **do not merge
before they do**).

**Why this was buildable at all:** a research fork read Ali's actual code on
`origin/agents/ali-b4-commit-gate` (not just his handoff prose) and confirmed his B1-B4
(`NegotiationService`, `Router`, `CommitGate`, `Actor`, `StubSim`, `FakeProvider`) are complete
and tested (150 of his own tests green). His B4 handoff literally names "Tisha (C4)" with the
exact construction call. Two real constraints shaped this PR, not cosmetic ones:
1. `NegotiationService.start_decision_point()` **blocks** until the whole decision point
   resolves -- `/negotiate` backgrounds it (`asyncio.create_task`, same pattern as C6's
   `BenchmarkRunner`) to honor the PRD's `202 {dp_id}` response.
2. **`StubSim`'s world doesn't match `app.models.WorldState`** (missing `Cell`
   `x`/`y`/`state`/`intensity`/`ignited_step`, no `metrics_so_far`, ignores `scenario_id`). A
   real, previously-unreviewed gap between WS-B's stub and WS-C's contracts -- G0 only reviewed
   §7.5-7.7 agent/message fields, not §7.2 world fields. **Scope decision:** rather than pad
   fake position/fire data onto `StubSim`'s world to force-fit `WorldState` (its own kind of
   fabrication), **negotiation runs against its own `StubSim`, fully decoupled from
   `RunController`'s live-run world.** `GET /state` is unchanged (still my own stub world);
   negotiation's state only surfaces through its own envelopes and `GET /proposals`. This is a
   flagged gap, not papered over -- see "Asks for other owners."

**Done:**
- `backend/app/negotiation_session.py` (new): `NegotiationSession` wraps `StubSim` + 3 `Actor`s
  + `NegotiationService` per run_id. `INJECT_EVENT_CATALOG` maps the PRD's 4 named composite
  disruption events onto `StubSim`'s 3 primitive event kinds (`road_status`/`wind_change`/
  `resource_status`) -- my own minimal stand-in, explicitly not a claim about real disruption
  physics (Madhav's real catalog lives in `scenarios/**`, not built yet).
- `backend/app/run.py`: re-added `emit_external`/`has_buffered_envelopes` (originally from C6,
  PR #12, not yet merged to this branch's base) -- needed so `RouterEvent`s reach
  `/events/stream` via the same mechanism. `/events/stream`'s source-selection condition
  updated to `is_active or has_buffered_envelopes` (same C6 fix, re-applied).
- `backend/app/main.py`: `POST /negotiate` (backgrounds + `202 {dp_id}`), `POST
  /negotiate/cancel`, `POST /events/inject`, `POST /escalations/{dp_id}/resolve`, `GET
  /proposals`. `create_app()` gained `negotiation_script`/`negotiation_delay_s` test-only
  overrides (same pattern as C6's path overrides). Session dict cleared on every successful
  reset (one active run at a time, §8.1).
- Verified manually, three times, with real (not hand-waved) outcomes:
  - A scripted unanimous commit (EVAC proposes round 1, FIRE+LOG accept round 2) -- real
    `plan.committed` envelope, `authority: "unanimous"`, 3 real acceptances.
  - An unscripted all-silent run -- real escalation (`escalation.opened`, zero candidates),
    resolved via `fallback` -- real `Commit(authority="human_choice", plan_id="dp-1:F0")`.
  - `/events/inject` against `StubSim` -- real `wind`/`road.status_override` mutation,
    `state_version` incremented correctly, and a stale-version call correctly rejected 409
    afterward.
- 156 backend tests pass (143 before this branch + 13 new in `test_negotiate.py`): 404/409/503
  guards, real commit flow, real escalation+resolve flow, cancel, concurrent-negotiate 409
  (using a `delay_s` on the TEST PROVIDER to make the race deterministic, not flaky), `/events/
  inject` success + Literal-rejected 422, `GET /proposals` 404. `scripts/check.sh` passes with
  or without `RESCUEMESH_TEST`/`RESCUEMESH_PROVIDER` set in the shell (tests set their own via
  `monkeypatch`).
- **Bug found while writing tests, not a product bug:** my first `_poll_dp` test helper waited
  for `/proposals`'s plan list to be non-empty before considering a decision point "resolved" --
  but an all-silent decision point escalates with **zero plans** (nobody proposed), so that
  condition can never become true. Fixed by polling `/events/stream` for a terminal event type
  (`plan.committed`/`escalation.opened`) instead, which is the only reliable completion signal
  regardless of whether any plan was ever proposed.
- Re-applied the same `emit_external`/`has_buffered_envelopes` methods from C6 (PR #12) since
  this branch is based on Ali's `agents/ali-b4-commit-gate`, which only has my C1-C3 merged
  (not C5/C6, both still open). Confirmed via `git diff --stat` that Ali's merged B1/B2/B3/B4
  content has zero overlap with anything WS-C owns.

**In progress:**
- None. C4 scope (connect negotiation) is done, scoped as above (no world unification).

**Next steps:**
1. Commit, push, `gh pr create` (base `main`). PR body must state plainly: **cannot merge
   before #6(done)/#7(done)/#8(open)/#11(open) all merge**, and will need a `model_validate`
   cleanup pass once #13 (`contracts`→`app.models` re-export, also open) lands -- right now
   `Commit`/`EscalationPackage` objects this code returns are Ali's own `app.agents.contracts`
   classes (field-compatible by transcription, not `isinstance`-identical to `app.models`); it
   doesn't matter today since nothing here type-checks against `app.models.Commit` directly,
   but worth a follow-up once #13 merges for hygiene.
2. Once the merge chain lands: rebase this branch onto `main`, re-run `scripts/check.sh`.
3. **The real unlock for G1/G2:** once Madhav's `app.sim` (A2/A3/A4) exists with a
   `WorldState`-compatible world, swap `StubSim` for it in `negotiation_session.py` (one
   constructor call site) and retire the "decoupled worlds" scope decision -- `GET /state`
   would then reflect negotiation's actual effect on the world. Tracked as the real follow-up,
   not silently assumed to be "done."
4. C7 (backend integration checks, save live replay fixtures) is the other remaining C-owned
   item; could use this PR's real commit/escalation flows as the first non-hand-written
   fixtures once this merges (§13.3's requirement that fixtures come from live runs, not
   hand-written JSON) -- though they'd still need the "STUB"/TEST PROVIDER label since no real
   model or physics is involved yet.

**Decisions and why:**
- Negotiation decoupled from `RunController`'s world (see "Why this was buildable" above) --
  the alternative (padding `StubSim`'s world to fit `WorldState`) would fabricate fire/position
  data that doesn't exist, which is worse than an honestly-labeled gap.
- `Commit`/`EscalationPackage` returned as-is (Ali's `contracts` classes), not round-tripped
  through `app.models.Commit.model_validate(...)` -- the JSON output is identical either way
  (field-compatible by transcription) and nothing in this PR's own code needs a strict
  `app.models` instance, so the conversion would be pure overhead. Revisit if that changes.
- `INJECT_EVENT_CATALOG` is explicitly my own minimal stand-in mapping the PRD's 4 named events
  onto `StubSim`'s 3 primitives and its fixed `R2`/`B1` identifiers -- not a claim about real
  disruption physics, which is Madhav's (§5.11, `scenarios/**`).
- `/events/inject`'s `expected_state_version` is checked against the **negotiation session's
  own** version space (`StubSim`'s), not `RunController`'s live-run version -- an honest
  consequence of the decoupled-worlds decision, documented in the endpoint's own docstring.

**Gotchas / traps:**
- This branch is stacked on `origin/agents/ali-b4-commit-gate`, not `main` -- `git switch -c
  backend/tisha-c4-negotiate origin/agents/ali-b4-commit-gate` (manual, like C2/C3; `start-
  task.sh` only branches from `origin/main`).
- `NegotiationService.start_decision_point` blocks; never `await` it directly from an HTTP
  handler that needs to respond promptly -- always background it and let `sink` (wired to
  `controller.emit_external`) carry the results.
- `FakeProvider` is refused unless `RESCUEMESH_TEST=1` (AC-026, enforced by Ali's
  `get_provider`) -- `/negotiate` without a configured provider returns `503
  MODEL_UNAVAILABLE`, not a crash; confirmed by `test_negotiate_without_provider_configured_
  returns_503`.
- Polling for decision-point completion must watch `/events/stream`'s event *types*, not
  `/proposals`'s plan list -- an all-silent escalation has zero plans (see "Bug found" above).

**How to verify:**
```bash
cd backend
uv run pytest -q          # 156 passed, 1 skipped
cd .. && bash scripts/check.sh
```

**Asks for other owners:**
- **Madhav (A3, world schema):** `StubSim`'s world (`backend/app/agents/sim_stub.py`) doesn't
  match `app.models.WorldState` -- missing `Cell.x/y/state/intensity/ignited_step`,
  `metrics_so_far` entirely, and it ignores `scenario_id`. This wasn't caught at G0 (that review
  only covered §7.5-7.7). Worth reconciling before `app.sim` exists, so WS-B's stub and the real
  engine (and WS-C's integration) agree on one world shape from the start.
- **Ali:** flagging only, not blocking -- once PR #13 (`contracts`→`app.models` re-export)
  merges, this PR's `Commit`/`EscalationPackage` handling simplifies (no longer two separate-
  but-compatible classes). No action needed from him for this PR to work.

**Open questions:**
- None new. OPEN-05 (no credentials anywhere) still open, not blocking C4 -- TEST PROVIDER
  covers the integration-proving need per AGENTS.md §1 invariant 8.

## Session log

### 2026-10-10T09:32Z · claude-code · Tisha Gangar
**Status:** C4 complete: real negotiation wired via Ali's NegotiationService (TEST PROVIDER), commit+escalation+fallback proven; 156 tests green
```text
HEAD 236ad73 · behind origin/main: 0
-- commits on branch --
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
 M backend/app/main.py
 M backend/app/run.py
?? backend/app/negotiation_session.py
?? backend/tests/test_negotiate.py
?? docs/handoff/backend__tisha-c4-negotiate.md
-- diffstat vs main --
 backend/app/negotiation/hash.py            |  66 ++++
 backend/app/negotiation/normalize.py       |  64 ++++
 backend/app/negotiation/router.py          | 462 +++++++++++++++++++++++
 backend/app/negotiation/service.py         | 243 ++++++++++++
 backend/app/run.py                         |  30 ++
 backend/tests/test_actor.py                | 259 +++++++++++++
 backend/tests/test_actor_prompt.py         | 102 +++++
 backend/tests/test_actor_providers.py      |   9 +-
 backend/tests/test_actor_tools.py          | 114 ++++++
 backend/tests/test_hash.py                 |  90 +++++
 backend/tests/test_protocol.py             | 587 +++++++++++++++++++++++++++++
 docs/handoff/agents__ali-b2-actor.md       | 147 ++++++++
 docs/handoff/agents__ali-b3-router.md      | 137 +++++++
 docs/handoff/agents__ali-b4-commit-gate.md | 155 ++++++++
 27 files changed, 3791 insertions(+), 87 deletions(-)
```
