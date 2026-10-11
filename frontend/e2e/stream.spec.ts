import { expect, test } from "@playwright/test";
import { readEvent, reduceEnvelope, type StreamCursor } from "../src/stream";
import type { StreamEvent } from "../src/components/shell-data";

const cursor: StreamCursor = { runId: "run-a", lastSeq: 5, benchmarkSeq: {} };
const envelope: StreamEvent = {
  run_id: "run-a",
  dp_id: null,
  trace_id: "run-a/dp-1/1/EVAC",
  seq: 6,
  step: 0,
  state_version: 0,
  mode: "live",
  type: "message.delivered",
  data: {},
};

test("PRD §8.4: old and duplicate sequences never apply", () => {
  expect(reduceEnvelope(cursor, { ...envelope, seq: 4 }).apply).toBe(false);
  expect(reduceEnvelope(cursor, { ...envelope, seq: 5 }).apply).toBe(false);
  const accepted = reduceEnvelope(cursor, envelope);
  expect(accepted.apply).toBe(true);
  expect(reduceEnvelope(accepted.cursor, envelope).apply).toBe(false);
  expect(cursor.lastSeq).toBe(5);
});

test("PRD §8.4: another run cannot advance the incident cursor", () => {
  const result = reduceEnvelope(cursor, {
    ...envelope,
    run_id: "run-b",
    seq: 100,
  });
  expect(result.apply).toBe(false);
  expect(result.cursor).toBe(cursor);
});

test("PRD §8.4: benchmarks use their own run cursors", () => {
  const benchmark = {
    ...envelope,
    type: "benchmark.progress",
    run_id: "bench-1",
    seq: 100,
  };
  const result = reduceEnvelope(cursor, benchmark);
  expect(result.apply).toBe(true);
  expect(result.cursor.lastSeq).toBe(5);
  expect(reduceEnvelope(result.cursor, benchmark).apply).toBe(false);
  expect(reduceEnvelope(result.cursor, envelope).apply).toBe(true);
});

test("PRD §8.4: snapshot.required with no active run requests resync", () => {
  const signal = readEvent(
    JSON.stringify({
      ...envelope,
      run_id: null,
      seq: 0,
      type: "snapshot.required",
      data: { active_run_id: null },
    }),
  );
  expect(reduceEnvelope(cursor, signal)).toEqual({
    cursor,
    apply: false,
    resync: true,
  });
});

test("AC-029: malformed stream data is rejected before reduction", () => {
  expect(() => readEvent("{bad")).toThrow();
  expect(() => readEvent(JSON.stringify({ ...envelope, seq: "6" }))).toThrow();
  expect(() =>
    readEvent(JSON.stringify({ ...envelope, trace_id: null })),
  ).toThrow();
  expect(() =>
    readEvent(JSON.stringify({ ...envelope, run_id: null })),
  ).toThrow();
});
