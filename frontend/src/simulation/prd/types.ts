/**
 * TypeScript mirror of the PRD section 7 data contracts, scoped to what the
 * incident scene and environmental controls consume.
 *
 * OWNERSHIP: WS-C (Tisha) is the sole editor of `backend/app/models.py` and of
 * the generated `frontend/src/types.ts` (AGENTS.md section 2). This file is a
 * WS-A local mirror so the scene can render from fixtures before the backend
 * exists, per PRD section 12.2 "Independent start". It is superseded by the
 * generated export at G0/G1 and must not be hand-maintained past that point.
 * The field list is raised under "Asks for other owners" in the branch handoff.
 */

// --- section 7.1 enums ------------------------------------------------------

export type AgentId = "EVAC" | "FIRE" | "LOG";

export type ResourceType = "bus" | "transport" | "crew";

export type TaskType =
  | "drive"
  | "load"
  | "unload"
  | "transfer_crew"
  | "contain"
  | "clear_road"
  | "refuel"
  | "hold";

export type RoadStatus = "OPEN" | "CLOSED_CLEARABLE" | "CLOSED_HARD";

export type CellState = "UNBURNED" | "BURNING" | "BURNED_OUT" | "EXTINGUISHED";

export type WindDir = "N" | "NE" | "E" | "SE" | "S" | "SW" | "W" | "NW";

export type PlanState =
  | "PROPOSED"
  | "EVALUATED"
  | "CHALLENGED"
  | "PARTIALLY_ACCEPTED"
  | "UNANIMOUS"
  | "COMMITTED"
  | "REJECTED_AT_COMMIT"
  | "WITHDRAWN"
  | "STALE"
  | "ESCALATED"
  | "SUPERSEDED";

export type EvalBasis =
  | "view_EVAC"
  | "view_FIRE"
  | "view_LOG"
  | "authoritative"
  | "union";

export type ViolationCode =
  | "ROAD_CLOSED"
  | "ROAD_NOT_ENGINE_CAPABLE"
  | "RESOURCE_DOUBLE_BOOKED"
  | "RESOURCE_UNAVAILABLE"
  | "UNKNOWN_RESOURCE"
  | "VEHICLE_OVER_CAPACITY"
  | "SHELTER_OVER_CAPACITY"
  | "FUEL_INSUFFICIENT"
  | "WRONG_LOCATION"
  | "TARGET_TOO_INTENSE"
  | "TARGET_OUT_OF_REACH"
  | "MIXED_PAYLOAD"
  | "SCHEDULE_OVERRUN"
  | "LOCKED_LEG_CHANGED"
  | "NO_CHANGE";

export type MetricName =
  | "assisted_completion"
  | "civilian_exposure"
  | "fire_extent"
  | "crew_risk_steps"
  | "logistics_risk";

/** How a snapshot reached the viewer. `fixture` is never presented as live. */
export type ViewerMode = "live" | "replay" | "fixture";

/** Node kinds the scene draws with distinct shapes, not colour alone. */
export type NodeRole = "zone" | "shelter" | "base" | "junction";

// --- section 7.2 world state ------------------------------------------------

export type Road = {
  id: string;
  a: string;
  b: string;
  travel_steps: number;
  capacity: number;
  engine_ok: boolean;
  initial_status: RoadStatus;
  status_override: RoadStatus | null;
  clear_progress: number;
};

export type Zone = {
  id: string;
  name: string;
  cell: string;
  unassisted_initial: number;
  assisted_initial: number;
  self_evacuated: number;
  assisted_picked_up: number;
};

export type Shelter = {
  id: string;
  name: string;
  cell: string;
  capacity: number;
  background: number;
  arrivals: number;
};

export type Cell = {
  id: string;
  x: number;
  y: number;
  fuel_initial: number;
  fuel_burned: number;
  firebreak_bonus: boolean;
  state: CellState;
  intensity: number;
  ignited_step: number | null;
};

export type Resource = {
  id: string;
  type: ResourceType;
  name: string;
  node: string | null;
  edge: string | null;
  edge_steps_left: number;
  /**
   * PROPOSED ADDITION to PRD section 7.2 (WS-A ask on WS-C): the node this
   * resource is driving toward while on an edge. `edge` plus `edge_steps_left`
   * fix how far along the road a vehicle is but not which way it faces, so a
   * mid-edge marker cannot be placed without it. Optional until the shared
   * schema carries it; the scene falls back to `road.a` toward `road.b`.
   */
  edge_to?: string | null;
  capacity: number;
  fuel_capacity: number | null;
  fuel_used: number;
  aboard_people: Record<string, number>;
  aboard_crew: string | null;
  engine_node: string | null;
  available: boolean;
};

export type Wind = { direction: WindDir; speed: number };

export type ScheduledEvent = {
  event_id: string;
  step: number;
  kind: "wind_change" | "road_status" | "resource_status";
  target: string | null;
  value: string | number | null;
  public: boolean;
};

export type Metrics = {
  civilian_exposure: number;
  assisted_completion: number | null;
  assisted_sheltered: number;
  assisted_demand: number;
  evacuation_completion_step: number | null;
  fire_extent: number;
  burning_cell_steps: number;
  crew_risk_steps: number;
  logistics_risk: number;
  invalid_attempted: number;
  invalid_executed: number;
};

export type Leg = {
  resource_id: string;
  kind: "traverse" | "load" | "unload" | "work" | "board" | "drop" | "refuel";
  edge_id: string | null;
  node: string | null;
  start_step: number;
  end_step: number;
};

export type WorldState = {
  schema_version: string;
  run_id: string;
  scenario_id: string;
  seed: number;
  step: number;
  state_version: number;
  roads: Record<string, Road>;
  zones: Record<string, Zone>;
  shelters: Record<string, Shelter>;
  cells: Record<string, Cell>;
  resources: Record<string, Resource>;
  wind: Wind;
  committed_plan_hash: string | null;
  active_legs: Leg[];
  metrics_so_far: Metrics | null;
  paused: boolean;
};

// --- section 7.3 target, section 7.6 plan and evaluation --------------------

export type Target = {
  metric: MetricName;
  direction: "min" | "max";
  aspiration: number;
  floor: number;
  revisable_by_agent: boolean;
};

export type Assignment = {
  order: number;
  locked: boolean;
  resource_id: string;
  task: TaskType;
  origin: string | null;
  destination: string | null;
  route_ids: string[];
  start_step: number;
  end_step: number;
  wait_steps: number;
  people_count: number | null;
  zone_id: string | null;
  shelter_id: string | null;
  crew_id: string | null;
  target_cells: string[];
  edge_id: string | null;
  duration_steps: number | null;
};

export type Plan = {
  schema_version: string;
  plan_id: string;
  plan_hash: string;
  proposer: AgentId;
  parent_plan_id: string | null;
  run_id: string;
  dp_id: string;
  state_version: number;
  assignments: Assignment[];
  evidence_ids: string[];
  state: PlanState;
  evaluation_ids: string[];
  tradeoffs: string[];
  expected_shelter_use: Record<string, number>;
};

export type Violation = {
  code: ViolationCode;
  assignment_order: number | null;
  resource_id: string | null;
  road_id: string | null;
  detail: string;
};

export type TargetCheck = {
  agent_id: AgentId;
  metric: MetricName;
  value: number | null;
  meets_aspiration: boolean;
  meets_floor: boolean;
};

export type Evaluation = {
  schema_version: string;
  evaluation_id: string;
  plan_hash: string;
  basis: EvalBasis;
  kind: "forecast" | "realized";
  run_id: string;
  state_version: number;
  from_step: number;
  horizon: number;
  seed: number;
  valid: boolean;
  violations: Violation[];
  metrics: Metrics | null;
  target_checks: TargetCheck[];
  leg_timing: Leg[];
  trace_ref: string | null;
  sim_ms: number;
};

// --- scene-side scenario view ----------------------------------------------

/**
 * Static scenario facts the scene needs for layout and labelling. The engine
 * owns the dynamic world; this is the part that never changes within a run.
 */
export type SceneScenario = {
  scenario_id: string;
  title: string;
  label: "Synthetic simulation";
  horizon: number;
  step_minutes: number;
  grid: [number, number];
  nodes: Record<string, string>;
  node_names: Record<string, string>;
  node_roles: Record<string, NodeRole>;
  roads: Road[];
  zones: Zone[];
  shelters: Shelter[];
  resources: Resource[];
  targets: Record<AgentId, Target[]>;
  events: ScheduledEvent[];
};

// --- environmental command envelope (A to D, section 12.2) -----------------

/**
 * Commands `EnvironmentalControls` emits. The control surface never mutates
 * world state: WS-D forwards these to WS-C, which applies them under the run
 * lock. "CALM" is an explicit wind option per PRD section 12.3.
 */
export type EnvironmentCommand =
  | { type: "set_wind"; direction: WindDir | "CALM"; speed: number }
  | { type: "set_road_status"; road_id: string; status: RoadStatus }
  | { type: "set_resource_available"; resource_id: string; available: boolean }
  | { type: "inject_preset"; preset: "wind_shift_and_closure" };
