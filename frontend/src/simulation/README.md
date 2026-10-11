# Browser simulation demo (WS-A, Madhav)

This directory ships **two separately labelled models**. They have different grids,
different time bases and different purposes, and **their numbers are never mixed**.
Neither is the authoritative PRD simulator the backend runs — see
[`/backend/app/sim/`](/backend/app/sim) and the root [`README.md`](/README.md) for that.

| Route | Model | What it is |
|---|---|---|
| `?view=prd` | PRD incident scene | A rendering of the PRD §5.2 world — 10×6 grid, 8 nodes, 11 roads, 3 zones, 2 shelters, 6 resources — driven by committed fixtures in this demo, by the real backend once WS-D wires it in. |
| default | `ucsc-visual-v1` | A browser 3D wildfire experiment at a synthetic 320 × 240 m Music Center / Great Meadow redwood opening, Santa Cruz. |

This demo's PRD scene reads its own fixture copies of the PRD world (`/scenarios/ucsc-demo/`),
not the backend's authoritative `/scenarios/normal.json` etc. — see the naming note in
[`/scenarios/README.md`](/scenarios/README.md). Nothing in either model here is a forecast,
a replay or a benchmark result until `runs/results.csv` exists.

## The PRD incident scene (`?view=prd`)

WS-A queue item A1: the scenario presets, the PRD §7 snapshot contract and the two
A→D interfaces PRD §12.2 freezes at G0, `IncidentViewer` and `EnvironmentalControls`.
It is a flat SVG scene, which is what PRD §12.3 asks for first; a 3D PRD scene stays
available as that section's gated enhancement.

Road status carries a stroke pattern, a glyph and words as well as colour; node roles
differ by shape; fire intensity is printed in the cell. Status is never colour-only
(AC-035).

Scenario values live in `/scenarios/` and never as code constants — see
[`/scenarios/README.md`](/scenarios/README.md). The A→D contract is in
[`/docs/simulation-integration.md`](/docs/simulation-integration.md).

## The UCSC forest-edge model (default route)

React + Three.js render the landscape; an independent Web Worker advances
deterministic surface-fire and ember physics. No API key or Python runtime required.

## Run either model

From `frontend/`, requires Node.js 22.12+ (tested with Node 24):

```bash
npm ci
npm run dev
```

Open the printed local URL. Select a weather profile, run or step the model, inspect terrain cells, switch fuel/fire layers, change conditions while paused, and export a snapshot. Reset reproduces the selected seed. `1×` means 10 simulated seconds per 500 ms wall time.

```bash
npm test
npm run build
npm run preview
```

The production site is static output in `dist/`, including the physics worker. Serve it over HTTP(S); opening `index.html` as `file://` will not work. WebGL2 and Web Workers are required for the full experience. WebGL failures show a message while numerical controls remain usable. Fonts use Google Fonts with local sans-serif fallbacks; geometry and simulation require no external data feed.

## Implemented

- Procedural redwood grove, terrain cutaway, meadow, schematic buildings and access road.
- Seeded surface spread driven by wind, slope, fuel and moisture; finite fuel mass and heat accounting.
- Ember lift, aerodynamic drag, gravity, landing and probabilistic spot ignitions.
- Coastal / dry autumn / offshore presets; run, pause, step, speed, reset and cell inspection.
- Operator ignition/treatment and road-closure experiments; counterfactual forecasts on cloned state.
- Responsive UI, orbit/overhead views, fuel/fire layers, computed metrics and snapshot export.
- Agent observation/evaluation seam. **Live agents are not connected** and no negotiations or results are fabricated.

## Boundaries

This is a synthetic research/demo model, not an emergency tool, surveyed campus model, validated wildfire forecast, CFD simulation or full PRD implementation. It does not model real populations, evacuation, crew dispatch, crown fires, smoke toxicity or structural fires. The extended visual model deliberately differs from the PRD's 10×6 graph-and-grid benchmark; do not mix their metrics.

See [simulation plan and sources](/docs/simulation-plan.md), [integration contract](/docs/simulation-integration.md), and [scenario configuration](/scenarios/ucsc-music-center.json).

## Layout

```text
frontend/src/simulation/
  prd/                         PRD incident scene (?view=prd)
    types.ts                   mirror of PRD section 7, superseded by WS-C's generated types
    scenario.ts                preset loading and step-0 world construction
    geometry.ts                pure grid-to-SVG projection
    IncidentViewer.tsx         frozen A-to-D scene interface
    EnvironmentalControls.tsx  frozen A-to-D control interface
    fixtures.ts                fixture playback, not a simulator
    Harness.tsx                isolated harness, no backend needed
    incident.css               scoped styling
  App.tsx / simulation.css     ucsc-visual-v1 demo UI
  Scene.tsx                    Three.js rendering and picking
  terrain.ts                   procedural geography
  engine.ts                    pure deterministic physics and forecasts
  simulation.worker.ts         independent clock and state owner
  types.ts                     local visual-model protocol
  tests/                       engine, PRD scenario and PRD render suites
```

Scenario inputs, presets, fixtures and tuning history live in [`/scenarios/`](/scenarios/README.md).

The pre-existing uncommitted UI scaffold is preserved in `frontend/src/App.tsx`, `frontend/src/data/scenario.ts`, `frontend/src/styles.css` and `docs/legacy-scaffold-plan.md`; it is not mounted. This demo is separate from the team's backend and agent branches — see the root [`README.md`](/README.md) for how they fit together.
