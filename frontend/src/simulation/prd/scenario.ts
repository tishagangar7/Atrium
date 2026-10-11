/**
 * Scenario loading and step-0 world construction for the PRD world
 * (PRD sections 5.2, 5.3, 5.11, 7.2).
 *
 * This module is DATA CONSTRUCTION ONLY. It expands the tuneable JSON in
 * `scenarios/` into the `WorldState` shape the scene renders, and nothing else.
 * The step rules of PRD section 5.5 to 5.7 (ignition, growth, burnout,
 * suppression, capacity waits, conservation) belong to the authoritative
 * simulator in `backend/app/sim/**` and are deliberately NOT duplicated here:
 * PRD section 12.3 requires the scene to follow backend progress rather than
 * run its own physics.
 */

import normalJson from "../../../../scenarios/ucsc-demo/normal.json";
import windShiftJson from "../../../../scenarios/ucsc-demo/wind_shift.json";
import roadClosureJson from "../../../../scenarios/ucsc-demo/road_closure.json";
import compoundFailureJson from "../../../../scenarios/ucsc-demo/compound_failure.json";

import type {
  AgentId,
  Cell,
  NodeRole,
  Resource,
  Road,
  RoadStatus,
  SceneScenario,
  ScheduledEvent,
  Shelter,
  Target,
  WorldState,
  Zone,
} from "./types";

export type PresetId =
  | "normal"
  | "wind_shift"
  | "road_closure"
  | "compound_failure";

export const PRESET_IDS: readonly PresetId[] = [
  "normal",
  "wind_shift",
  "road_closure",
  "compound_failure",
] as const;

/**
 * Raw preset documents. A preset other than `normal` carries only its
 * `events` plus identity and inherits every number from the file named by
 * `extends`, so G2 tuning edits one set of values (PRD section 5.13).
 */
const RAW: Record<PresetId, Record<string, unknown>> = {
  normal: normalJson as unknown as Record<string, unknown>,
  wind_shift: windShiftJson as unknown as Record<string, unknown>,
  road_closure: roadClosureJson as unknown as Record<string, unknown>,
  compound_failure: compoundFailureJson as unknown as Record<string, unknown>,
};

const BY_FILENAME: Record<string, PresetId> = {
  "normal.json": "normal",
  "wind_shift.json": "wind_shift",
  "road_closure.json": "road_closure",
  "compound_failure.json": "compound_failure",
};

/** Resolve the `extends` chain into one flat scenario document. */
export function resolveScenarioDocument(
  preset: PresetId,
): Record<string, unknown> {
  const seen = new Set<string>();
  const chain: Record<string, unknown>[] = [];
  let current: PresetId | undefined = preset;

  while (current) {
    if (seen.has(current)) {
      throw new Error(`scenario extends cycle at "${current}"`);
    }
    seen.add(current);
    const doc: Record<string, unknown> | undefined = RAW[current];
    if (!doc) throw new Error(`unknown scenario preset "${current}"`);
    chain.push(doc);

    const parent: unknown = doc.extends;
    if (parent === undefined || parent === null) break;
    if (typeof parent !== "string") {
      throw new Error(`scenario "${current}" has a non-string extends`);
    }
    const next: PresetId | undefined = BY_FILENAME[parent];
    if (!next) {
      throw new Error(`scenario "${current}" extends unknown "${parent}"`);
    }
    current = next;
  }

  // Base first, so the extending document's own keys win.
  const flat: Record<string, unknown> = {};
  for (const doc of chain.reverse()) Object.assign(flat, doc);
  delete flat.extends;
  return flat;
}

type CellSpec = {
  fuel_default: number;
  fuel_overrides: {
    cells: string[];
    fuel_initial: number;
    fuel_initial_prior?: number;
  }[];
  firebreak_bonus: string[];
  initial_fire: { cell: string; intensity: number }[];
};

/** Cell IDs in reading order: row by row, west to east. Deterministic. */
export function cellIds(cols: number, rows: number): string[] {
  const ids: string[] = [];
  for (let y = 0; y < rows; y += 1) {
    for (let x = 0; x < cols; x += 1) ids.push(`c${x}_${y}`);
  }
  return ids;
}

export function parseCellId(id: string): { x: number; y: number } {
  const m = /^c(\d+)_(\d+)$/.exec(id);
  if (!m) throw new Error(`malformed cell id "${id}"`);
  return { x: Number(m[1]), y: Number(m[2]) };
}

/** Static scenario facts the scene needs for layout and labelling. */
export function loadSceneScenario(preset: PresetId): SceneScenario {
  const doc = resolveScenarioDocument(preset);
  const grid = doc.grid as [number, number];

  return {
    scenario_id: doc.scenario_id as string,
    title: doc.title as string,
    label: doc.label as "Synthetic simulation",
    horizon: doc.horizon as number,
    step_minutes: doc.step_minutes as number,
    grid: [grid[0], grid[1]],
    nodes: doc.nodes as Record<string, string>,
    node_names: doc.node_names as Record<string, string>,
    node_roles: doc.node_roles as Record<string, NodeRole>,
    roads: (doc.roads as Record<string, unknown>[]).map(toRoad),
    zones: (doc.zones as Record<string, unknown>[]).map(toZone),
    shelters: (doc.shelters as Record<string, unknown>[]).map(toShelter),
    resources: (doc.resources as Record<string, unknown>[]).map(toResource),
    targets: doc.targets as Record<AgentId, Target[]>,
    events: (doc.events as ScheduledEvent[]) ?? [],
  };
}

function toRoad(raw: Record<string, unknown>): Road {
  return {
    id: raw.id as string,
    a: raw.a as string,
    b: raw.b as string,
    travel_steps: raw.travel_steps as number,
    capacity: raw.capacity as number,
    engine_ok: raw.engine_ok as boolean,
    initial_status: raw.initial_status as RoadStatus,
    status_override: null,
    clear_progress: 0,
  };
}

function toZone(raw: Record<string, unknown>): Zone {
  return {
    id: raw.id as string,
    name: raw.name as string,
    cell: raw.cell as string,
    unassisted_initial: raw.unassisted_initial as number,
    assisted_initial: raw.assisted_initial as number,
    self_evacuated: 0,
    assisted_picked_up: 0,
  };
}

function toShelter(raw: Record<string, unknown>): Shelter {
  return {
    id: raw.id as string,
    name: raw.name as string,
    cell: raw.cell as string,
    capacity: raw.capacity as number,
    background: raw.background as number,
    arrivals: 0,
  };
}

function toResource(raw: Record<string, unknown>): Resource {
  const type = raw.type as Resource["type"];
  const startNode = raw.start_node as string;
  return {
    id: raw.id as string,
    type,
    name: raw.name as string,
    node: startNode,
    edge: null,
    edge_steps_left: 0,
    capacity: raw.capacity as number,
    fuel_capacity: (raw.fuel_capacity as number | null) ?? null,
    fuel_used: 0,
    aboard_people: {},
    aboard_crew: null,
    // A crew starts co-located with its own engine (PRD section 5.3).
    engine_node: type === "crew" ? startNode : null,
    available: true,
  };
}

/**
 * Expand the compact cell spec into all `cols * rows` cells at step 0.
 * Later overrides win, so the ridge block applies over the fuel default.
 */
function buildCells(
  spec: CellSpec,
  cols: number,
  rows: number,
): Record<string, Cell> {
  const fuel = new Map<string, number>();
  const ids = cellIds(cols, rows);
  for (const id of ids) fuel.set(id, spec.fuel_default);

  for (const override of spec.fuel_overrides) {
    for (const id of override.cells) {
      if (!fuel.has(id)) {
        throw new Error(`fuel override names unknown cell "${id}"`);
      }
      fuel.set(id, override.fuel_initial);
    }
  }

  const firebreak = new Set(spec.firebreak_bonus);
  for (const id of firebreak) {
    if (!fuel.has(id)) throw new Error(`firebreak names unknown cell "${id}"`);
  }

  const fire = new Map<string, number>();
  for (const entry of spec.initial_fire) {
    if (!fuel.has(entry.cell)) {
      throw new Error(`initial fire names unknown cell "${entry.cell}"`);
    }
    fire.set(entry.cell, entry.intensity);
  }

  const cells: Record<string, Cell> = {};
  for (const id of ids) {
    const { x, y } = parseCellId(id);
    const intensity = fire.get(id) ?? 0;
    cells[id] = {
      id,
      x,
      y,
      fuel_initial: fuel.get(id) as number,
      fuel_burned: 0,
      firebreak_bonus: firebreak.has(id),
      state: intensity > 0 ? "BURNING" : "UNBURNED",
      intensity,
      ignited_step: intensity > 0 ? 0 : null,
    };
  }
  return cells;
}

export type ResetOptions = {
  seed?: number;
  /**
   * PRD section 7 formats this as `run-{UTC yyyymmddThhmmZ}-{preset}-s{seed}`.
   * The default here is deliberately timestamp-free so two resets produce
   * byte-identical JSON in tests; AC-014 exempts `run_id` and timestamps.
   */
  run_id?: string;
};

/**
 * Build the step-0 authoritative-shaped world for a preset: every counter
 * zeroed, resources at their start nodes, scheduled events not yet applied.
 *
 * `metrics_so_far` is null, not a zero-filled object: no metric exists until
 * the simulator produces an `Evaluation` (PRD invariant A.3, AC-023).
 */
export function resetWorld(
  preset: PresetId,
  options: ResetOptions = {},
): WorldState {
  const doc = resolveScenarioDocument(preset);
  const seed = options.seed ?? 1;
  const [cols, rows] = doc.grid as [number, number];

  const roads: Record<string, Road> = {};
  for (const raw of doc.roads as Record<string, unknown>[]) {
    const road = toRoad(raw);
    roads[road.id] = road;
  }

  const zones: Record<string, Zone> = {};
  for (const raw of doc.zones as Record<string, unknown>[]) {
    const zone = toZone(raw);
    zones[zone.id] = zone;
  }

  const shelters: Record<string, Shelter> = {};
  for (const raw of doc.shelters as Record<string, unknown>[]) {
    const shelter = toShelter(raw);
    shelters[shelter.id] = shelter;
  }

  const resources: Record<string, Resource> = {};
  for (const raw of doc.resources as Record<string, unknown>[]) {
    const resource = toResource(raw);
    resources[resource.id] = resource;
  }

  return {
    schema_version: "1",
    run_id: options.run_id ?? `run-fixture-${doc.scenario_id as string}-s${seed}`,
    scenario_id: doc.scenario_id as string,
    seed,
    step: 0,
    state_version: 0,
    roads,
    zones,
    shelters,
    cells: buildCells(doc.cells as CellSpec, cols, rows),
    resources,
    wind: doc.wind as WorldState["wind"],
    committed_plan_hash: null,
    active_legs: [],
    metrics_so_far: null,
    paused: true,
  };
}

/** Effective road status: a public override replaces the static value. */
export function roadStatus(road: Road): RoadStatus {
  return road.status_override ?? road.initial_status;
}

/** Assisted residents still waiting in a zone (PRD section 7.2 derived). */
export function assistedWaiting(zone: Zone): number {
  return zone.assisted_initial - zone.assisted_picked_up;
}

/** Unassisted residents still in a zone (PRD section 7.2 derived). */
export function unassistedInZone(zone: Zone): number {
  return zone.unassisted_initial - zone.self_evacuated;
}

/** Fuel left in a cell (PRD section 7.2 derived). */
export function fuelRemaining(cell: Cell): number {
  return Math.max(0, cell.fuel_initial - cell.fuel_burned);
}
