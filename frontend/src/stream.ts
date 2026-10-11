import { API_BASE } from "./api";
import { record, type StreamEvent } from "./components/shell-data";
export const eventTypes = [
  "run.reset",
  "state.snapshot",
  "state.step",
  "negotiation.started",
  "negotiation.round",
  "negotiation.cancelled",
  "agent.turn",
  "tool.called",
  "message.delivered",
  "message.dropped",
  "evidence.disclosed",
  "plan.proposed",
  "plan.state",
  "evaluation.created",
  "plan.committed",
  "escalation.opened",
  "human.decision",
  "event.applied",
  "error",
  "plan.bounced",
  "snapshot.required",
  "run.closed",
  "benchmark.progress",
  "benchmark.done",
];
export function readEvent(json: string): StreamEvent {
  const value = record(JSON.parse(json));
  if (
    !(
      typeof value.run_id === "string" ||
      (value.type === "snapshot.required" && value.run_id === null)
    ) ||
    typeof value.type !== "string" ||
    typeof value.trace_id !== "string" ||
    !Number.isInteger(value.seq) ||
    !Number.isInteger(value.step) ||
    !Number.isInteger(value.state_version) ||
    typeof value.mode !== "string" ||
    !(value.dp_id === null || typeof value.dp_id === "string") ||
    !("data" in value)
  ) {
    throw new Error("Malformed stream event");
  }
  return value as unknown as StreamEvent;
}
export interface StreamCursor {
  runId: string;
  lastSeq: number;
  benchmarkSeq: Record<string, number>;
}

// PRD §8.4: benchmark streams never advance the incident's cursor.
export function reduceEnvelope(cursor: StreamCursor, event: StreamEvent) {
  if (event.type === "snapshot.required")
    return { cursor, apply: false, resync: true };
  if (event.type.startsWith("benchmark.") && event.run_id) {
    if (event.seq <= (cursor.benchmarkSeq[event.run_id] ?? -1))
      return { cursor, apply: false, resync: false };
    return {
      cursor: {
        ...cursor,
        benchmarkSeq: { ...cursor.benchmarkSeq, [event.run_id]: event.seq },
      },
      apply: true,
      resync: false,
    };
  }
  if (event.run_id !== cursor.runId || event.seq <= cursor.lastSeq)
    return { cursor, apply: false, resync: false };
  return {
    cursor: { ...cursor, lastSeq: event.seq },
    apply: true,
    resync: false,
  };
}

export function subscribeToEvents(options: {
  runId: string;
  afterSeq: number;
  onEvent: (event: StreamEvent) => void;
  onConnection: (status: string) => void;
  onSnapshotRequired: () => void;
}) {
  const source = new EventSource(`${API_BASE}/events/stream`);
  let cursor: StreamCursor = {
    runId: options.runId,
    lastSeq: options.afterSeq,
    benchmarkSeq: {},
  };
  const receive = (message: MessageEvent<string>) => {
    // The PRD has an envelope named "error", but the browser also fires its own "error"
    // Event (no data) whenever the connection closes. Only server envelopes carry data.
    if (typeof message.data !== "string") return;
    try {
      const event = readEvent(message.data);
      const result = reduceEnvelope(cursor, event);
      if (result.resync) {
        source.close();
        options.onConnection("Refresh required");
        options.onSnapshotRequired();
        return;
      }
      if (!result.apply) return;
      cursor = result.cursor;
      options.onEvent(event);
    } catch {
      options.onConnection("Invalid event received");
    }
  };
  for (const type of eventTypes)
    source.addEventListener(type, receive as EventListener);
  // The backend closes the stream after each batch and the browser reconnects with
  // Last-Event-ID (§8.4). Only report trouble if a reconnect takes a while.
  let slow: number | undefined;
  source.onopen = () => {
    window.clearTimeout(slow);
    options.onConnection("Connected");
  };
  source.onerror = () => {
    window.clearTimeout(slow);
    slow = window.setTimeout(() => {
      if (source.readyState !== EventSource.OPEN)
        options.onConnection("Reconnecting…");
    }, 4000);
  };
  return () => {
    window.clearTimeout(slow);
    source.close();
  };
}
