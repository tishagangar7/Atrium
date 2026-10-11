# Handoff: agents/rohaan-b6-single-agent-main

| Field | Value |
|---|---|
| Branch | `agents/rohaan-b6-single-agent-main` |
| Owner | rohaan (covering WS-B for Ali while his laptop is down; team-approved) |
| Workstream / queue item | agents / B6 (land on main) |
| PRD sections | §11.2, §11.3, FR-061, AC-010, D-14, FR-040 |

## Goal
Get Ali's single-agent baseline (B6) onto `main`. #14 merged into `agents/ali-b5-models-reexport`, not `main`.

## Current state
**Status:** ready for PR

**Done:**
- Merged `origin/agents/ali-b6-single-agent` (B5 contracts re-export + B6 baseline). Ali's commits keep his authorship.
- Conflicts: `sim_stub.py` kept from main (newer, re-exports `app.sim.contract`). `actor.py` and `escalation.py` taken from B6; they are strict supersets of main (`prompt_builder` hook; `build_fallback_from` split, same behavior).
- Added the post-await version guard Tisha's C7 audit asked for: `SingleAgentBaseline._ensure_current()` raises `StaleDecisionPoint` if the authoritative `state_version` moved during a model call or before the fallback. Test: `test_world_moving_during_the_model_call_is_never_applied`.
- Backend: 247 passed. The only failures are `tests/test_bench.py` timing flakes, which also fail on plain `main` (WS-C, untouched).

**Next steps:**
1. Merge, so C6 can dispatch the real `single_agent` method.
2. A4 `fixed_rule.py` next (`sim/rohaan-a4-fixed-rule`).

**Asks for other owners:**
- Tisha: `tests/test_bench.py` is timing-flaky on slow disks (1–2 random failures per run, also on main).
