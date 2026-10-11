export type Weather = {
  windSpeed: number;
  windToward: number;
  humidity: number;
  temperature: number;
  fuelMoisture: number;
};
export type FuelKind = "forest" | "grass" | "scrub" | "cleared";
export type Cell = {
  id: number;
  x: number;
  z: number;
  elevation: number;
  kind: FuelKind;
  fuel: number;
  initialFuel: number;
  moisture: number;
  intensity: number;
  burned: boolean;
  suppressed: boolean;
  heat: number;
};
export type Ember = {
  id: number;
  x: number;
  y: number;
  z: number;
  vx: number;
  vy: number;
  vz: number;
  age: number;
};
export type Metrics = {
  burning: number;
  affectedHa: number;
  consumedKg: number;
  heatMW: number;
  spotIgnitions: number;
  meanMoisture: number;
};
export type SimEvent = {
  seq: number;
  step: number;
  kind: string;
  text: string;
};
export type Snapshot = {
  schema_version: "1";
  model: "ucsc-visual-v1";
  run_id: string;
  seed: number;
  state_version: number;
  step: number;
  seconds: number;
  weather: Weather;
  cells: Cell[];
  embers: Ember[];
  metrics: Metrics;
  events: SimEvent[];
  roadClosed: boolean;
  completed: boolean;
};
export type Intervention =
  | { type: "weather"; weather: Weather }
  | { type: "ignite"; cell: number }
  | { type: "suppress"; cells: number[] }
  | { type: "closure"; closed: boolean };
export type WorkerCommand =
  | { type: "reset"; seed: number; weather: Weather }
  | { type: "play"; playing: boolean; speed: number }
  | { type: "step" }
  | { type: "intervene"; expectedVersion: number; intervention: Intervention }
  | {
      type: "evaluate";
      requestId: string;
      expectedVersion: number;
      intervention: Intervention;
      steps: number;
    };
export type WorkerReply =
  | { type: "snapshot"; snapshot: Snapshot; playing: boolean }
  | { type: "error"; message: string }
  | {
      type: "evaluation";
      requestId: string;
      state_version: number;
      metrics: Metrics;
    };
