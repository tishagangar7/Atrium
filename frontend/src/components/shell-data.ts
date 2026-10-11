import type { IconName } from "./Icon";
import type { Snapshot, WorldState } from "../types";

// Display projections use WS-C's generated types without copying its world model.
export interface ScreenState {
  runId: string;
  scenarioId: string;
  step: WorldState["step"];
  version: WorldState["state_version"];
  lastSeq: Snapshot["last_seq"];
  mode: Snapshot["mode"] | "preview";
  status: Snapshot["negotiation_status"];
  raw: unknown;
}
export interface StreamEvent {
  schema_version?: string;
  run_id: string | null;
  dp_id: string | null;
  trace_id: string;
  seq: number;
  step: number;
  state_version: number;
  mode: string;
  type: string;
  data: unknown;
}
export const presets = [
  {
    id: "normal",
    name: "Normal response",
    description: "Coordinate the initial wildfire response.",
  },
  {
    id: "wind_shift",
    name: "Wind shift",
    description: "Revisit a response when the wind changes.",
  },
  {
    id: "road_closure",
    name: "Road closure",
    description: "Revisit routes when a road becomes unavailable.",
  },
  {
    id: "compound_failure",
    name: "Compound failure",
    description: "Explore conflicting priorities under pressure.",
  },
];
export const agents: {
  id: string;
  name: string;
  summary: string;
  objective: string;
  icon: IconName;
}[] = [
  {
    id: "evac",
    name: "Evacuation",
    summary: "People & safe passage",
    objective:
      "Prioritizes evacuating residents, including people who need assistance. Shares local evidence and evaluates plans from its own view.",
    icon: "people",
  },
  {
    id: "fire",
    name: "Fire Operations",
    summary: "Containment & crew safety",
    objective:
      "Prioritizes containing the wildfire with available crews. Evaluates how resource allocations affect fire operations.",
    icon: "fire",
  },
  {
    id: "log",
    name: "Logistics",
    summary: "Routes & shared resources",
    objective:
      "Coordinates feasible use of vehicles, roads and shelters. Discloses held evidence that can change what plans are possible.",
    icon: "truck",
  },
];
export function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Unexpected simulator response.");
  return value as Record<string, unknown>;
}
export function readScreenState(value: unknown): ScreenState {
  const snapshot = record(value);
  const world = record(snapshot.world);
  if (
    snapshot.schema_version !== "1" ||
    typeof snapshot.run_id !== "string" ||
    typeof world.scenario_id !== "string" ||
    !Number.isInteger(world.step) ||
    !Number.isInteger(world.state_version) ||
    !Number.isInteger(snapshot.last_seq) ||
    !["live", "replay"].includes(String(snapshot.mode)) ||
    typeof snapshot.negotiation_status !== "string"
  ) {
    throw new Error(
      "Unsupported snapshot. Shared contracts need to be connected.",
    );
  }
  return {
    runId: snapshot.run_id,
    scenarioId: world.scenario_id,
    step: world.step as number,
    version: world.state_version as number,
    lastSeq: snapshot.last_seq as number,
    mode: snapshot.mode as ScreenState["mode"],
    status: snapshot.negotiation_status as Snapshot["negotiation_status"],
    raw: value,
  };
}
