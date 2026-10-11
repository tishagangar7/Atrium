import {
  record,
  readScreenState,
  type ScreenState,
  type StreamEvent,
} from "./components/shell-data";
import type { Snapshot } from "./types";
import { disruptionFlow, normalFlow, type BaseWorld } from "./fixtures/preview";
export interface SavedRun {
  runId: string;
  preset: string | null;
  createdTs: string | null;
}
export type InjectEvent =
  | "wind_shift_road_closure"
  | "wind_shift"
  | "road_closure"
  | "compound_failure";
export const API_BASE = (
  import.meta.env?.VITE_API_BASE ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");
export class ApiError extends Error {
  status: number;
  /** ErrorObject.code from the backend (PRD §7.8), e.g. STATE_VERSION_MISMATCH. */
  code: string | null;
  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.status = status;
    this.code = code;
  }
}
export const isStale = (error: unknown) =>
  error instanceof ApiError &&
  (error.code === "STATE_VERSION_MISMATCH" || error.code === "RUN_MISMATCH");
async function request(path: string, body?: unknown): Promise<unknown> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: { code?: string; message?: string };
    } | null;
    const code = body?.error?.code ?? null;
    throw new ApiError(
      response.status,
      response.status === 404
        ? "No active run was found."
        : (body?.error?.message ?? `Simulator request failed (${response.status}).`),
      code,
    );
  }
  return response.json();
}
export const api = {
  async health() {
    const data = record(await request("/health"));
    if (typeof data.ok !== "boolean")
      throw new Error("The simulator health response is not supported.");
    return {
      ok: data.ok,
      modelAvailable: data.model_available === true,
      testProvider:
        /test|fake/i.test(String(data.provider)) || data.mode === "test",
    };
  },
  async state(): Promise<Snapshot> {
    const value = await request("/state");
    readScreenState(value); // Validate the fields used by this D1 consumer.
    return value as Snapshot;
  },
  async reset(scenario: string, seed = 1): Promise<Snapshot> {
    const value = record(
      await request(`/scenarios/${encodeURIComponent(scenario)}/reset`, {
        seed,
        request_id: crypto.randomUUID(),
      }),
    );
    readScreenState(value.snapshot);
    return value.snapshot as Snapshot;
  },
  async step(state: ScreenState, steps = 1) {
    const value = record(
      await request("/simulation/step", {
        run_id: state.runId,
        expected_state_version: state.version,
        steps,
        request_id: crypto.randomUUID(),
      }),
    );
    if (!Number.isInteger(value.step) || !Number.isInteger(value.state_version))
      throw new Error("The step response is not supported.");
    return { step: value.step as number, version: value.state_version as number };
  },
  /** Saved runs to replay (PRD §8.2 GET /runs); replays of replays are left out. */
  async runs(): Promise<SavedRun[]> {
    const value = await request("/runs");
    if (!Array.isArray(value)) throw new Error("The runs list is not supported.");
    return value
      .map((item) => record(item))
      .filter((item) => typeof item.run_id === "string" && !String(item.run_id).startsWith("replay-of-"))
      .map((item) => ({
        runId: String(item.run_id),
        preset: typeof item.preset === "string" ? item.preset : null,
        createdTs: typeof item.created_ts === "string" ? item.created_ts : null,
      }))
      .sort((a, b) => (b.createdTs ?? "").localeCompare(a.createdTs ?? ""));
  },
  async replay(runId: string, speed: 1 | 2 | 4) {
    const value = record(
      await request(`/replay/${encodeURIComponent(runId)}`, { speed }),
    );
    return { runId: String(value.run_id) };
  },
  async negotiate(state: ScreenState) {
    const value = record(
      await request("/negotiate", {
        run_id: state.runId,
        expected_state_version: state.version,
        request_id: crypto.randomUUID(),
      }),
    );
    return { dpId: String(value.dp_id) };
  },
  cancel: (runId: string) =>
    request("/negotiate/cancel", { run_id: runId, reason: "cancelled by operator" }),
  /** `version` is the negotiation session's state_version (from stream envelopes), not /state's. */
  async inject(runId: string, version: number, event: InjectEvent) {
    const value = record(
      await request("/events/inject", {
        run_id: runId,
        expected_state_version: version,
        event,
        auto_negotiate: true,
        request_id: crypto.randomUUID(),
      }),
    );
    return { version: value.state_version as number };
  },
  /** The only human-decision path (FR-051): pick a feasible candidate or the fallback F0. */
  resolve: (
    runId: string,
    dpId: string,
    version: number,
    choice: "candidate" | "fallback",
    planHash?: string,
  ) =>
    request(`/escalations/${encodeURIComponent(dpId)}/resolve`, {
      run_id: runId,
      expected_state_version: version,
      choice,
      plan_hash: planHash ?? null,
      request_id: crypto.randomUUID(),
    }),
};
export const previewApi = {
  async reset(
    scenario: string,
    baseWorld?: BaseWorld,
  ): Promise<{ screen: ScreenState; events: StreamEvent[] }> {
    const runId = `ui-preview-${crypto.randomUUID()}`;
    const fixture = {
      schema_version: "1",
      label: "Synthetic simulation",
      source: "UI FIXTURE",
      scenario_id: scenario,
      run_id: runId,
      step: 0,
      state_version: 0,
    };
    const events =
      scenario === "normal"
        ? normalFlow(runId, scenario, baseWorld)
        : disruptionFlow(runId, scenario, baseWorld);
    return {
      screen: {
        runId,
        scenarioId: scenario,
        step: 0,
        version: 0,
        lastSeq: 0,
        mode: "preview",
        status: "idle",
        raw: fixture,
      },
      events,
    };
  },
};
