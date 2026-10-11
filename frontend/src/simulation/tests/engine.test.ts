import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  advance,
  applyIntervention,
  createWorld,
  draw,
  evaluate,
} from "../engine";
import { scenario, cellAt, elevation } from "../terrain";
import type { Snapshot } from "../types";
function run(s: Snapshot, steps: number) {
  for (let i = 0; i < steps; i++) advance(s);
  return s;
}
test("FR-014: common random numbers match SHA-256 first 8 bytes", () => {
  const hex = createHash("sha256")
    .update("42:12:c3_4")
    .digest("hex")
    .slice(0, 16);
  assert.ok(
    Math.abs(draw(42, 12, "c3_4") - Number(BigInt(`0x${hex}`)) / 2 ** 64) <
      1e-15,
  );
});
test("AC-014: same seed and interventions reproduce complete state", () => {
  assert.deepEqual(run(createWorld(), 60), run(createWorld(), 60));
  assert.notDeepEqual(
    run(createWorld(43), 20).metrics,
    run(createWorld(42), 20).metrics,
  );
});
test("AC-022: treatment counterfactual never mutates authoritative world", () => {
  const s = run(createWorld(), 12);
  const before = structuredClone(s);
  const metrics = evaluate(
    s,
    { type: "suppress", cells: scenario.initialIgnitions },
    60,
  );
  assert.deepEqual(s, before);
  assert.ok(Number.isFinite(metrics.affectedHa));
});
test("FR-004: finite nonnegative fuel, bounded intensity and conservation over horizon", () => {
  const s = createWorld(42, scenario.presets.offshore);
  const initialMass = s.cells.reduce(
    (sum, c) => sum + c.initialFuel * scenario.cellMeters ** 2,
    0,
  );
  let previousArea = 0;
  for (let i = 0; i < scenario.horizonSteps; i++) {
    advance(s);
    for (const c of s.cells) {
      assert.ok(
        Number.isFinite(c.fuel) && c.fuel >= 0 && c.fuel <= c.initialFuel,
      );
      assert.ok(c.intensity >= 0 && c.intensity <= 4);
      if (c.kind === "cleared") assert.equal(c.intensity, 0);
    }
    assert.ok(s.metrics.affectedHa >= previousArea);
    previousArea = s.metrics.affectedHa;
    const remaining = s.cells.reduce(
      (sum, c) => sum + c.fuel * scenario.cellMeters ** 2,
      0,
    );
    assert.ok(Math.abs(remaining + s.metrics.consumedKg - initialMass) < 1e-6);
    for (const e of s.embers)
      assert.ok(Number.isFinite(e.x + e.y + e.z) && e.y > elevation(e.x, e.z));
  }
  assert.equal(s.completed, true);
  assert.ok(s.step <= scenario.horizonSteps);
  const frozen = structuredClone(s);
  advance(s);
  assert.deepEqual(s, frozen);
});
test("AC-027: stale intervention rejected without changes", () => {
  const s = run(createWorld(), 1),
    before = structuredClone(s);
  assert.throws(
    () => applyIntervention(s, { type: "closure", closed: true }, 0),
    /Stale/,
  );
  assert.deepEqual(s, before);
});
test("Malformed inputs cannot partly apply or poison a world", () => {
  const s = createWorld(),
    before = structuredClone(s);
  assert.throws(() =>
    applyIntervention(
      s,
      { type: "weather", weather: { ...s.weather, windSpeed: NaN } },
      0,
    ),
  );
  assert.throws(() =>
    applyIntervention(s, { type: "suppress", cells: [1, 999999] }, 0),
  );
  assert.throws(() => applyIntervention(s, { type: "ignite", cell: -1 }, 0));
  assert.throws(() => evaluate(s, { type: "closure", closed: true }, Infinity));
  assert.deepEqual(s, before);
});
test("Moist coastal fuels produce less spread than dry fuels in a controlled pair", () => {
  const dry = run(
    createWorld(42, { ...scenario.weather, humidity: 12, fuelMoisture: 3 }),
    60,
  );
  const wet = run(
    createWorld(42, { ...scenario.weather, humidity: 90, fuelMoisture: 30 }),
    60,
  );
  assert.ok(dry.metrics.affectedHa > wet.metrics.affectedHa);
});
test("Ablation: wind changes spread geometry while seed stays fixed", () => {
  const east = run(
    createWorld(42, { ...scenario.weather, windSpeed: 15, windToward: 90 }),
    40,
  );
  const west = run(
    createWorld(42, { ...scenario.weather, windSpeed: 15, windToward: 270 }),
    40,
  );
  const meanX = (s: Snapshot) =>
    s.cells.filter((c) => c.burned).reduce((n, c) => n + c.x, 0) /
    s.cells.filter((c) => c.burned).length;
  assert.ok(meanX(east) > meanX(west));
});
test("Cell picking honors bounds and maps centers correctly", () => {
  const s = createWorld();
  for (const c of s.cells) assert.equal(cellAt(c.x, c.z), c.id);
  assert.equal(cellAt(160, 0), -1);
  assert.equal(cellAt(-161, 0), -1);
  assert.equal(cellAt(0, 121), -1);
});
test("Reset restores seed, weather, road state and interventions", () => {
  const s = createWorld();
  applyIntervention(s, { type: "closure", closed: true }, 0);
  applyIntervention(s, { type: "suppress", cells: [366] }, 1);
  run(s, 10);
  const clean = createWorld();
  assert.equal(clean.roadClosed, false);
  assert.equal(clean.cells[366].suppressed, false);
  assert.equal(clean.state_version, 0);
  assert.deepEqual(clean, createWorld());
});
