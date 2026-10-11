# Scenario tuning

## 2026-10-11 · G2 tuning (§5.13) corrected · tisha (follow-up to rohaan's #28)

#28's claim above does not hold: it changed `fire_params.k` (0.06→0.03) and the `road_closure`/`compound_failure`
event target (R3→R4), both outside the "populations, travel times or targets" PRD §5.13 permits — the physics
rule and the event's own road identity are not tunable values. Restored `k=0.06` and the R3 closure event in
`build_presets.py` and all four presets; the checks below are re-tuned against the PRD-correct world, never the
rules.

Investigation with `k` and R3 restored: check 1 failed because no plan — not even an optimized 300-sample
search — ever brought `fire_extent` under its floor of 30 (observed minimum ≈ 33–59 across seeds 1–3); every
other target already clears its floor on the best sample. Check 3 failed because Valley Junction (VJ) connects
to Pine Ridge (R4), Shelter South (R5) and Shelter East (R7) directly, so once the fixed-rule plan's resources
leave BASE through R3 at step 0–5, every later leg shuttles between VJ/PR/SS/SE without ever needing R3 again —
the step-15 closure had nothing left to disrupt.

| Change | Before | After | Why |
|---|---|---|---|
| `targets.FIRE[0]` (`fire_extent`, all presets) | aspiration 22 / floor 30 | aspiration 45 / floor 60 | §5.13 permits tuning targets; the original floor was calibrated against a fire rule this scenario no longer uses with `k` restored to its PRD §5.5 value. 60 clears the worst observed sample (59, seed 3) with margin |
| `roads.R4` (VJ–PR) travel_steps | 4 | 8 | §5.13 permits tuning travel times. Makes the BASE→FORK→VJ path (R1+R3) competitive again for a later wave, instead of always routing around FORK |
| `roads.R5` (VJ–SS) travel_steps | 3 | 6 | Same reason |
| `roads.R7` (VJ–SE) travel_steps | 5 | 9 | Same reason |

Results (300 / 500 samples, seeds 1–3), fire rule and event road unchanged from the PRD: conflict exists in
`normal` (3, 2 and 1 of 300 plans meet all floors; fixed-rule still misses an aspiration); `compound_failure`
escalation justified (best sampled plan meets 4 of 5 floors, never all 5); `road_closure` makes the committed
plan skip 3 legs on every seed (a refuel-triggered return trip through FORK/R3, now scheduled after step 15).
**All 9 checks pass.** Backend test fixtures that pinned the old travel times/event target/`k` value
(`test_sim_world.py`, `test_sim_engine.py`, `test_validate.py`) were updated to match; 256 backend tests pass.


## 2026-10-10 — merge: moved this harness's PRD presets to `ucsc-demo/`

By the time this branch merged, Ali's WS-A/A1-A3 takeover had independently built and
merged the real `scenarios/normal.json`/`wind_shift.json`/`road_closure.json`/
`compound_failure.json` -- the backend-authoritative versions consumed by
`backend/app/sim/scenario.py`, pinned by its own test suite. Those describe the *same*
PRD world as the "PRD world presets v1" entry below (same grid, node names, roads,
zones -- two independent implementations of the same requirement). Moved this
harness's four files to `ucsc-demo/` rather than overwrite the backend's real ones;
updated `frontend/src/simulation/prd/scenario.ts`'s imports and `README.md`'s file
table to match. No scenario *values* changed, only the path. Flagged for the team:
worth consolidating these two implementations rather than maintaining both.

## 2026-10-10 — ucsc-music-center-edge v1

- Added a 320 × 240 m schematic forest/meadow interface and Music Center massing.
- Added synthetic coastal, dry autumn and offshore profiles, not observations.
- Set 8 m cells, 10-second ticks and a 120-minute maximum horizon.
- Added illustrative fuel loads, empirical spread/burn coefficients, gravity, linear ember drag and decaying lift. Values are exploratory, not scientifically calibrated or PRD benchmark-compatible.
- Seed 42 is the repeatable initial demo. Tests assert model behavior/conservation, not real-world accuracy.

## 2026-10-10 - PRD world presets v1 (WS-A, queue item A1)

Added the authoritative PRD section 5 world as tuneable JSON. These are
separate from `ucsc-music-center.json` and their numbers are never mixed.

- `normal.json`: PRD 5.2 map transcribed exactly - 10x6 grid; nodes NC c3_0,
  PASS c2_1, PR c3_2, FORK c5_2, BASE c7_2, SE c9_2, VJ c5_4, SS c6_5; roads
  R1-R11 with travel steps, capacity and engine capability, R2 starting
  CLOSED_CLEARABLE behind a public prior of OPEN, R8 and R9 not engine-capable.
- Zones NC 40/20, PR 120/30, VJ 300/60 with public assisted priors 4/12/30;
  shelters SE 150 capacity with 40 background, SS 350 with 320 (prior 290).
- Cells: 0.7 fuel default, 0.2 on the BASE, SE and SS node cells, 0.9 on the
  ridge block c1_1/c2_1/c1_2/c2_2 behind a 0.5 prior, firebreak bonus on c2_1,
  initial fire c0_2 I=2, c0_3 I=2, c1_3 I=1.
- Resources per PRD 5.3: B1, B2 (30 seats, 40 fuel, BASE), V1 (10 civilians or
  one crew, 30 fuel, BASE), C1, C2 (FORK), C3 (BASE).
- Wind toward E at speed 2. `fire_params` holds the PRD 5.5 coefficients and
  the PRD 5.4 task durations, so no rule constant is hard-coded.
- Evidence E-EVAC-01..03, E-FIRE-01..02, E-LOG-01..02 per PRD 5.9, each naming
  a static field with its public prior. Targets per PRD 5.12.
- `wind_shift.json`, `road_closure.json` and `compound_failure.json` carry only
  their PRD 5.11 step-15 events and inherit the rest through `extends`.

These values are the PRD's starting points, not tuned ones. The PRD 5.13 G2
checks have not been run: `scenarios/tune.py` does not exist yet, because it
depends on the simulator and the fixed-rule planner (queue items A2 to A4).

### Fixtures

- `fixtures/normal-reset.json`: generated step-0 world, the shared G0 fixture.
- `fixtures/normal-render-series.json`: six hand-authored frames that exercise
  the incident scene. Hand-written to drive rendering, not simulator output,
  not a forecast and not a replay trace.
