# Browser simulation integration

WS-A ships **two separately labelled models**. They answer different questions, their
numbers are never mixed, and each has its own entry point:

| Model | Entry | World | Status |
|---|---|---|---|
| PRD incident scene | `?view=prd` | PRD section 5.2: 10x6 grid, 8 nodes, 11 roads, resources, people | Scene and controls built; **authoritative simulator not built yet** |
| `ucsc-visual-v1` | default route | 40x30 cells at 8 m, 10-second ticks, surface fire and embers | Complete, documented in the rest of this file |

Standalone entry for both: `src/main.tsx`. Do not edit generated WS-C types or WS-B
code to integrate with either.

## PRD incident scene: the A-to-D contract frozen at G0

These are the two interface names PRD section 12.2 freezes. Both live in
`frontend/src/simulation/prd/` and are owned by WS-A.

```ts
import { IncidentViewer } from "frontend/src/simulation/prd/IncidentViewer";
import { EnvironmentalControls } from "frontend/src/simulation/prd/EnvironmentalControls";

<IncidentViewer
  snapshot={world}            // PRD 7.2 WorldState, authoritative or a belief view
  selectedPlan={plan}         // PRD 7.6 Plan or null; its route_ids are overlaid
  evaluation={evaluation}     // PRD 7.6 Evaluation or null
  mode="live"                 // "live" | "replay" | "fixture"
/>

<EnvironmentalControls
  environment={world.wind}
  resources={world.resources}
  roads={world.roads}
  disabled={world.paused}
  onCommand={(command) => api.send(command)}
/>
```

`IncidentViewer` also accepts an optional `scenario` prop; left out, it loads the
preset named by `snapshot.scenario_id`.

**The viewer renders a metric only when it is present on `evaluation`.** With no
evaluation it prints an em dash. It never computes, derives or defaults an outcome
number (PRD invariant A.3, AC-023). Zone and shelter counts are world state, labelled
as such, not forecasts.

**The controls never mutate state.** They emit one of these and nothing else; WS-D
forwards them to WS-C, which applies them under the run lock and republishes:

```ts
type EnvironmentCommand =
  | { type: "set_wind"; direction: WindDir | "CALM"; speed: number }
  | { type: "set_road_status"; road_id: string; status: RoadStatus }
  | { type: "set_resource_available"; resource_id: string; available: boolean }
  | { type: "inject_preset"; preset: "wind_shift_and_closure" };
```

There is deliberately no command to open a road by fiat, add a resource, enlarge a
shelter or grant fuel: hard constraints are never waived from the UI (invariant 7).
A road reopens only through a crew's `clear_road` task.

### Open asks on other owners

- **WS-C:** `frontend/src/simulation/prd/types.ts` is a WS-A mirror of the PRD
  section 7 contracts so the scene could be built before the backend existed. It is
  superseded by the generated `frontend/src/types.ts` at G0/G1. Please re-export
  these fields rather than letting the two drift.
- **WS-C:** PRD 7.2 `Resource` carries `edge` and `edge_steps_left` but no direction,
  so a mid-edge marker cannot be placed. The mirror proposes an optional
  `edge_to: string | null` naming the node being driven toward. Without it the scene
  assumes travel from `road.a` toward `road.b`.
- **WS-D:** mount the two components above and route `onCommand` through the API.
  Decide whether the manual experiment controls stay visible in backend mode.

### Fixtures

`scenarios/fixtures/normal-reset.json` is the shared step-0 world, generated from
`scenarios/ucsc-demo/normal.json` (moved here, alongside the demo's other three
presets, when the real backend `scenarios/normal.json` etc. -- a different schema
entirely, built independently by WS-A/A1-A3 -- claimed those filenames).
`scenarios/fixtures/normal-render-series.json` is six
hand-authored frames that exercise the renderer; it is labelled in-file and on-screen
as a fixture and must never be presented as a forecast, a replay or a result.

## `ucsc-visual-v1`: worker and ownership

`simulation.worker.ts` owns model state. `types.ts` defines a local protocol, **not PRD §7's backend schema**. The discriminator `model: "ucsc-visual-v1"` distinguishes its semantics.

Commands: `reset`, `play`, `step`, `intervene`, `evaluate`. Replies: `snapshot`, `evaluation`, `error`. At most one interval runs. Every physical tick/operator event increments `state_version`. Reset starts revision zero; consumers must discard pending requests on reset. `run_id` encodes the seed, not a globally unique session ID.

Actions are synthetic operator experiments, not crew arrival or plan acceptance. Forecasts clone the world and run 1–120 ticks without authoritative mutation. Consumers must compare state versions before using returned predictions. Road closure is an observation; no routing is simulated.

## Same-page observation/evaluation seam

```ts
window.addEventListener("rescuemesh:snapshot", (event) => {
  const world = (event as CustomEvent).detail;
  // Forward only observations permitted to the appropriate agent.
  // This visual slice exposes full state; it does not implement PRD belief masking.
});

window.dispatchEvent(
  new CustomEvent("rescuemesh:evaluate", {
    detail: {
      type: "evaluate",
      requestId: "fire-ops-forecast-01",
      expectedVersion: 12, // latest snapshot, not this example literal
      intervention: { type: "suppress", cells: [366, 367] },
      steps: 60, // 10 minutes
    },
  }),
);

window.addEventListener("rescuemesh:evaluation", (event) => {
  // Handle requestId, state_version and metrics; discard stale results.
});
```

No network listener, cross-origin bridge, secret or arbitrary-code executor is installed. This is a same-page seam, not an authenticated API. Rendering and physics can operate beside an agent service, but **that service is not connected**. A bounded forecast temporarily occupies the physics worker while rendering remains independent.

## Other workstreams

- **WS-B:** real actors, belief masking, canonical hash, unanimous gate and bounded negotiations remain with the agent implementation. Do not substitute legacy fixture messages.
- **WS-C:** define a separate model mode or projection to `Snapshot`. Preserve the authoritative backend schema. Establish unique run IDs and error envelopes before production integration.
- **WS-D:** embed `Scene` beside the real agent timeline; determine availability of local experiment controls in backend mode.

## Export

Export downloads current world, configuration and last 80 observations as JSON. It is a diagnostic snapshot, **not a full replay**. No import/replay or benchmark CSV is implied.
