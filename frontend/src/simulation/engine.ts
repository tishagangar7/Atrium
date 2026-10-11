import { sha256 } from "@noble/hashes/sha2.js";
import { scenario, width, depth, elevation, fuelKind, cellAt } from "./terrain";
import type { Snapshot, Weather, Intervention, Metrics } from "./types";
const encoder = new TextEncoder();
const clamp = (n: number, min: number, max: number) =>
  Math.max(min, Math.min(max, n));
// PRD §5.5 common random numbers: first eight SHA-256 bytes / 2^64.
export function draw(seed: number, step: number, id: string) {
  const bytes = sha256(encoder.encode(`${seed}:${step}:${id}`));
  let n = 0;
  for (let i = 0; i < 8; i++) n = n * 256 + bytes[i];
  return Math.min(1 - Number.EPSILON, n / 2 ** 64);
}
export function validWeather(w: Weather) {
  return (
    !!w &&
    [
      ["windSpeed", 0, 25],
      ["windToward", 0, 360],
      ["humidity", 1, 100],
      ["temperature", 0, 50],
      ["fuelMoisture", 1, 40],
    ].every(
      ([key, low, high]) =>
        Number.isFinite(w[key as keyof Weather]) &&
        w[key as keyof Weather] >= Number(low) &&
        w[key as keyof Weather] <= Number(high),
    )
  );
}
export function measure(s: Snapshot): Metrics {
  const area = scenario.cellMeters ** 2;
  return {
    burning: s.cells.filter((c) => c.intensity > 0).length,
    affectedHa: (s.cells.filter((c) => c.burned).length * area) / 10000,
    consumedKg: s.cells.reduce(
      (a, c) => a + (c.initialFuel - c.fuel) * area,
      0,
    ),
    heatMW: s.cells.reduce((a, c) => a + c.heat, 0),
    spotIgnitions: s.metrics.spotIgnitions,
    meanMoisture:
      s.cells
        .filter((c) => c.initialFuel > 0)
        .reduce((a, c) => a + c.moisture, 0) /
      s.cells.filter((c) => c.initialFuel > 0).length,
  };
}
export function log(s: Snapshot, kind: string, text: string) {
  s.events.push({
    seq: (s.events.at(-1)?.seq ?? 0) + 1,
    step: s.step,
    kind,
    text,
  });
  s.events = s.events.slice(-80);
}
export function createWorld(
  seed = scenario.seed,
  weather: Weather = scenario.weather,
): Snapshot {
  if (
    !Number.isInteger(seed) ||
    seed < 0 ||
    seed > 999999 ||
    !validWeather(weather)
  )
    throw new Error("Invalid scenario parameters");
  const cells = Array.from(
    { length: scenario.columns * scenario.rows },
    (_, id) => {
      const x =
        ((id % scenario.columns) + 0.5) * scenario.cellMeters - width / 2;
      const z =
        (Math.floor(id / scenario.columns) + 0.5) * scenario.cellMeters -
        depth / 2;
      const kind = fuelKind(x, z);
      const fuel =
        kind === "cleared"
          ? 0
          : scenario.fuelLoads[kind] * (0.8 + 0.4 * draw(seed, 0, `fuel${id}`));
      const ignited = scenario.initialIgnitions.includes(id);
      return {
        id,
        x,
        z,
        elevation: elevation(x, z),
        kind,
        fuel,
        initialFuel: fuel,
        moisture: weather.fuelMoisture + (kind === "forest" ? 3 : 0),
        intensity: ignited ? 1 : 0,
        burned: ignited,
        suppressed: false,
        heat: 0,
      };
    },
  );
  const s: Snapshot = {
    schema_version: "1",
    model: "ucsc-visual-v1",
    run_id: `ucsc-s${seed}`,
    seed,
    state_version: 0,
    step: 0,
    seconds: 0,
    weather: { ...weather },
    cells,
    embers: [],
    metrics: {
      burning: 0,
      affectedHa: 0,
      consumedKg: 0,
      heatMW: 0,
      spotIgnitions: 0,
      meanMoisture: 0,
    },
    events: [],
    roadClosed: false,
    completed: false,
  };
  s.metrics = measure(s);
  log(s, "scenario", "Synthetic surface ignition at the redwood forest edge.");
  return s;
}
export function applyIntervention(
  s: Snapshot,
  action: Intervention,
  expectedVersion: number,
) {
  if (expectedVersion !== s.state_version)
    throw new Error(
      `Stale state v${expectedVersion}; current v${s.state_version}`,
    );
  if (
    !action ||
    !["weather", "ignite", "suppress", "closure"].includes(action.type)
  )
    throw new Error("Unknown intervention");
  if (action.type === "weather") {
    if (!validWeather(action.weather))
      throw new Error("Weather outside supported bounds");
    s.weather = { ...action.weather };
    // Moisture slider represents a measured fuel-moisture observation; humidity then drives relaxation.
    for (const c of s.cells)
      c.moisture = action.weather.fuelMoisture + (c.kind === "forest" ? 3 : 0);
    log(
      s,
      "weather",
      `Weather changed: ${s.weather.windSpeed} m/s toward ${s.weather.windToward}°, RH ${s.weather.humidity}%.`,
    );
  } else if (action.type === "ignite") {
    if (
      !Number.isInteger(action.cell) ||
      !s.cells[action.cell] ||
      s.cells[action.cell].fuel <= 0.02
    )
      throw new Error("Choose a cell with remaining vegetation");
    s.cells[action.cell].intensity = 1;
    s.cells[action.cell].burned = true;
    log(s, "ignition", `Operator ignition in cell ${action.cell}.`);
  } else if (action.type === "suppress") {
    if (
      !Array.isArray(action.cells) ||
      action.cells.length === 0 ||
      action.cells.length > 12 ||
      action.cells.some((id) => !Number.isInteger(id) || !s.cells[id])
    )
      throw new Error("Suppression requires 1–12 valid cell IDs");
    for (const id of action.cells) {
      s.cells[id].suppressed = true;
      s.cells[id].intensity *= 0.45;
    }
    log(
      s,
      "suppression",
      `Operator treatment on ${action.cells.length} cells; no agent dispatch implied.`,
    );
  } else {
    if (typeof action.closed !== "boolean")
      throw new Error("Closure must be boolean");
    s.roadClosed = action.closed;
    log(
      s,
      "closure",
      `Schematic access road ${action.closed ? "closed" : "reopened"} by operator.`,
    );
  }
  s.state_version++;
  s.metrics = measure(s);
}
export function advance(s: Snapshot) {
  if (s.completed) return s;
  const dt = scenario.stepSeconds;
  const { physics: p, columns, rows } = scenario;
  const angle = (s.weather.windToward * Math.PI) / 180;
  const wx = Math.sin(angle) * s.weather.windSpeed,
    wz = -Math.cos(angle) * s.weather.windSpeed;
  const before = s.cells.map((c) => c.intensity);
  const ignition: number[] = [];
  for (const c of s.cells) {
    const equilibrium =
      2 +
      s.weather.humidity * 0.22 +
      (c.kind === "forest" ? 3 : 0) -
      (s.weather.temperature - 20) * 0.08;
    c.moisture +=
      (clamp(equilibrium, 1, 40) - c.moisture) *
      (1 - Math.exp(-dt / p.moistureTimeSeconds));
    c.heat = 0;
    if (c.fuel <= 0.02) {
      c.intensity = 0;
      continue;
    }
    if (before[c.id] > 0) {
      c.intensity =
        clamp(before[c.id] + dt / 160, 0, 4) * (c.suppressed ? 0.9 : 1);
      const consumed = Math.min(
        c.fuel,
        p.burnRate * c.intensity * dt * (c.kind === "grass" ? 1.7 : 1),
      );
      c.fuel -= consumed;
      c.heat = (consumed * scenario.cellMeters ** 2 * p.fuelHeatMJkg) / dt;
      if (c.fuel <= 0.02 || c.intensity < 0.04) c.intensity = 0;
      if (
        s.embers.length < p.maxEmbers &&
        draw(s.seed, s.step, `ember${c.id}`) < 0.15 * c.intensity
      ) {
        s.embers.push({
          id: s.step * s.cells.length + c.id,
          x: c.x,
          z: c.z,
          y: c.elevation + 3,
          vx: wx * 0.3,
          vz: wz * 0.3,
          vy: 5 + draw(s.seed, s.step, `lift${c.id}`) * 4,
          age: 0,
        });
      }
      continue;
    }
    let pressure = 0;
    const col = c.id % columns,
      row = Math.floor(c.id / columns);
    for (let dz = -1; dz <= 1; dz++)
      for (let dx = -1; dx <= 1; dx++) {
        if (
          (!dx && !dz) ||
          col + dx < 0 ||
          col + dx >= columns ||
          row + dz < 0 ||
          row + dz >= rows
        )
          continue;
        const n = s.cells[(row + dz) * columns + col + dx];
        if (!before[n.id]) continue;
        const length = Math.hypot(dx, dz);
        const windAlignment = (-dx * wx - dz * wz) / length;
        const slope =
          (c.elevation - n.elevation) / (scenario.cellMeters * length);
        pressure +=
          (before[n.id] / length) *
          Math.exp(clamp(windAlignment * 0.13 + slope * 3, -2, 2));
      }
    const dryness = clamp((32 - c.moisture) / 25, 0.02, 1.3);
    const rate =
      p.ignitionCoefficient *
      pressure *
      dryness *
      Math.min(c.fuel, 1.5) *
      (c.suppressed ? 1 - p.suppressionFactor : 1);
    if (draw(s.seed, s.step, `c${col}_${row}`) < 1 - Math.exp(-rate * dt))
      ignition.push(c.id);
  }
  // Semi-implicit Euler, 0.1 s substeps. Lift decays, gravity acts continuously, wind drag advects.
  for (const e of s.embers) {
    for (let t = 0; t < dt && e.age < p.emberLifetime; t += 0.1) {
      e.vx += (wx - e.vx) * p.emberDrag * 0.1;
      e.vz += (wz - e.vz) * p.emberDrag * 0.1;
      e.vy +=
        (p.emberLift * Math.exp(-e.age / 6) - p.gravity - p.emberDrag * e.vy) *
        0.1;
      e.x += e.vx * 0.1;
      e.z += e.vz * 0.1;
      e.y += e.vy * 0.1;
      e.age += 0.1;
      if (e.y <= elevation(e.x, e.z)) {
        const id = cellAt(e.x, e.z),
          c = s.cells[id];
        if (
          c &&
          !c.intensity &&
          c.fuel > 0.02 &&
          draw(s.seed, s.step, `land${e.id}`) <
            clamp((28 - c.moisture) / 90, 0, 0.3) * (c.suppressed ? 0.1 : 1) &&
          !ignition.includes(id)
        ) {
          ignition.push(id);
          s.metrics.spotIgnitions++;
        }
        e.age = p.emberLifetime;
        break;
      }
    }
  }
  s.embers = s.embers.filter(
    (e) => e.age < p.emberLifetime && cellAt(e.x, e.z) >= 0,
  );
  for (const id of ignition) {
    s.cells[id].intensity = 1;
    s.cells[id].burned = true;
  }
  s.step++;
  s.seconds += dt;
  s.state_version++;
  s.metrics = measure(s);
  s.completed =
    s.step >= scenario.horizonSteps ||
    (s.metrics.burning === 0 && s.embers.length === 0);
  if (s.step % 12 === 0)
    log(
      s,
      "observation",
      `${s.metrics.burning} active cells · ${s.metrics.affectedHa.toFixed(2)} ha affected.`,
    );
  if (s.completed)
    log(
      s,
      "complete",
      s.step >= scenario.horizonSteps
        ? "120-minute simulation horizon reached."
        : "No active fire or airborne embers remain.",
    );
  return s;
}
export function evaluate(
  source: Snapshot,
  intervention: Intervention,
  steps: number,
) {
  if (!Number.isInteger(steps) || steps < 1 || steps > 120)
    throw new Error("Evaluation horizon must be 1–120 steps");
  const clone = structuredClone(source);
  applyIntervention(clone, intervention, clone.state_version);
  for (let i = 0; i < steps && !clone.completed; i++) advance(clone);
  return clone.metrics;
}
