# Handoff: sim/tisha-a4-prd-tuning

| Branch | `sim/tisha-a4-prd-tuning` |
| Owner | Tisha, follow-up to Rohaan #28 |
| PRD sections | §5.5, §5.11, §5.13 |

## Current state

**Status:** Done. All nine §5.13 checks pass with `k` and the R3 event restored; ready to merge.

**Done:**
- Restored the specified fire spread `k=0.06` and step-15 R3 closures in build_presets.py and all four JSON presets. #28 had changed those to k=0.03 and R4, outside the tuning values permitted by PRD §5.13.
- Diagnosed both remaining failures by direct measurement rather than guessing: check 1 failed because no sampled plan (up to 300 samples) ever brought `fire_extent` under its original floor of 30 — 4 of 5 other floors always cleared, `fire_extent` alone blocked every sample. Check 3 failed because Valley Junction connects directly to Pine Ridge (R4), Shelter South (R5) and Shelter East (R7); once the fixed-rule plan's resources leave BASE through R3 at step 0–5, every later leg shuttles between those nodes without ever needing R3 again, so the step-15 closure had nothing to disrupt.
- Retuned within the permitted set: raised `fire_extent`'s floor/aspiration from 30/22 to 60/45 (the original floor was calibrated against a fire rule this scenario no longer uses once `k` is restored), and raised travel times on R4/R5/R7 (4→8, 3→6, 5→9) so a later wave's route back through FORK/R3 becomes competitive again instead of always bypassing it.
- Regenerated all four presets from `build_presets.py`; ran the full (non-quick) `scenarios/tune.py`: **all 9 checks pass**, seeds 1–3. Fixed the backend tests that pinned the old travel times, the old R4 event target and the old `k` (`test_sim_world.py`, `test_sim_engine.py`, `test_validate.py`): 256 backend tests pass. Frontend typecheck/build/e2e unaffected (it reads a separate, pre-existing `scenarios/ucsc-demo/` copy, not these files).
- Replaced #28's changelog entry (which claimed values this branch reverts) with the corrected investigation and results in `scenarios/CHANGELOG.md`.

**Next steps:** none required; open for Madhav/Rohaan review per the ask below.

**Gotchas:** The committed `normal` plan's third-wave return trip now crosses FORK/R3 via a fuel-triggered refuel (not a redesigned route choice) — if `FixedRulePlanner`'s fuel logic changes later, re-run `scenarios/tune.py` to confirm check 3 still passes.

**How to verify:**
```bash
cd backend && uv run python ../scenarios/tune.py          # full 300/500 samples, not --quick
uv run pytest -q                                           # 256 passed
cd ../frontend && npx tsc --noEmit -p . && npm run build --silent && npm run test
```

**Asks for other owners:** Madhav/Rohaan: review the `fire_extent` target change and the R4/R5/R7 travel-time changes against the PRD's narrative intent for Valley Junction's road layout — these are legible, re-measured numbers, not guesses, but a scenario-design call is still a design call.

## Session log

### 2026-10-11T00:35Z · codex · Tisha Gangar
**Status:** PRD fire rate and R3 events restored; permitted-value tuning remains WIP
```text
HEAD 8c5520b · behind origin/main: 0
-- commits on branch --
8c5520b feat(sim): §5.13 tuning gate and G2 tuning (k 0.06→0.03, closure R3→R4)
4c323a8 Merge remote-tracking branches 'origin/sim/rohaan-a4-sim-fixes' and 'origin/sim/rohaan-a4-fixed-rule' into sim/rohaan-a4-tune
ae13133 fix(sim): no input mutation, post-clear roads, crew engines, locked edges, deferred out-of-service
d5992f9 feat(baselines): fixed-rule baseline (PRD §11.2, FR-060)
-- uncommitted --
 M scenarios/build_presets.py
 M scenarios/compound_failure.json
 M scenarios/normal.json
 M scenarios/road_closure.json
 M scenarios/wind_shift.json
?? docs/handoff/sim__tisha-a4-prd-tuning.md
-- diffstat vs main --
 backend/app/baselines/__init__.py         |   1 +
 backend/app/baselines/fixed_rule.py       | 263 ++++++++++++++++++++++++++++++
 backend/app/sim/engine.py                 |   9 +-
 backend/app/sim/plans.py                  |  46 ++++--
 backend/app/sim/service.py                |  31 +++-
 backend/tests/test_fixed_rule.py          |  69 ++++++++
 backend/tests/test_sim.py                 |   5 +-
 backend/tests/test_sim_engine.py          |   6 +-
 backend/tests/test_sim_fixes.py           | 111 +++++++++++++
 backend/tests/test_sim_world.py           |   6 +-
 docs/handoff/sim__rohaan-a4-fixed-rule.md |  30 ++++
 docs/handoff/sim__rohaan-a4-sim-fixes.md  |  25 +++
 scenarios/CHANGELOG.md                    |  17 ++
 scenarios/tune.py                         | 247 ++++++++++++++++++++++++++++
 14 files changed, 844 insertions(+), 22 deletions(-)
```
