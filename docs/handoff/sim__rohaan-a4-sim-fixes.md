# Handoff: sim/rohaan-a4-sim-fixes

| Field | Value |
|---|---|
| Branch | `sim/rohaan-a4-sim-fixes` |
| Owner | rohaan (covering Ali's WS-A work while his laptop is down; team-approved) |
| Workstream / queue item | sim / A4 correctness fixes from Tisha's C7 audit |
| PRD sections | §5.3, §5.4, §5.8, D-10, invariant 4 |

## Current state
**Status:** ready for PR

**Done (each with a regression test in `tests/test_sim_fixes.py`):**
1. `plans.expand` no longer mutates its input world. Planned pickups are tracked in a local `pickups` map (invariant 4).
2. A road cleared by a planned `clear_road` can be driven once that work ends; earlier entry is still `ROAD_CLOSED`.
3. Only a `transport` can `transfer_crew` (buses were accepted).
4. A crew driving its own engine takes the engine with it, in both planning (`plans._expand_drive`) and execution (`engine._arrive`).
5. A vehicle failing with passengers aboard goes out of service after its next completed unload (`engine` unload).
6. `locked_legs()` locks only the edge a vehicle is on mid-drive. `expand` accepts that one-edge locked drive without re-entry or a false `RESOURCE_DOUBLE_BOOKED`.

Backend: 244 passed (this branch is off main; no B6/fixed-rule files).

**Next steps:**
1. Merge. Then `scenarios/tune.py` + tuning (§5.13): the fire reaches ~54/60 cells.
2. WS-B fixes: disclosure version invalidation, target revisions, aggregate DP budget, F0 revalidation.
