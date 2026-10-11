import { test } from "node:test";
import assert from "node:assert/strict";
import {
  PRESET_IDS,
  assistedWaiting,
  cellIds,
  loadSceneScenario,
  resetWorld,
  resolveScenarioDocument,
  roadStatus,
  unassistedInZone,
} from "../prd/scenario";

test("PRD 5.2: the road table loads exactly as specified", () => {
  const scene = loadSceneScenario("normal");
  const byId = new Map(scene.roads.map((r) => [r.id, r]));

  const expected: [string, string, string, number, number, boolean][] = [
    ["R1", "BASE", "FORK", 3, 2, true],
    ["R2", "FORK", "PR", 3, 1, true],
    ["R3", "FORK", "VJ", 2, 2, true],
    ["R4", "VJ", "PR", 4, 1, true],
    ["R5", "VJ", "SS", 3, 2, true],
    ["R6", "FORK", "SE", 6, 2, true],
    ["R7", "VJ", "SE", 5, 1, true],
    ["R8", "PR", "PASS", 3, 1, false],
    ["R9", "PASS", "NC", 3, 1, false],
    ["R10", "NC", "FORK", 7, 1, true],
    ["R11", "BASE", "SS", 4, 2, true],
  ];

  assert.equal(scene.roads.length, expected.length);
  for (const [id, a, b, travel, capacity, engineOk] of expected) {
    const road = byId.get(id);
    assert.ok(road, `${id} missing`);
    assert.equal(road.a, a, `${id} end a`);
    assert.equal(road.b, b, `${id} end b`);
    assert.equal(road.travel_steps, travel, `${id} travel steps`);
    assert.equal(road.capacity, capacity, `${id} capacity`);
    assert.equal(road.engine_ok, engineOk, `${id} engine capability`);
  }
});

test("PRD 5.2: R2 starts closed but clearable; every other road is open", () => {
  const world = resetWorld("normal");
  assert.equal(roadStatus(world.roads.R2), "CLOSED_CLEARABLE");
  assert.equal(world.roads.R2.clear_progress, 0);
  for (const road of Object.values(world.roads)) {
    if (road.id === "R2") continue;
    assert.equal(roadStatus(road), "OPEN", `${road.id} should start open`);
  }
});

test("PRD 5.2: node cells match the map table", () => {
  const scene = loadSceneScenario("normal");
  assert.deepEqual(scene.nodes, {
    NC: "c3_0",
    PASS: "c2_1",
    PR: "c3_2",
    FORK: "c5_2",
    BASE: "c7_2",
    SE: "c9_2",
    VJ: "c5_4",
    SS: "c6_5",
  });
});

test("PRD 5.2: zone populations and assisted demand", () => {
  const world = resetWorld("normal");
  const totals: Record<string, [number, number]> = {
    NC: [40, 20],
    PR: [120, 30],
    VJ: [300, 60],
  };
  for (const [id, [people, assisted]] of Object.entries(totals)) {
    const zone = world.zones[id];
    assert.ok(zone, `${id} missing`);
    assert.equal(
      zone.unassisted_initial + zone.assisted_initial,
      people,
      `${id} total people`,
    );
    assert.equal(zone.assisted_initial, assisted, `${id} assisted`);
    // Nothing has happened yet, so the derived counters mirror the statics.
    assert.equal(assistedWaiting(zone), assisted);
    assert.equal(unassistedInZone(zone), people - assisted);
  }
  const demand = Object.values(world.zones).reduce(
    (sum, z) => sum + z.assisted_initial,
    0,
  );
  assert.equal(demand, 110, "total assisted demand");
});

test("PRD 5.2: shelter capacity and background occupancy", () => {
  const world = resetWorld("normal");
  assert.equal(world.shelters.SE.capacity, 150);
  assert.equal(world.shelters.SE.background, 40);
  assert.equal(world.shelters.SS.capacity, 350);
  assert.equal(world.shelters.SS.background, 320);
  for (const shelter of Object.values(world.shelters)) {
    assert.equal(shelter.arrivals, 0);
    assert.ok(
      shelter.background <= shelter.capacity,
      `${shelter.id} background within capacity`,
    );
  }
});

test("PRD 5.2: grid is 10 by 6 and every cell exists once", () => {
  const scene = loadSceneScenario("normal");
  assert.deepEqual(scene.grid, [10, 6]);
  const world = resetWorld("normal");
  const ids = cellIds(10, 6);
  assert.equal(ids.length, 60);
  assert.equal(Object.keys(world.cells).length, 60);
  assert.equal(new Set(ids).size, 60);
  for (const id of ids) assert.ok(world.cells[id], `${id} missing`);
});

test("PRD 5.2: initial fire cells and intensities", () => {
  const world = resetWorld("normal");
  const burning = Object.values(world.cells)
    .filter((c) => c.state === "BURNING")
    .map((c) => `${c.id}:${c.intensity}`)
    .sort();
  assert.deepEqual(burning, ["c0_2:2", "c0_3:2", "c1_3:1"]);
  for (const cell of Object.values(world.cells)) {
    if (cell.state === "BURNING") {
      assert.equal(cell.ignited_step, 0);
    } else {
      assert.equal(cell.state, "UNBURNED");
      assert.equal(cell.intensity, 0);
      assert.equal(cell.ignited_step, null);
    }
    assert.equal(cell.fuel_burned, 0);
  }
});

test("PRD 5.2: cell fuel defaults, cleared ground and ridge block", () => {
  const world = resetWorld("normal");
  // Cleared ground on the BASE, SE and SS node cells.
  for (const id of ["c7_2", "c9_2", "c6_5"]) {
    assert.equal(world.cells[id].fuel_initial, 0.2, `${id} cleared`);
  }
  // Heavy ridge fuel, the true value behind E-FIRE-01.
  for (const id of ["c1_1", "c2_1", "c1_2", "c2_2"]) {
    assert.equal(world.cells[id].fuel_initial, 0.9, `${id} ridge fuel`);
  }
  // Everything else takes the default.
  const special = new Set([
    "c7_2",
    "c9_2",
    "c6_5",
    "c1_1",
    "c2_1",
    "c1_2",
    "c2_2",
  ]);
  for (const cell of Object.values(world.cells)) {
    if (special.has(cell.id)) continue;
    assert.equal(cell.fuel_initial, 0.7, `${cell.id} default fuel`);
  }
});

test("PRD 5.2: only Ridge Pass carries the firebreak bonus", () => {
  const world = resetWorld("normal");
  const withBonus = Object.values(world.cells)
    .filter((c) => c.firebreak_bonus)
    .map((c) => c.id);
  assert.deepEqual(withBonus, ["c2_1"]);
});

test("PRD 5.3: resources, capacities and start nodes", () => {
  const world = resetWorld("normal");
  assert.deepEqual(Object.keys(world.resources).sort(), [
    "B1",
    "B2",
    "C1",
    "C2",
    "C3",
    "V1",
  ]);

  for (const id of ["B1", "B2"]) {
    const bus = world.resources[id];
    assert.equal(bus.type, "bus");
    assert.equal(bus.capacity, 30);
    assert.equal(bus.fuel_capacity, 40);
    assert.equal(bus.node, "BASE");
  }

  const v1 = world.resources.V1;
  assert.equal(v1.type, "transport");
  assert.equal(v1.capacity, 10);
  assert.equal(v1.fuel_capacity, 30);
  assert.equal(v1.node, "BASE");

  // Crews have no civilian capacity and no modelled fuel; each starts with
  // its own engine (PRD 5.3).
  for (const [id, node] of [
    ["C1", "FORK"],
    ["C2", "FORK"],
    ["C3", "BASE"],
  ] as const) {
    const crew = world.resources[id];
    assert.equal(crew.type, "crew");
    assert.equal(crew.capacity, 0);
    assert.equal(crew.fuel_capacity, null);
    assert.equal(crew.node, node);
    assert.equal(crew.engine_node, node);
  }

  for (const resource of Object.values(world.resources)) {
    assert.equal(resource.fuel_used, 0);
    assert.equal(resource.edge, null);
    assert.equal(resource.aboard_crew, null);
    assert.deepEqual(resource.aboard_people, {});
    assert.equal(resource.available, true);
    // Exactly one of node or edge, per the PRD 5.6 invariant.
    assert.ok(
      (resource.node === null) !== (resource.edge === null),
      `${resource.id} must be at a node or on an edge, not both`,
    );
  }
});

test("PRD 5.2: wind starts blowing toward E at speed 2", () => {
  const world = resetWorld("normal");
  assert.deepEqual(world.wind, { direction: "E", speed: 2 });
});

test("PRD 5.1: horizon is 60 steps of 2 simulated minutes", () => {
  const scene = loadSceneScenario("normal");
  assert.equal(scene.horizon, 60);
  assert.equal(scene.step_minutes, 2);
});

test("PRD 5.9: the evidence table matches, with holders and priors", () => {
  const doc = resolveScenarioDocument("normal");
  const evidence = doc.evidence as {
    evidence_id: string;
    holders: string[];
    field_path: string;
    true_value: unknown;
    prior_value: unknown;
    summary: string;
  }[];

  const expected: [string, string, string, unknown, unknown][] = [
    ["E-EVAC-01", "EVAC", "zones.PR.assisted_initial", 30, 12],
    ["E-EVAC-02", "EVAC", "zones.VJ.assisted_initial", 60, 30],
    ["E-EVAC-03", "EVAC", "zones.NC.assisted_initial", 20, 4],
    ["E-FIRE-01", "FIRE", "cells[c1_1,c2_1,c1_2,c2_2].fuel_initial", 0.9, 0.5],
    ["E-FIRE-02", "FIRE", "cells.c2_1.firebreak_bonus", true, false],
    ["E-LOG-01", "LOG", "roads.R2.initial_status", "CLOSED_CLEARABLE", "OPEN"],
    ["E-LOG-02", "LOG", "shelters.SS.background", 320, 290],
  ];

  assert.equal(evidence.length, expected.length);
  for (const [id, holder, path, trueValue, prior] of expected) {
    const item = evidence.find((e) => e.evidence_id === id);
    assert.ok(item, `${id} missing`);
    assert.deepEqual(item.holders, [holder], `${id} holder`);
    assert.equal(item.field_path, path, `${id} field path`);
    assert.deepEqual(item.true_value, trueValue, `${id} true value`);
    assert.deepEqual(item.prior_value, prior, `${id} prior`);
    assert.notDeepEqual(
      item.true_value,
      item.prior_value,
      `${id} must actually differ from its prior`,
    );
    assert.ok(item.summary.length <= 160, `${id} summary within 160 chars`);
  }
});

test("PRD 5.9: every evidence item names a static field, never a counter", () => {
  const doc = resolveScenarioDocument("normal");
  const evidence = doc.evidence as {
    evidence_id: string;
    field_path: string;
  }[];
  const counters = [
    "self_evacuated",
    "assisted_picked_up",
    "arrivals",
    "fuel_used",
    "fuel_burned",
    "intensity",
    "clear_progress",
    "status_override",
  ];
  for (const item of evidence) {
    for (const counter of counters) {
      assert.ok(
        !item.field_path.includes(counter),
        `${item.evidence_id} masks the dynamic counter ${counter}`,
      );
    }
  }
});

test("PRD 5.12: acceptance targets per agent", () => {
  const scene = loadSceneScenario("normal");
  assert.deepEqual(scene.targets.EVAC, [
    {
      metric: "assisted_completion",
      direction: "max",
      aspiration: 0.9,
      floor: 0.75,
      revisable_by_agent: true,
    },
    {
      metric: "civilian_exposure",
      direction: "min",
      aspiration: 600,
      floor: 1200,
      revisable_by_agent: true,
    },
  ]);
  assert.deepEqual(scene.targets.FIRE, [
    {
      metric: "fire_extent",
      direction: "min",
      aspiration: 22,
      floor: 30,
      revisable_by_agent: true,
    },
    {
      metric: "crew_risk_steps",
      direction: "min",
      aspiration: 0,
      floor: 4,
      revisable_by_agent: true,
    },
  ]);
  assert.deepEqual(scene.targets.LOG, [
    {
      metric: "logistics_risk",
      direction: "min",
      aspiration: 1,
      floor: 3,
      revisable_by_agent: true,
    },
  ]);
});

test("PRD 5.12: a floor is never stricter than its aspiration", () => {
  const scene = loadSceneScenario("normal");
  for (const [agent, targets] of Object.entries(scene.targets)) {
    for (const target of targets) {
      if (target.direction === "min") {
        assert.ok(
          target.floor >= target.aspiration,
          `${agent} ${target.metric}: floor must be no stricter than aspiration`,
        );
      } else {
        assert.ok(
          target.floor <= target.aspiration,
          `${agent} ${target.metric}: floor must be no stricter than aspiration`,
        );
      }
    }
  }
});

test("PRD 5.11: all four presets load and carry the right events", () => {
  assert.deepEqual(
    [...PRESET_IDS],
    ["normal", "wind_shift", "road_closure", "compound_failure"],
  );

  const normal = loadSceneScenario("normal");
  assert.equal(normal.events.length, 0, "normal has no scheduled events");

  const windShift = loadSceneScenario("wind_shift");
  assert.deepEqual(
    windShift.events.map((e) => [e.step, e.kind, e.target, e.value]),
    [
      [15, "wind_change", "direction", "SE"],
      [15, "wind_change", "speed", 3],
    ],
  );

  const roadClosure = loadSceneScenario("road_closure");
  assert.deepEqual(
    roadClosure.events.map((e) => [e.step, e.kind, e.target, e.value]),
    [[15, "road_status", "R3", "CLOSED_HARD"]],
  );

  const compound = loadSceneScenario("compound_failure");
  assert.deepEqual(
    compound.events.map((e) => [e.step, e.kind, e.target, e.value]),
    [
      [15, "wind_change", "direction", "SE"],
      [15, "wind_change", "speed", 3],
      [15, "road_status", "R3", "CLOSED_HARD"],
      [15, "road_status", "R5", "CLOSED_HARD"],
      [15, "resource_status", "B2", "OUT_OF_SERVICE"],
    ],
  );

  for (const preset of PRESET_IDS) {
    const scene = loadSceneScenario(preset);
    for (const event of scene.events) {
      assert.equal(event.step, 15, "benchmark events all fire at step 15");
      assert.equal(event.public, true);
    }
  }
});

test("PRD 5.11: disruption presets inherit the normal map unchanged", () => {
  const base = loadSceneScenario("normal");
  const presets = ["wind_shift", "road_closure", "compound_failure"] as const;
  for (const preset of presets) {
    const scene = loadSceneScenario(preset);
    assert.deepEqual(scene.roads, base.roads, `${preset} roads`);
    assert.deepEqual(scene.zones, base.zones, `${preset} zones`);
    assert.deepEqual(scene.shelters, base.shelters, `${preset} shelters`);
    assert.deepEqual(scene.nodes, base.nodes, `${preset} nodes`);
    assert.deepEqual(scene.targets, base.targets, `${preset} targets`);
    assert.equal(scene.horizon, base.horizon, `${preset} horizon`);
  }
});

test("PRD 5.11: an event never fires at or after the horizon", () => {
  for (const preset of PRESET_IDS) {
    const scene = loadSceneScenario(preset);
    for (const event of scene.events) {
      assert.ok(
        event.step < scene.horizon,
        `${preset} event ${event.event_id} must land inside the horizon`,
      );
    }
  }
});

test("AC-014: two resets of a preset are byte-identical", () => {
  for (const preset of PRESET_IDS) {
    const first = JSON.stringify(resetWorld(preset, { seed: 1 }));
    const second = JSON.stringify(resetWorld(preset, { seed: 1 }));
    assert.equal(first, second, `${preset} reset is not reproducible`);
  }
});

test("AC-014: the seed changes run_id and seed, not the initial world", () => {
  const a = resetWorld("normal", { seed: 1 });
  const b = resetWorld("normal", { seed: 2 });
  assert.notEqual(a.run_id, b.run_id);
  assert.notEqual(a.seed, b.seed);
  assert.deepEqual(
    { ...a, run_id: "", seed: 0 },
    { ...b, run_id: "", seed: 0 },
    "the seed must not change the initial world",
  );
});

test("AC-023: a reset carries no metrics, because nothing was evaluated", () => {
  for (const preset of PRESET_IDS) {
    const world = resetWorld(preset);
    assert.equal(world.metrics_so_far, null, `${preset} metrics_so_far`);
    assert.equal(world.committed_plan_hash, null, `${preset} committed hash`);
    assert.deepEqual(world.active_legs, [], `${preset} active legs`);
    assert.equal(world.step, 0, `${preset} step`);
    assert.equal(world.state_version, 0, `${preset} state version`);
    assert.equal(world.paused, true, `${preset} starts paused`);
  }
});

test("a mutation of one reset never leaks into the next", () => {
  const first = resetWorld("normal");
  first.cells.c0_0.intensity = 4;
  first.roads.R1.status_override = "CLOSED_HARD";
  first.zones.PR.assisted_picked_up = 30;
  const second = resetWorld("normal");
  assert.equal(second.cells.c0_0.intensity, 0);
  assert.equal(second.roads.R1.status_override, null);
  assert.equal(second.zones.PR.assisted_picked_up, 0);
});

test("the scenario is labelled synthetic in every preset", () => {
  for (const preset of PRESET_IDS) {
    assert.equal(loadSceneScenario(preset).label, "Synthetic simulation");
  }
});

test("roads reference real nodes and places reference real cells", () => {
  const scene = loadSceneScenario("normal");
  const world = resetWorld("normal");
  const nodeIds = new Set(Object.keys(scene.nodes));
  for (const road of scene.roads) {
    assert.ok(nodeIds.has(road.a), `${road.id} end a is a real node`);
    assert.ok(nodeIds.has(road.b), `${road.id} end b is a real node`);
    assert.notEqual(road.a, road.b, `${road.id} must not be a self loop`);
  }
  for (const zone of Object.values(world.zones)) {
    assert.ok(world.cells[zone.cell], `${zone.id} sits on a real cell`);
    assert.equal(scene.nodes[zone.id], zone.cell, `${zone.id} node agrees`);
  }
  for (const shelter of Object.values(world.shelters)) {
    assert.ok(world.cells[shelter.cell], `${shelter.id} sits on a real cell`);
    assert.equal(
      scene.nodes[shelter.id],
      shelter.cell,
      `${shelter.id} node agrees`,
    );
  }
  for (const resource of Object.values(world.resources)) {
    assert.ok(
      resource.node === null || nodeIds.has(resource.node),
      `${resource.id} starts at a real node`,
    );
  }
});

test("every node is reachable from BASE when all roads are open", () => {
  const scene = loadSceneScenario("normal");
  const neighbours = new Map<string, string[]>();
  for (const road of scene.roads) {
    neighbours.set(road.a, [...(neighbours.get(road.a) ?? []), road.b]);
    neighbours.set(road.b, [...(neighbours.get(road.b) ?? []), road.a]);
  }
  const seen = new Set<string>(["BASE"]);
  const queue = ["BASE"];
  while (queue.length > 0) {
    const current = queue.shift() as string;
    for (const next of neighbours.get(current) ?? []) {
      if (!seen.has(next)) {
        seen.add(next);
        queue.push(next);
      }
    }
  }
  assert.deepEqual(
    [...seen].sort(),
    Object.keys(scene.nodes).sort(),
    "the map must be connected when every road is open",
  );
});
