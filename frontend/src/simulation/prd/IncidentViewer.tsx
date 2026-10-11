/**
 * `IncidentViewer` - the A-to-D incident scene interface frozen at G0
 * (PRD section 12.2: `IncidentViewer({snapshot, selectedPlan, evaluation, mode})`).
 *
 * Renders the authoritative PRD world (section 5.2 map, section 5.3 resources)
 * as a readable flat scene. PRD section 12.3 asks WS-A for "a readable
 * isometric/SVG scene behind `IncidentViewer`" first and treats a React Three
 * Fiber scene as a gated enhancement, so this is SVG: no WebGL dependency, it
 * stays legible at 1280x720 and it can be asserted in tests.
 *
 * TWO RULES THIS COMPONENT ENFORCES:
 *
 * 1. Every outcome number comes from an `Evaluation` (PRD invariant A.3,
 *    AC-023). The viewer computes no metric. With no `evaluation` prop it
 *    prints an em dash, never a zero and never a guess.
 * 2. Status is never carried by colour alone (AC-035, NFR-008). Road status
 *    also uses a stroke pattern, a glyph and text; fire intensity is printed
 *    as a number in the cell.
 */

import { useMemo } from "react";

import {
  CELL,
  canvasSize,
  cellRect,
  fanGroups,
  nodePoint,
  resourcePoint,
  roadLabelPoint,
  roadPath,
  roadStatusCue,
  windVector,
} from "./geometry";
import {
  assistedWaiting,
  loadSceneScenario,
  roadStatus,
  unassistedInZone,
  type PresetId,
} from "./scenario";
import type {
  Cell,
  Evaluation,
  Plan,
  Resource,
  SceneScenario,
  ViewerMode,
  WorldState,
} from "./types";

export type IncidentViewerProps = {
  /** Authoritative or belief-view world to draw. */
  snapshot: WorldState;
  /** Plan whose routes are highlighted, if any. */
  selectedPlan?: Plan | null;
  /** The only permitted source of outcome numbers. */
  evaluation?: Evaluation | null;
  /** Provenance label. `fixture` is never presented as live. */
  mode: ViewerMode;
  /**
   * Static layout facts. Optional: defaults to the preset named by
   * `snapshot.scenario_id`, so the frozen four-prop signature stays usable.
   */
  scenario?: SceneScenario;
};

const MODE_LABEL: Record<ViewerMode, string> = {
  live: "LIVE",
  replay: "REPLAY",
  fixture: "FIXTURE",
};

const RESOURCE_GLYPH: Record<Resource["type"], string> = {
  bus: "B",
  transport: "V",
  crew: "C",
};

export function IncidentViewer({
  snapshot,
  selectedPlan = null,
  evaluation = null,
  mode,
  scenario,
}: IncidentViewerProps) {
  const scene = useMemo(
    () => scenario ?? loadSceneScenario(snapshot.scenario_id as PresetId),
    [scenario, snapshot.scenario_id],
  );

  const size = canvasSize(scene.grid);
  const cells = useMemo(() => Object.values(snapshot.cells), [snapshot.cells]);
  const resources = useMemo(
    () =>
      Object.values(snapshot.resources).sort((a, b) => a.id.localeCompare(b.id)),
    [snapshot.resources],
  );
  const fans = useMemo(() => fanGroups(resources), [resources]);

  /** Roads this plan drives over, for the route overlay. */
  const planRoads = useMemo(() => {
    const ids = new Set<string>();
    for (const assignment of selectedPlan?.assignments ?? []) {
      for (const roadId of assignment.route_ids) ids.add(roadId);
    }
    return ids;
  }, [selectedPlan]);

  const wind = windVector(snapshot.wind.direction);
  const minutes = snapshot.step * scene.step_minutes;

  return (
    <section className="iv" aria-label={`Incident scene, ${scene.title}`}>
      <header className="iv-head">
        <div className="iv-head-main">
          <h2 className="iv-title">{scene.title}</h2>
          <p className="iv-sub">
            Step {snapshot.step} of {scene.horizon} &middot; {minutes} simulated
            minutes &middot; state version {snapshot.state_version}
            {snapshot.paused ? " · paused" : ""}
          </p>
        </div>
        <div className="iv-badges">
          <span className={`iv-mode iv-mode-${mode}`}>{MODE_LABEL[mode]}</span>
          <span className="iv-synthetic">{scene.label}</span>
        </div>
      </header>

      <div className="iv-stage">
        <svg
          className="iv-svg"
          viewBox={`0 0 ${size.width} ${size.height}`}
          role="img"
          aria-labelledby="iv-svg-title iv-svg-desc"
          preserveAspectRatio="xMidYMid meet"
        >
          <title id="iv-svg-title">
            {`Synthetic ${scene.grid[0]} by ${scene.grid[1]} incident grid`}
          </title>
          <desc id="iv-svg-desc">{describeScene(snapshot, scene)}</desc>

          <g className="iv-cells">
            {cells.map((cell) => (
              <CellRect key={cell.id} cell={cell} />
            ))}
          </g>

          <g className="iv-grid-lines" aria-hidden="true">
            {gridLines(scene.grid).map((line) => (
              <line
                key={line.key}
                x1={line.x1}
                y1={line.y1}
                x2={line.x2}
                y2={line.y2}
              />
            ))}
          </g>

          <g className="iv-roads">
            {scene.roads.map((road) => {
              const live = snapshot.roads[road.id] ?? road;
              const cue = roadStatusCue(roadStatus(live));
              const onRoute = planRoads.has(road.id);
              const label = roadLabelPoint(scene, road);
              return (
                <g key={road.id} className="iv-road">
                  {onRoute && (
                    <path
                      className="iv-road-route"
                      d={roadPath(scene, road)}
                      fill="none"
                    />
                  )}
                  <path
                    className={`iv-road-line iv-road-${cue.status}`}
                    d={roadPath(scene, road)}
                    fill="none"
                    strokeDasharray={cue.dash ?? undefined}
                  />
                  <g
                    className="iv-road-tag"
                    transform={`translate(${label.x} ${label.y})`}
                  >
                    <rect x={-25} y={-11} width={50} height={22} rx={5} />
                    <text className="iv-road-id" y={4}>
                      {`${road.id}${cue.glyph ? ` ${cue.glyph}` : ""}`}
                    </text>
                  </g>
                </g>
              );
            })}
          </g>

          <g className="iv-nodes">
            {Object.keys(scene.nodes).map((nodeId) => (
              <NodeMark key={nodeId} nodeId={nodeId} scene={scene} />
            ))}
          </g>

          <g className="iv-resources">
            {resources.map((resource) => {
              const fan = fans.get(resource.id) ?? { index: 0, count: 1 };
              const point = resourcePoint(
                scene,
                resource,
                snapshot.roads,
                fan.index,
                fan.count,
              );
              const aboard = Object.values(resource.aboard_people).reduce(
                (sum, n) => sum + n,
                0,
              );
              return (
                <g
                  key={resource.id}
                  className={[
                    "iv-res",
                    `iv-res-${resource.type}`,
                    resource.available ? "" : "iv-res-down",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  transform={`translate(${point.x} ${point.y})`}
                >
                  <circle r={13} />
                  <text className="iv-res-glyph" y={4}>
                    {RESOURCE_GLYPH[resource.type]}
                  </text>
                  <text className="iv-res-id" y={25}>
                    {resource.id}
                    {aboard > 0 ? ` · ${aboard}p` : ""}
                    {resource.aboard_crew ? ` · ${resource.aboard_crew}` : ""}
                    {resource.available ? "" : " ✕"}
                  </text>
                </g>
              );
            })}
          </g>

          <WindRose
            x={size.width - 96}
            y={size.height - 44}
            dx={wind.x}
            dy={wind.y}
          />
        </svg>
      </div>

      <div className="iv-panels">
        <ZonePanel snapshot={snapshot} />
        <ShelterPanel snapshot={snapshot} />
        <MetricPanel evaluation={evaluation} />
        <Legend />
      </div>
    </section>
  );
}

function CellRect({ cell }: { cell: Cell }) {
  const rect = cellRect(cell.id);
  const burning = cell.state === "BURNING";
  return (
    <g className={`iv-cell iv-cell-${cell.state}`}>
      <rect
        x={rect.x}
        y={rect.y}
        width={rect.size}
        height={rect.size}
        className={burning ? `iv-fire iv-fire-${cell.intensity}` : undefined}
      />
      {cell.firebreak_bonus && (
        <text className="iv-cell-break" x={rect.x + 6} y={rect.y + 16}>
          {"⚑"}
        </text>
      )}
      {burning && (
        <text
          className="iv-cell-intensity"
          x={rect.x + rect.size - 7}
          y={rect.y + rect.size - 6}
        >
          {cell.intensity}
        </text>
      )}
      {cell.state === "EXTINGUISHED" && (
        <text
          className="iv-cell-out"
          x={rect.x + rect.size - 7}
          y={rect.y + rect.size - 6}
        >
          {"✓"}
        </text>
      )}
    </g>
  );
}

/** Node shapes differ by role so the map does not rely on colour. */
function NodeMark({ nodeId, scene }: { nodeId: string; scene: SceneScenario }) {
  const point = nodePoint(scene, nodeId);
  const role = scene.node_roles[nodeId] ?? "junction";
  const name = scene.node_names[nodeId] ?? nodeId;

  return (
    <g
      className={`iv-node iv-node-${role}`}
      transform={`translate(${point.x} ${point.y})`}
    >
      {role === "zone" && <rect x={-17} y={-13} width={34} height={26} rx={4} />}
      {role === "shelter" && (
        <polygon points="0,-17 17,-3 17,14 -17,14 -17,-3" />
      )}
      {role === "base" && <polygon points="0,-18 18,0 0,18 -18,0" />}
      {role === "junction" && <circle r={9} />}
      <text className="iv-node-id" y={5}>
        {role === "junction" ? "" : nodeId}
      </text>
      <text className="iv-node-name" y={-23}>
        {name}
      </text>
    </g>
  );
}

function WindRose({
  x,
  y,
  dx,
  dy,
}: {
  x: number;
  y: number;
  dx: number;
  dy: number;
}) {
  const length = 26;
  return (
    <g className="iv-wind" transform={`translate(${x} ${y})`} aria-hidden="true">
      <line x1={0} y1={0} x2={dx * length} y2={dy * length} />
      <circle
        className="iv-wind-head"
        cx={dx * length}
        cy={dy * length}
        r={4.5}
      />
    </g>
  );
}

function ZonePanel({ snapshot }: { snapshot: WorldState }) {
  const zones = Object.values(snapshot.zones);
  return (
    <div className="iv-panel">
      <h3>Zones</h3>
      <table>
        <thead>
          <tr>
            <th scope="col">Zone</th>
            <th scope="col">Assisted waiting</th>
            <th scope="col">Unassisted</th>
            <th scope="col">Picked up</th>
          </tr>
        </thead>
        <tbody>
          {zones.map((zone) => (
            <tr key={zone.id}>
              <th scope="row">{zone.name}</th>
              <td>{assistedWaiting(zone)}</td>
              <td>{unassistedInZone(zone)}</td>
              <td>{zone.assisted_picked_up}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="iv-note">World state, not a forecast.</p>
    </div>
  );
}

function ShelterPanel({ snapshot }: { snapshot: WorldState }) {
  const shelters = Object.values(snapshot.shelters);
  return (
    <div className="iv-panel">
      <h3>Shelters</h3>
      <table>
        <thead>
          <tr>
            <th scope="col">Shelter</th>
            <th scope="col">Occupied</th>
            <th scope="col">Capacity</th>
            <th scope="col">Free</th>
          </tr>
        </thead>
        <tbody>
          {shelters.map((shelter) => {
            const occupied = shelter.background + shelter.arrivals;
            return (
              <tr key={shelter.id}>
                <th scope="row">{shelter.name}</th>
                <td>{occupied}</td>
                <td>{shelter.capacity}</td>
                <td>{shelter.capacity - occupied}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="iv-note">World state, not a forecast.</p>
    </div>
  );
}

/**
 * Outcome numbers, and only from an `Evaluation` (AC-023). No evaluation
 * attached means every row reads as an em dash.
 */
function MetricPanel({ evaluation }: { evaluation: Evaluation | null }) {
  const metrics = evaluation?.metrics ?? null;
  const rows: { label: string; value: string }[] = [
    { label: "Civilian exposure", value: fmt(metrics?.civilian_exposure) },
    {
      label: "Assisted completion",
      value:
        metrics == null
          ? "—"
          : metrics.assisted_completion == null
            ? "N/A"
            : `${(metrics.assisted_completion * 100).toFixed(0)}%`,
    },
    { label: "Fire extent", value: fmt(metrics?.fire_extent) },
    { label: "Crew risk steps", value: fmt(metrics?.crew_risk_steps) },
    { label: "Logistics risk", value: fmt(metrics?.logistics_risk) },
  ];

  return (
    <div className="iv-panel">
      <h3>Outcome numbers</h3>
      <dl className="iv-metrics">
        {rows.map((row) => (
          <div key={row.label}>
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
      {evaluation ? (
        <p className="iv-note">
          {evaluation.kind === "realized" ? "Executed" : "Predicted"} &middot;{" "}
          {basisLabel(evaluation.basis)} &middot; {evaluation.evaluation_id}
        </p>
      ) : (
        <p className="iv-note">
          No evaluation attached. The scene never computes a metric itself.
        </p>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="iv-panel">
      <h3>Legend</h3>
      <ul className="iv-legend">
        <li>
          <span className="iv-key iv-key-zone" aria-hidden="true" /> Rounded box
          - residential or recreation zone
        </li>
        <li>
          <span className="iv-key iv-key-shelter" aria-hidden="true" /> House
          shape - shelter
        </li>
        <li>
          <span className="iv-key iv-key-base" aria-hidden="true" /> Diamond -
          response base
        </li>
        <li>
          <span className="iv-key iv-key-junction" aria-hidden="true" /> Small
          circle - road junction
        </li>
        <li>Solid road - open</li>
        <li>Long dashes {"△"} - closed, a crew can clear it</li>
        <li>Short dots {"✕"} - closed, not clearable</li>
        <li>Number in a cell - fire intensity 1 to 4</li>
        <li>
          {"✓"} in a cell - extinguished; {"⚑"} - firebreak
        </li>
        <li>B bus &middot; V multi-purpose transport &middot; C fire crew</li>
      </ul>
    </div>
  );
}

function gridLines(grid: [number, number]) {
  const [cols, rows] = grid;
  const size = canvasSize(grid);
  const origin = cellRect("c0_0");
  const out: {
    key: string;
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  }[] = [];
  for (let x = 0; x <= cols; x += 1) {
    const px = origin.x + x * CELL;
    out.push({
      key: `v${x}`,
      x1: px,
      y1: origin.y,
      x2: px,
      y2: size.height - origin.y,
    });
  }
  for (let y = 0; y <= rows; y += 1) {
    const py = origin.y + y * CELL;
    out.push({
      key: `h${y}`,
      x1: origin.x,
      y1: py,
      x2: size.width - origin.x,
      y2: py,
    });
  }
  return out;
}

/** Text alternative for the SVG, so the scene is not colour or shape only. */
export function describeScene(
  snapshot: WorldState,
  scene: SceneScenario,
): string {
  const burning = Object.values(snapshot.cells).filter(
    (cell) => cell.state === "BURNING",
  );
  const closed = scene.roads.filter(
    (road) => roadStatus(snapshot.roads[road.id] ?? road) !== "OPEN",
  );
  const parts = [
    `Step ${snapshot.step} of ${scene.horizon}.`,
    `Wind blowing toward ${snapshot.wind.direction} at speed ${snapshot.wind.speed}.`,
    burning.length === 0
      ? "No cells burning."
      : `${burning.length} cells burning: ${burning
          .map((cell) => `${cell.id} at intensity ${cell.intensity}`)
          .join(", ")}.`,
    closed.length === 0
      ? "All roads open."
      : `Roads not open: ${closed
          .map((road) => {
            const live = snapshot.roads[road.id] ?? road;
            return `${road.id} ${roadStatusCue(roadStatus(live)).text}`;
          })
          .join("; ")}.`,
  ];
  return parts.join(" ");
}

function basisLabel(basis: Evaluation["basis"]): string {
  switch (basis) {
    case "authoritative":
      return "Predicted (simulator)";
    case "union":
      return "Predicted (all evidence)";
    case "view_EVAC":
      return "Predicted by Evacuation's view";
    case "view_FIRE":
      return "Predicted by Fire Operations' view";
    case "view_LOG":
      return "Predicted by Logistics' view";
  }
}

function fmt(value: number | null | undefined): string {
  return value == null ? "—" : String(value);
}
