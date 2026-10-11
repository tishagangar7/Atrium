// GENERATED FILE -- do not hand-edit.
// Source: backend/app/models.py. Regenerate with:
//   cd backend && uv run python scripts/gen_types.py
// Owner: Tisha / WS-C (AGENTS.md §12.2).

export type SchemaVersion = "1";
export type AgentId = "EVAC" | "FIRE" | "LOG";
export type ResourceType = "bus" | "transport" | "crew";
export type TaskType = "drive" | "load" | "unload" | "transfer_crew" | "contain" | "clear_road" | "refuel" | "hold";
export type RoadStatus = "OPEN" | "CLOSED_CLEARABLE" | "CLOSED_HARD";
export type CellState = "UNBURNED" | "BURNING" | "BURNED_OUT" | "EXTINGUISHED";
export type WindDir = "N" | "NE" | "E" | "SE" | "S" | "SW" | "W" | "NW";
export type MessageType = "PROPOSE" | "COUNTERPROPOSE" | "CHALLENGE" | "REQUEST_EVIDENCE" | "SHARE_EVIDENCE" | "ACCEPT" | "WITHDRAW" | "ESCALATE";
export type PlanState = "PROPOSED" | "EVALUATED" | "CHALLENGED" | "PARTIALLY_ACCEPTED" | "UNANIMOUS" | "COMMITTED" | "REJECTED_AT_COMMIT" | "WITHDRAWN" | "STALE" | "ESCALATED" | "SUPERSEDED";
export type EvalBasis = "view_EVAC" | "view_FIRE" | "view_LOG" | "authoritative" | "union";
export type Method = "rescuemesh" | "fixed_rule" | "single_agent";
export type RunMode = "live" | "replay" | "benchmark";
export type ViolationCode = "ROAD_CLOSED" | "ROAD_NOT_ENGINE_CAPABLE" | "RESOURCE_DOUBLE_BOOKED" | "RESOURCE_UNAVAILABLE" | "UNKNOWN_RESOURCE" | "VEHICLE_OVER_CAPACITY" | "SHELTER_OVER_CAPACITY" | "FUEL_INSUFFICIENT" | "WRONG_LOCATION" | "TARGET_TOO_INTENSE" | "TARGET_OUT_OF_REACH" | "MIXED_PAYLOAD" | "SCHEDULE_OVERRUN" | "LOCKED_LEG_CHANGED" | "NO_CHANGE";

export interface Evidence {
  evidence_id: string;
  holders: AgentId[];
  field_path: string;
  true_value: string | number | boolean;
  prior_value: string | number | boolean;
  summary: string;
  observed_step: number;
  confidence: "low" | "medium" | "high";
}

export interface Target {
  metric: "assisted_completion" | "civilian_exposure" | "fire_extent" | "crew_risk_steps" | "logistics_risk";
  direction: "min" | "max";
  aspiration: number;
  floor: number;
  revisable_by_agent: boolean;
}

export interface Road {
  id: string;
  a: string;
  b: string;
  travel_steps: number;
  capacity: number;
  engine_ok: boolean;
  initial_status: RoadStatus;
  status_override: RoadStatus | null;
  clear_progress: number;
}

export interface Zone {
  id: string;
  name: string;
  cell: string;
  unassisted_initial: number;
  assisted_initial: number;
  self_evacuated: number;
  assisted_picked_up: number;
}

export interface Shelter {
  id: string;
  name: string;
  cell: string;
  capacity: number;
  background: number;
  arrivals: number;
}

export interface Cell {
  id: string;
  x: number;
  y: number;
  fuel_initial: number;
  fuel_burned: number;
  firebreak_bonus: boolean;
  state: CellState;
  intensity: number;
  ignited_step: number | null;
}

export interface Resource {
  id: string;
  type: ResourceType;
  node: string | null;
  edge: string | null;
  edge_steps_left: number;
  capacity: number;
  fuel_capacity: number | null;
  fuel_used: number;
  aboard_people: Record<string, number>;
  aboard_crew: string | null;
  engine_node: string | null;
  available: boolean;
}

export interface Wind {
  direction: WindDir;
  speed: number;
}

export interface ScheduledEvent {
  event_id: string;
  step: number;
  kind: "wind_change" | "road_status" | "resource_status";
  target: string | null;
  value: string | number | null;
  public: boolean;
}

export interface AssignmentDraft {
  resource_id: string;
  task: TaskType;
  origin: string | null;
  destination: string | null;
  route_ids: string[];
  start_step: number | null;
  people_count: number | null;
  zone_id: string | null;
  shelter_id: string | null;
  crew_id: string | null;
  target_cells: string[];
  edge_id: string | null;
  duration_steps: number | null;
}

export interface Assignment {
  resource_id: string;
  task: TaskType;
  origin: string | null;
  destination: string | null;
  route_ids: string[];
  start_step: number;
  people_count: number | null;
  zone_id: string | null;
  shelter_id: string | null;
  crew_id: string | null;
  target_cells: string[];
  edge_id: string | null;
  duration_steps: number | null;
  order: number;
  locked: boolean;
  end_step: number;
  wait_steps: number;
}

export interface Leg {
  resource_id: string;
  kind: string;
  edge_id: string | null;
  node: string | null;
  start_step: number;
  end_step: number;
}

export interface Violation {
  code: ViolationCode;
  assignment_order: number | null;
  resource_id: string | null;
  road_id: string | null;
  detail: string;
}

export interface Metrics {
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
}

export interface TargetCheck {
  agent_id: AgentId;
  metric: string;
  value: number | null;
  meets_aspiration: boolean;
  meets_floor: boolean;
}

export interface Scenario {
  schema_version: SchemaVersion;
  scenario_id: string;
  title: string;
  horizon: number;
  step_minutes: number;
  grid: [number, number];
  nodes: Record<string, string>;
  roads: Road[];
  zones: Zone[];
  shelters: Shelter[];
  cells: Cell[];
  resources: Resource[];
  wind: Wind;
  fire_params: Record<string, number>;
  evidence: Evidence[];
  events: ScheduledEvent[];
  targets: Record<AgentId, Target[]>;
  label: "Synthetic simulation";
}

export interface WorldState {
  schema_version: SchemaVersion;
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
  metrics_so_far: Metrics;
  paused: boolean;
}

export interface Observation {
  schema_version: SchemaVersion;
  agent_id: AgentId;
  run_id: string;
  dp_id: string;
  state_version: number;
  step: number;
  round: number;
  world: Record<string, unknown>;
  held_evidence: Evidence[];
  public_events: ScheduledEvent[];
  targets: Record<AgentId, Target[]>;
  locked_assignments: Assignment[];
}

export interface Objection {
  kind: "infeasible" | "target_unmet" | "evidence_conflict" | "risk";
  metric: string | null;
  evaluation_id: string | null;
  proposed_amendment: string | null;
}

export interface TargetRevision {
  by: "EVAC" | "FIRE" | "LOG" | "human";
  metric: string;
  old_aspiration: number;
  new_aspiration: number;
  reason: string;
  dp_id: string;
}

export interface TurnMessage {
  message_type: MessageType;
  recipients: AgentId[];
  plan: AssignmentDraft[] | null;
  parent_plan_id: string | null;
  target_plan_id: string | null;
  target_plan_hash: string | null;
  objection: Objection | null;
  evidence_ids: string[];
  caused_by: string[];
  requested_evidence_id: string | null;
  requested_topic: string | null;
  shared_evidence_ids: string[];
  reason: string | null;
  blocking: string[];
  rationale: string;
}

export interface AgentTurn {
  messages: TurnMessage[];
  target_revision: TargetRevision | null;
}

export interface AgentMessage {
  message_type: MessageType;
  recipients: AgentId[];
  plan: AssignmentDraft[] | null;
  parent_plan_id: string | null;
  target_plan_id: string | null;
  target_plan_hash: string | null;
  objection: Objection | null;
  evidence_ids: string[];
  caused_by: string[];
  requested_evidence_id: string | null;
  requested_topic: string | null;
  shared_evidence_ids: string[];
  reason: string | null;
  blocking: string[];
  rationale: string;
  schema_version: SchemaVersion;
  message_id: string;
  sender: AgentId;
  run_id: string;
  scenario_id: string;
  dp_id: string;
  state_version: number;
  round: number;
  ts: string;
  step: number;
  proposal_id: string | null;
  plan_hash: string | null;
  status: "delivered" | "dropped";
  drop_reason: string | null;
}

export interface Plan {
  schema_version: SchemaVersion;
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
}

export interface Evaluation {
  schema_version: SchemaVersion;
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
}

export interface Acceptance {
  agent_id: AgentId;
  plan_hash: string;
  dp_id: string;
  state_version: number;
  via: "ACCEPT" | "PROPOSE" | "COUNTERPROPOSE";
  message_id: string;
  round: number;
  revoked: boolean;
}

export interface Commit {
  schema_version: SchemaVersion;
  run_id: string;
  dp_id: string;
  plan_hash: string;
  plan_id: string;
  state_version_before: number;
  state_version_after: number;
  acceptances: Acceptance[];
  ordering_rule: "first_proposed_seq";
  authority: "unanimous" | "human_choice" | "auto_fallback";
  authoritative_evaluation_id: string;
  ts: string;
  step: number;
}

export interface EscalationPackage {
  schema_version: SchemaVersion;
  run_id: string;
  dp_id: string;
  state_version: number;
  trigger: "ROUNDS_EXHAUSTED" | "BUDGET_EXCEEDED" | "ALL_ESCALATED" | "AGENT_UNAVAILABLE";
  candidates: string[];
  candidate_checks: Record<string, TargetCheck[]>;
  unmet_targets: Record<AgentId, string[]>;
  open_objections: string[];
  blocking_constraints: string[];
  fallback_plan_hash: string;
}

export interface SimulationEvent {
  schema_version: SchemaVersion;
  run_id: string;
  step: number;
  state_version: number;
  kind: "event.applied" | "leg.started" | "leg.completed" | "people.sheltered" | "cell.ignited" | "cell.extinguished" | "road.opened" | "task.skipped_unsafe" | "invariant.failed";
  data: Record<string, unknown>;
}

export interface RunResult {
  run_id: string;
  preset: string;
  seed: number;
  method: Method;
  model: string | null;
  budget_calls: number | null;
  budget_tokens: number | null;
  metrics: Metrics;
  decision_points: number;
  commits: number;
  escalations: number;
  human_decisions: number;
  inappropriate_consensus: number;
  justified_escalations: number;
  adaptation_wall_ms: number[];
  model_calls: number;
  tokens_in: number | null;
  tokens_out: number | null;
  wall_ms_total: number;
  cost_usd_estimate: number | null;
  notes: string;
}

export interface ErrorObject {
  code: "STATE_VERSION_MISMATCH" | "RUN_MISMATCH" | "NOT_FOUND" | "INVALID_REQUEST" | "NEGOTIATION_IN_PROGRESS" | "NO_ACTIVE_ESCALATION" | "PLAN_INFEASIBLE" | "MODEL_UNAVAILABLE" | "REPLAY_READ_ONLY" | "BUDGET_EXCEEDED" | "INTERNAL" | "BENCHMARK_IN_PROGRESS";
  message: string;
  retryable: boolean;
  run_id: string | null;
  state_version: number | null;
  details: Record<string, unknown>;
}

export interface Snapshot {
  schema_version: SchemaVersion;
  run_id: string;
  mode: RunMode;
  last_seq: number;
  world: WorldState;
  evidence_holders: Record<string, AgentId[]>;
  dp_id: string | null;
  negotiation_status: "idle" | "running" | "committed" | "escalated" | "cancelled";
  committed_plan: Plan | null;
  escalation: EscalationPackage | null;
  label: "Synthetic simulation";
  targets: Record<AgentId, Target[]> | null;
}
