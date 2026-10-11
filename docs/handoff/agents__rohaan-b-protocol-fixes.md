# Handoff: agents/rohaan-b-protocol-fixes

| Field | Value |
|---|---|
| Branch | `agents/rohaan-b-protocol-fixes` |
| Owner | rohaan (covering Ali's WS-B while his laptop is down; team-approved) |
| Workstream / queue item | agents / WS-B correctness fixes from the C7 audit |
| PRD sections | §4.3, §6.3, §6.8, §6.9, §6.11, §10.2, NFR-004 |

## Current state
**Status:** ready for PR. Regressions in `tests/test_protocol_fixes.py` (6).

**Done:**
1. **Disclosure before evaluation:** cited/shared evidence is disclosed once the message is certain to be delivered and **before** recipients' delivery-time evaluations, so each own-view evaluation knows the cited evidence. Rejected messages disclose nothing.
2. **Target revisions are public:** `Router.publish_revision()` updates the owner's aspiration, the shared public target table every actor's prompt reads, and the simulator (`SimulatorService.set_target_aspiration`, so `target_checks` use it). The human relax goes through it too. Each router copies the target table, so revisions never leak into `DEFAULT_TARGETS` or another run.
3. **Aggregate budget:** `RouterSettings.dp_max_calls=48` / `dp_max_tokens=120_000` are tracked across all actors (`rec.model_calls`, `rec.tokens`). The remaining calls are split per actor each round, and the DP stops with `BUDGET_EXCEEDED` before a round that could overrun.
4. **Same-round degrade:** the turn that makes an actor DEGRADED (second failure) is counted at that round boundary, so `AGENT_UNAVAILABLE` fires a round earlier than before.
5. **F0 commit:** re-checks `state_version` (`StaleDecisionPoint`) and authoritative validity (`PlanInfeasible`) before applying, including locked-only F0.

**Deliberately not changed (decision, needs Ali's eyes):** the audit suggested that disclosure should bump `state_version` and void acceptances. The PRD's version bump is for exogenous events and new evidence entering the world (FR-040, §4.6). Disclosure between agents is the negotiation mechanism (§4.3, B§7): bumping the version on every share would make the gate reject every commit after any share. The real defect was the evaluation ordering (fix 1).

**Open edge case:** a turn with a `target_revision` but no messages is treated as `silent`, so its revision is ignored (actor sets status by message count). Worth deciding in WS-B.

Backend: 242 passed (only the known flaky `test_bench.py`).
