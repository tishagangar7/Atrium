# Handoff: sim/rohaan-a4-fixed-rule

| Field | Value |
|---|---|
| Branch | `sim/rohaan-a4-fixed-rule` |
| Owner | rohaan (covering Ali's A4 while his laptop is down; team-approved) |
| Workstream / queue item | sim / A4 (fixed-rule baseline) |
| PRD sections | §11.2 fixed-rule policy, FR-060, §11.3, D-14 |

## Goal
Deterministic fixed-rule baseline so C6 can run all three methods.

## Current state
**Status:** ready for PR

**Done:**
- `backend/app/baselines/fixed_rule.py`: `FixedRulePlanner(sim).plan(view, locked=None) -> list[AssignmentDraft]`, the four §11.2 rules on the union view. Greedy; each step is kept only if `sim.validate_plan` accepts the whole plan and it ends by the horizon. No model calls, no forecast-based choice.
- `tests/test_fixed_rule.py` (12): valid on all 4 presets, deterministic, V1 never carries crews, rule-1 zone order, capacity/waiting bounds, rule-4 refuel.
- Backend: 248 passed (only the known flaky `test_bench.py`).

**Findings (not fixed here; next PR `sim/rohaan-a4-sim-fixes`):**
- `validate_plan` mutates its input view (a zone's `assisted_waiting` drops after validating loads). The planner reads all counts before validating, so it isn't affected.
- At step 0 no crew gets a contain task: the West Forest fire is more than 1 cell from every node. This is per rule, not a bug. Clearing R2 for Pine Ridge isn't triggered because PR is reachable via R4.

**Next steps:**
1. Merge; C6 can then call `FixedRulePlanner` for `method="fixed_rule"`.
2. Sim fixes from the C7 audit; then `scenarios/tune.py` and tuning.

**Asks for other owners:**
- Tisha (C6): call shape is `FixedRulePlanner(sim).plan(sim.build_belief_view("union"), locked=sim.locked_legs())`, then normalize → hash → `apply_accepted_plan`.
