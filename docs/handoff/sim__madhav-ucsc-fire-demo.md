# Handoff: sim/madhav-ucsc-fire-demo

| Field | Value |
|---|---|
| Branch | `sim/madhav-ucsc-fire-demo` |
| Owner | Madhav |
| Workstream / queue item | WS-A / A1 (plus the earlier standalone 3D slice) |
| PRD references | §5.2, §5.3, §5.9, §5.11, §5.12, §7.2, §7.6, §12.2, §12.3; AC-014, AC-022, AC-023, AC-035 |
| Date | 2026-10-10 |

## Goal

Deliver WS-A queue item **A1**: "Specify simulation contracts, fixture snapshot and
scenario skeleton; start isolated viewer harness", completion evidence "reset fixture
renders locally" (PRD §12.3). The branch also carries the earlier standalone
`ucsc-visual-v1` 3D forest-edge demo, which is unchanged.

## Current state

**Status:** A1 complete and verified. Ready for PR review. The authoritative
simulator is still unbuilt and is the next session's work.

**Done this session:**

- **PRD world as tuneable JSON** (`scenarios/`). `normal.json` transcribes the PRD
  §5.2/§5.3 tables exactly: 10×6 grid, 8 nodes, roads R1–R11 (R2 `CLOSED_CLEARABLE`
  behind an `OPEN` prior; R8/R9 not engine-capable), zones NC 40/20, PR 120/30,
  VJ 300/60 with public priors, shelters SE 150/40 and SS 350/320 (prior 290), cell
  fuel 0.7 default / 0.2 cleared / 0.9 ridge, firebreak on `c2_1`, initial fire
  `c0_2` I=2, `c0_3` I=2, `c1_3` I=1, resources B1/B2/V1/C1/C2/C3, wind toward E
  speed 2, §5.5 coefficients and §5.4 durations in `fire_params`, §5.9 evidence and
  §5.12 targets. `wind_shift`, `road_closure` and `compound_failure` carry only their
  §5.11 step-15 events and inherit the rest via `extends`.
- **PRD §7 snapshot contract in TypeScript** (`frontend/src/simulation/prd/types.ts`),
  explicitly a WS-A mirror to be superseded by WS-C's generated `frontend/src/types.ts`.
- **`scenario.ts`** resolves `extends`, expands the compact cell spec into 60 cells and
  builds the step-0 `WorldState`. Data construction only — **no fire rules in TS**.
- **`geometry.ts`**: pure, deterministic grid-to-SVG projection with per-road bows so
  collinear roads (R1 BASE-FORK sits on R6 FORK-SE) never overlap.
- **The two A-to-D interfaces PRD §12.2 freezes at G0**, under exactly those names:
  `IncidentViewer({snapshot, selectedPlan, evaluation, mode})` and
  `EnvironmentalControls({environment, resources, roads, disabled, onCommand})`.
- **`Harness.tsx`** mounts both against committed fixtures at `?view=prd`, with a
  preset picker, a frame scrubber, a plan-route toggle and a command log.
- **Fixtures:** `scenarios/fixtures/normal-reset.json` (generated step-0 world, the
  shared G0 fixture) and `normal-render-series.json` (six hand-authored frames).
- **Docs:** `scenarios/README.md`, a `scenarios/CHANGELOG.md` entry, the frozen
  contract and open asks in `docs/simulation-integration.md`, and a rewritten
  `README.md` describing the two labelled models.
- **Tests:** 50 new, 60 total, all passing. `npm run build` and `scripts/check.sh` pass.

**Three defects found in browser review and fixed:**

1. Burning cells rendered flat — `.iv-cell rect` outspecified `.iv-fire-N`, so the
   unburned fill won. Fixed by matching specificity.
2. Four resources start at BASE and their markers piled on the node glyph. Fixed by
   laying markers out in a centred row below the node (`fanPoint`).
3. The wind control kept a stale pending value after the world moved to SE/3. The
   controls are now keyed on `state_version`, matching PRD §5.8 (a new version voids
   in-flight work).

**In progress:** nothing half-finished.

**Next steps (ordered, concrete):**

1. **Build the authoritative simulator — this is the project's critical path.**
   PRD §12.4: "shared contracts → A step/validation/evaluation services → B live tools
   and unanimous gate → C integration". Ali's B3/B4, Tisha's C4 and both baselines all
   block on it, and none of it exists.
   - **A2** `backend/app/sim/`: deterministic step engine — §5.7 step order, §5.5 fire
     (CRN ignition `u = SHA-256("{seed}:{step}:{cell}")[:8] / 2^64`, growth every 4,
     burnout under 0.05, suppression 0.7 engine / 0.5 hand / +0.15 firebreak capped at
     0.9), §5.6 people and hazard, road capacity waits with the §5.7 priority rule, and
     the §5.6 conservation invariants checked after every step.
   - **A3** `validate_plan` with all 15 §7.1 violation codes; `evaluate_plan` on a clone
     asserting the authoritative hash is unchanged (AC-022); `BeliefView` masking only
     statics (§5.9); §11.1 metrics.
   - **A4** events, locked legs, `baselines/fixed_rule.py`, `scenarios/tune.py` for the
     §5.13 G2 checks.
2. Install the backend toolchain: **`uv` is not installed on this machine** and there is
   no `backend/` directory yet.
3. Point `IncidentViewer` at real snapshots once WS-C serves them (queue item A5), and
   retire the fixture series at that point.

**Decisions and why:**

- **SVG, not Three.js, for the PRD scene.** PRD §12.3 says WS-A "first delivers a
  readable isometric/SVG scene behind `IncidentViewer`" and makes React Three Fiber a
  gated enhancement; §12.6 says shed 3D first under pressure. SVG is also faster, needs
  no WebGL and can be asserted in tests.
- **`ucsc-visual-v1` untouched.** It stays on the default route as its own labelled
  model. The two never share metrics; the README says so.
- **No backend file was created at all.** `backend/pyproject.toml` and
  `backend/app/models.py` are WS-C's (AGENTS.md §2), so the PRD types live as a clearly
  marked WS-A mirror under `prd/` instead of being patched into someone else's file.
- **No simulation rules in TypeScript.** The scene renders snapshots; it never steps the
  world. Duplicating the rules would create a second source of truth.
- **The viewer shows no metric without an `Evaluation`.** It prints an em dash rather
  than a zero (AC-023, invariant A.3). The harness attaches no evaluation at all,
  because no simulator has produced one.
- **Compact `cells` spec rather than 60 hand-written cells**, so G2 tuning edits one
  rule instead of sixty entries. The expansion is pinned by tests.

**Gotchas / traps:**

- `scenarios/fixtures/normal-render-series.json` is **hand-authored to exercise
  rendering**. It is not simulator output, not a forecast and not a replay trace. It is
  labelled in-file, on-screen and in a test. Delete it once real snapshots exist.
- `scenarios/fixtures/normal-reset.json` is **generated** from `normal.json`; regenerate
  it rather than hand-editing, or the two will drift.
- The PRD §5.13 G2 tuning checks **have not been run**. `scenarios/tune.py` does not
  exist; it needs the simulator and the fixed-rule planner. The committed numbers are
  the PRD's starting points, not tuned ones.
- The root `tsconfig.json` is a solution-style stub, so `tsx` ignores its
  `compilerOptions` and defaults to the classic JSX transform. `npm test` therefore
  passes `--tsconfig ./tsconfig.app.json`; without it, rendering tests fail with
  "React is not defined".
- Two root files were touched: `src/main.tsx` (one `?view=` switch) and `package.json`
  (that test flag). Everything else is inside WS-A's owned paths.
- `metrics_so_far` is `null`, never a zero-filled object, so an absent metric can never
  be mistaken for a measured zero.
- A missing `favicon.ico` logs one 404 in the console. Pre-existing, harmless.

**How to verify:**

```bash
npm ci
npm test                 # 60 passing: 26 PRD scenario, 24 PRD render, 10 ucsc-visual-v1
npm run build            # tsc -b + vite build
bash scripts/check.sh    # repo gate
npm run dev              # then open ?view=prd
```

In the browser at `?view=prd`: all 8 nodes and 11 roads present; R2 dashed with a
triangle glyph reading "closed, a crew can clear it"; three fire cells at the west edge
showing intensities 2, 2, 1; resources fanned below BASE and FORK; wind reading
"toward E, speed 2"; the outcome panel reading em dashes with "No evaluation attached".
Drag the frame scrubber to frame 5 to see fire growth, an extinguished cell, R2 cleared,
R3 closed with a cross, B2 faded and crossed, B1 at Shelter South with 30 aboard, and
the wind at SE/3. Tick "Show fixture plan route" to overlay R1, R3 and R5. The default
route (no `?view=`) must still load the unchanged UCSC forest-edge demo.

**Asks for other owners (file, owner, what, why):**

- **WS-C / Tisha — `backend/app/models.py` and `frontend/src/types.ts`:** please
  re-export the PRD §7 fields now mirrored in `frontend/src/simulation/prd/types.ts`,
  then WS-A deletes the mirror. It exists only because WS-A must not edit your files.
- **WS-C / Tisha — PRD §7.2 `Resource`:** `edge` plus `edge_steps_left` fix how far
  along a road a vehicle is but not which way it faces, so a mid-edge marker cannot be
  placed. Proposed optional `edge_to: string | null`. This is a `[contract]` change and
  needs both owners.
- **WS-C / Tisha — `backend/pyproject.toml`:** WS-A needs `pytest` available and a
  `backend/` scaffold before the A2 engine tests can run under `scripts/check.sh`.
- **WS-D / Rohaan:** mount `IncidentViewer` and `EnvironmentalControls` from
  `frontend/src/simulation/prd/` and forward `onCommand` through WS-C's API. Decide
  whether the manual experiment controls stay visible in backend mode.
- **WS-B / Ali:** the scenario presets and the step-0 fixture are ready to build agent
  tools against. `BeliefView` masking is specified in `scenarios/README.md` but is not
  implemented until A3.

**Open questions (with the PRD's provisional answer if any):**

- OPEN-06 "Final scenario parameters and targets" (owner WS-A, due H+14 at the G2
  tuning sign-off). Provisional answer in use: the PRD §5 values, tuned in JSON only.
  Cannot be closed until `tune.py` and the simulator exist.
- Whether the incident scene is later upgraded to React Three Fiber (PRD §12.3 gated
  enhancement) or stays SVG. Not blocking; SVG satisfies the stated requirement.

## Session log

### 2026-10-10T07:29Z · codex · MS
**Status:** Browser 3D simulation complete; 10 tests, build, repository gate and production browser checks passed
```text
HEAD 6c9c12d · behind origin/main: 0
-- commits on branch --
-- uncommitted --
M  .gitignore
M  README.md
A  docs/handoff/sim__madhav-ucsc-fire-demo.md
A  docs/legacy-scaffold-plan.md
A  docs/simulation-integration.md
A  docs/simulation-plan.md
A  frontend/src/simulation/App.tsx
A  frontend/src/simulation/Scene.tsx
A  frontend/src/simulation/engine.ts
A  frontend/src/simulation/simulation.css
A  frontend/src/simulation/simulation.worker.ts
A  frontend/src/simulation/terrain.ts
A  frontend/src/simulation/tests/engine.test.ts
A  frontend/src/simulation/types.ts
A  index.html
A  package-lock.json
A  package.json
A  scenarios/CHANGELOG.md
A  scenarios/ucsc-music-center.json
A  src/App.tsx
A  src/data/scenario.ts
A  src/main.tsx
A  src/styles.css
A  tsconfig.app.json
A  tsconfig.json
A  tsconfig.node.json
A  vite.config.ts
?? docs/simulation-preview.jpg
-- diffstat vs main --
 frontend/src/simulation/types.ts             |   88 ++
 index.html                                   |   16 +
 package-lock.json                            | 2009 ++++++++++++++++++++++++++
 package.json                                 |   29 +
 scenarios/CHANGELOG.md                       |    9 +
 scenarios/ucsc-music-center.json             |   81 ++
 src/App.tsx                                  |  451 ++++++
 src/data/scenario.ts                         |  682 +++++++++
 src/main.tsx                                 |    9 +
 src/styles.css                               |  699 +++++++++
 tsconfig.app.json                            |   21 +
 tsconfig.json                                |    7 +
 tsconfig.node.json                           |   14 +
 vite.config.ts                               |    7 +
 27 files changed, 7848 insertions(+)
```

### 2026-10-10T07:56Z · codex · MS
**Status:** Prepared full simulation branch for PR; synced main and repository gate passed
```text
HEAD 82fd22b · behind origin/main: 0
-- commits on branch --
82fd22b feat(sim): add UCSC forest-edge 3D browser simulation
-- uncommitted --
 M docs/handoff/sim__madhav-ucsc-fire-demo.md
-- diffstat vs main --
 frontend/src/simulation/types.ts             |   88 ++
 index.html                                   |   16 +
 package-lock.json                            | 2009 ++++++++++++++++++++++++++
 package.json                                 |   29 +
 scenarios/CHANGELOG.md                       |    9 +
 scenarios/ucsc-music-center.json             |   81 ++
 src/App.tsx                                  |  451 ++++++
 src/data/scenario.ts                         |  682 +++++++++
 src/main.tsx                                 |    9 +
 src/styles.css                               |  699 +++++++++
 tsconfig.app.json                            |   21 +
 tsconfig.json                                |    7 +
 tsconfig.node.json                           |   14 +
 vite.config.ts                               |    7 +
 28 files changed, 7875 insertions(+)
```

### 2026-10-10T08:51Z · claude-code · MS
**Status:** WS-A A1 complete: PRD scenario presets, PRD section 7 snapshot contract, IncidentViewer and EnvironmentalControls on fixtures; 60 tests green
```text
HEAD 0fa9cd2 · behind origin/main: 0
-- commits on branch --
0fa9cd2 docs(sim): update handoff for PR review
82fd22b feat(sim): add UCSC forest-edge 3D browser simulation
-- uncommitted --
 M README.md
 M docs/handoff/sim__madhav-ucsc-fire-demo.md
 M docs/simulation-integration.md
 M package.json
 M scenarios/CHANGELOG.md
 M src/main.tsx
?? frontend/src/simulation/prd/
?? frontend/src/simulation/tests/prd-render.test.ts
?? frontend/src/simulation/tests/prd-scenario.test.ts
?? scenarios/README.md
?? scenarios/compound_failure.json
?? scenarios/fixtures/
?? scenarios/normal.json
?? scenarios/road_closure.json
?? scenarios/wind_shift.json
-- diffstat vs main --
 frontend/src/simulation/types.ts             |   88 ++
 index.html                                   |   16 +
 package-lock.json                            | 2009 ++++++++++++++++++++++++++
 package.json                                 |   29 +
 scenarios/CHANGELOG.md                       |   43 +
 scenarios/ucsc-music-center.json             |   81 ++
 src/App.tsx                                  |  451 ++++++
 src/data/scenario.ts                         |  682 +++++++++
 src/main.tsx                                 |   14 +
 src/styles.css                               |  699 +++++++++
 tsconfig.app.json                            |   21 +
 tsconfig.json                                |    7 +
 tsconfig.node.json                           |   14 +
 vite.config.ts                               |    7 +
 28 files changed, 8179 insertions(+)
```
