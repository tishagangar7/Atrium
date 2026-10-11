import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  CELL,
  MARGIN,
  canvasSize,
  cellCenter,
  cellRect,
  fanGroups,
  fanPoint,
  nodePoint,
  pointAlongRoad,
  resourcePoint,
  roadLabelPoint,
  roadPath,
  roadStatusCue,
  windVector,
  WIND_DIRECTIONS,
} from "../prd/geometry";
import { loadSceneScenario, resetWorld } from "../prd/scenario";
import { RENDER_SERIES, applyFrame, buildSeriesWorlds } from "../prd/fixtures";
import { IncidentViewer, describeScene } from "../prd/IncidentViewer";
import { EnvironmentalControls } from "../prd/EnvironmentalControls";
import type { Evaluation } from "../prd/types";

const scene = loadSceneScenario("normal");

function markup(node: Parameters<typeof renderToStaticMarkup>[0]): string {
  return renderToStaticMarkup(node);
}

test("the projection is deterministic", () => {
  for (const road of scene.roads) {
    assert.equal(roadPath(scene, road), roadPath(scene, road), road.id);
  }
  for (const nodeId of Object.keys(scene.nodes)) {
    assert.deepEqual(nodePoint(scene, nodeId), nodePoint(scene, nodeId));
  }
});

test("every cell and node lands inside the canvas", () => {
  const size = canvasSize(scene.grid);
  const world = resetWorld("normal");
  for (const cell of Object.values(world.cells)) {
    const rect = cellRect(cell.id);
    assert.ok(rect.x >= MARGIN, `${cell.id} left edge`);
    assert.ok(rect.y >= MARGIN, `${cell.id} top edge`);
    assert.ok(rect.x + rect.size <= size.width - MARGIN, `${cell.id} right`);
    assert.ok(rect.y + rect.size <= size.height - MARGIN, `${cell.id} bottom`);
  }
  for (const nodeId of Object.keys(scene.nodes)) {
    const point = nodePoint(scene, nodeId);
    assert.ok(point.x > 0 && point.x < size.width, `${nodeId} x`);
    assert.ok(point.y > 0 && point.y < size.height, `${nodeId} y`);
  }
});

test("cell geometry follows the grid coordinates", () => {
  assert.deepEqual(cellRect("c0_0"), { x: MARGIN, y: MARGIN, size: CELL });
  assert.deepEqual(cellCenter("c0_0"), {
    x: MARGIN + CELL / 2,
    y: MARGIN + CELL / 2,
  });
  // x runs west to east, y runs north to south (PRD 5.2).
  assert.ok(cellRect("c9_0").x > cellRect("c0_0").x);
  assert.ok(cellRect("c0_5").y > cellRect("c0_0").y);
});

test("no two roads are drawn on the same line", () => {
  const paths = scene.roads.map((road) => roadPath(scene, road));
  assert.equal(
    new Set(paths).size,
    paths.length,
    "overlapping road paths would be unreadable",
  );
  // R1 BASE-FORK and R6 FORK-SE are collinear on row 2, so their label
  // anchors must still be clearly apart.
  const r1 = scene.roads.find((r) => r.id === "R1");
  const r6 = scene.roads.find((r) => r.id === "R6");
  assert.ok(r1 && r6);
  const a = roadLabelPoint(scene, r1);
  const b = roadLabelPoint(scene, r6);
  assert.ok(Math.hypot(a.x - b.x, a.y - b.y) > 20, "labels overlap");
});

test("a road curve starts at one end and finishes at the other", () => {
  for (const road of scene.roads) {
    const start = pointAlongRoad(scene, road, 0);
    const end = pointAlongRoad(scene, road, 1);
    assert.deepEqual(start, nodePoint(scene, road.a), `${road.id} start`);
    assert.deepEqual(end, nodePoint(scene, road.b), `${road.id} end`);
  }
});

test("AC-035: road status never depends on colour alone", () => {
  const open = roadStatusCue("OPEN");
  const clearable = roadStatusCue("CLOSED_CLEARABLE");
  const hard = roadStatusCue("CLOSED_HARD");

  // Each closed state carries a dash pattern, a glyph and words.
  for (const cue of [clearable, hard]) {
    assert.ok(cue.dash, `${cue.status} needs a stroke pattern`);
    assert.ok(cue.glyph.length > 0, `${cue.status} needs a glyph`);
    assert.ok(cue.text.length > 0, `${cue.status} needs text`);
  }
  // And the three states are mutually distinguishable without colour.
  assert.notEqual(clearable.dash, hard.dash);
  assert.notEqual(clearable.glyph, hard.glyph);
  assert.equal(open.dash, null);
  assert.equal(open.glyph, "");
  assert.equal(new Set([open.text, clearable.text, hard.text]).size, 3);
});

test("resources sharing a node are fanned apart", () => {
  const world = resetWorld("normal");
  const resources = Object.values(world.resources);
  const fans = fanGroups(resources);

  // B1, B2, V1 and C3 all start at BASE (PRD 5.3).
  const atBase = resources.filter((r) => r.node === "BASE").map((r) => r.id);
  assert.deepEqual(atBase.sort(), ["B1", "B2", "C3", "V1"]);

  const points = atBase.map((id) => {
    const fan = fans.get(id);
    assert.ok(fan, `${id} missing a fan slot`);
    return resourcePoint(
      scene,
      world.resources[id],
      world.roads,
      fan.index,
      fan.count,
    );
  });
  const keys = points.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`);
  assert.equal(new Set(keys).size, keys.length, "markers overlap at BASE");

  // Fanning is stable across calls.
  assert.deepEqual(
    fanPoint({ x: 0, y: 0 }, 1, 4),
    fanPoint({ x: 0, y: 0 }, 1, 4),
  );
});

test("a mid-edge resource is placed by its travel progress", () => {
  const world = resetWorld("normal");
  const road = world.roads.R1; // BASE to FORK, 3 travel steps

  const justLeft = {
    ...world.resources.B1,
    node: null,
    edge: "R1",
    edge_steps_left: 3,
    edge_to: "FORK",
  };
  const almostThere = { ...justLeft, edge_steps_left: 1 };

  const start = resourcePoint(scene, justLeft, world.roads, 0, 1);
  const near = resourcePoint(scene, almostThere, world.roads, 0, 1);
  assert.deepEqual(start, nodePoint(scene, road.a), "no progress yet");
  const distanceToFork = Math.hypot(
    near.x - nodePoint(scene, "FORK").x,
    near.y - nodePoint(scene, "FORK").y,
  );
  const startToFork = Math.hypot(
    start.x - nodePoint(scene, "FORK").x,
    start.y - nodePoint(scene, "FORK").y,
  );
  assert.ok(distanceToFork < startToFork, "should have moved toward FORK");
});

test("edge_to reverses the direction of travel", () => {
  const world = resetWorld("normal");
  const outbound = {
    ...world.resources.B1,
    node: null,
    edge: "R1",
    edge_steps_left: 1,
    edge_to: "FORK",
  };
  const inbound = { ...outbound, edge_to: "BASE" };
  const a = resourcePoint(scene, outbound, world.roads, 0, 1);
  const b = resourcePoint(scene, inbound, world.roads, 0, 1);
  assert.notDeepEqual(a, b, "direction must change the marker position");
});

test("PRD 5.2: the wind vector points where the wind blows toward", () => {
  // Screen y grows downward, so north is negative y.
  assert.deepEqual(windVector("N"), { x: 0, y: -1 });
  assert.deepEqual(windVector("S"), { x: 0, y: 1 });
  assert.deepEqual(windVector("E"), { x: 1, y: 0 });
  assert.deepEqual(windVector("W"), { x: -1, y: 0 });
  for (const direction of WIND_DIRECTIONS) {
    const v = windVector(direction);
    assert.ok(
      Math.abs(Math.hypot(v.x, v.y) - 1) < 1e-9,
      `${direction} must be a unit vector`,
    );
  }
  assert.equal(WIND_DIRECTIONS.length, 8);
});

test("the scene renders the whole PRD map", () => {
  const world = resetWorld("normal");
  const html = markup(
    createElement(IncidentViewer, { snapshot: world, mode: "fixture" }),
  );

  for (const road of scene.roads) {
    assert.ok(html.includes(road.id), `${road.id} missing from the scene`);
  }
  for (const name of Object.values(scene.node_names)) {
    assert.ok(html.includes(name), `${name} missing from the scene`);
  }
  for (const id of Object.keys(world.resources)) {
    assert.ok(html.includes(id), `${id} missing from the scene`);
  }
  assert.ok(html.includes("Synthetic simulation"), "synthetic label missing");
});

test("the mode badge states the provenance", () => {
  const world = resetWorld("normal");
  const cases = [
    ["fixture", "FIXTURE"],
    ["replay", "REPLAY"],
    ["live", "LIVE"],
  ] as const;
  for (const [mode, label] of cases) {
    const html = markup(
      createElement(IncidentViewer, { snapshot: world, mode }),
    );
    assert.ok(html.includes(label), `${mode} badge missing`);
  }
});

test("AC-023: with no evaluation the scene shows no outcome number", () => {
  const world = resetWorld("normal");
  const html = markup(
    createElement(IncidentViewer, {
      snapshot: world,
      mode: "fixture",
      evaluation: null,
    }),
  );
  assert.ok(html.includes("No evaluation attached"), "missing disclosure");
  assert.ok(html.includes("—"), "metrics should read as em dashes");
  // The metric block must not invent a zero.
  const block = html.slice(html.indexOf("Outcome numbers"));
  assert.ok(!/<dd[^>]*>0<\/dd>/.test(block), "a zero was invented");
});

test("AC-023: an attached evaluation is the source of every number", () => {
  const world = resetWorld("normal");
  const evaluation: Evaluation = {
    schema_version: "1",
    evaluation_id: "ev-testfixture01-authoritative-v0",
    plan_hash: "testfixture01",
    basis: "authoritative",
    kind: "forecast",
    run_id: world.run_id,
    state_version: 0,
    from_step: 0,
    horizon: 60,
    seed: 1,
    valid: true,
    violations: [],
    metrics: {
      civilian_exposure: 417,
      assisted_completion: 0.82,
      assisted_sheltered: 90,
      assisted_demand: 110,
      evacuation_completion_step: null,
      fire_extent: 19,
      burning_cell_steps: 52,
      crew_risk_steps: 2,
      logistics_risk: 1,
      invalid_attempted: 0,
      invalid_executed: 0,
    },
    target_checks: [],
    leg_timing: [],
    trace_ref: null,
    sim_ms: 3,
  };

  const html = markup(
    createElement(IncidentViewer, {
      snapshot: world,
      mode: "live",
      evaluation,
    }),
  );
  assert.ok(html.includes("417"), "civilian exposure missing");
  assert.ok(html.includes("82%"), "assisted completion missing");
  assert.ok(html.includes("19"), "fire extent missing");
  assert.ok(html.includes("Predicted (simulator)"), "basis label missing");
  assert.ok(html.includes(evaluation.evaluation_id), "evaluation id missing");
  assert.ok(!html.includes("No evaluation attached"));
});

test("a selected plan highlights only the roads it drives", () => {
  const world = resetWorld("normal");
  const base = markup(
    createElement(IncidentViewer, { snapshot: world, mode: "fixture" }),
  );
  const withPlan = markup(
    createElement(IncidentViewer, {
      snapshot: world,
      mode: "fixture",
      selectedPlan: {
        schema_version: "1",
        plan_id: "t:P1",
        plan_hash: "t",
        proposer: "LOG",
        parent_plan_id: null,
        run_id: world.run_id,
        dp_id: "dp-1",
        state_version: 0,
        state: "PROPOSED",
        assignments: [
          {
            order: 0,
            locked: false,
            resource_id: "B1",
            task: "drive",
            origin: "BASE",
            destination: "VJ",
            route_ids: ["R1", "R3"],
            start_step: 0,
            end_step: 5,
            wait_steps: 0,
            people_count: null,
            zone_id: null,
            shelter_id: null,
            crew_id: null,
            target_cells: [],
            edge_id: null,
            duration_steps: null,
          },
        ],
        evidence_ids: [],
        evaluation_ids: [],
        tradeoffs: [],
        expected_shelter_use: {},
      },
    }),
  );
  const count = (html: string) => html.split("iv-road-route").length - 1;
  assert.equal(count(base), 0, "no plan means no overlay");
  assert.equal(count(withPlan), 2, "one overlay per routed road");
});

test("the SVG has a text alternative describing the state", () => {
  const world = resetWorld("normal");
  const text = describeScene(world, scene);
  assert.ok(text.includes("Step 0 of 60"));
  assert.ok(text.includes("blowing toward E"));
  for (const id of ["c0_2", "c0_3", "c1_3"]) {
    assert.ok(text.includes(id), `${id} missing from the description`);
  }
  assert.ok(text.includes("R2"), "the closed road must be described");
  assert.ok(text.includes("a crew can clear it"));
});

test("the controls go inert when the world is paused", () => {
  const world = resetWorld("normal");
  const disabled = markup(
    createElement(EnvironmentalControls, {
      environment: world.wind,
      resources: world.resources,
      roads: world.roads,
      disabled: true,
      onCommand: () => {},
    }),
  );
  const enabled = markup(
    createElement(EnvironmentalControls, {
      environment: world.wind,
      resources: world.resources,
      roads: world.roads,
      disabled: false,
      onCommand: () => {},
    }),
  );
  assert.ok(disabled.includes("disabled"), "fieldsets should be disabled");
  assert.ok(disabled.includes("Paused for negotiation"));
  assert.ok(!enabled.includes("Paused for negotiation"));
});

test("PRD 12.3: wind control offers eight headings plus an explicit calm", () => {
  const world = resetWorld("normal");
  const html = markup(
    createElement(EnvironmentalControls, {
      environment: world.wind,
      resources: world.resources,
      roads: world.roads,
      disabled: false,
      onCommand: () => {},
    }),
  );
  assert.ok(html.includes("Calm (no wind)"), "calm option missing");
  assert.ok(
    html.includes("Blowing toward"),
    "wind must be labelled by heading",
  );
  for (const direction of WIND_DIRECTIONS) {
    assert.ok(
      html.includes(`value="${direction}"`),
      `${direction} option missing`,
    );
  }
});

test("invariant 7: no control waives a hard constraint", () => {
  const world = resetWorld("normal");
  const html = markup(
    createElement(EnvironmentalControls, {
      environment: world.wind,
      resources: world.resources,
      roads: world.roads,
      disabled: false,
      onCommand: () => {},
    }),
  );
  // There is no option that simply opens a road, adds a resource, enlarges a
  // shelter or grants fuel.
  assert.ok(!html.includes('value="OPEN"'), "no reopen-by-fiat option");
  assert.ok(!/add[ _-]?resource/i.test(html));
  assert.ok(!/capacity/i.test(html));
  assert.ok(!/grant fuel/i.test(html));
});

test("the fixture series is labelled hand-authored, not simulator output", () => {
  assert.match(RENDER_SERIES.provenance, /HAND-AUTHORED/);
  assert.match(RENDER_SERIES.provenance, /NO SIMULATOR PRODUCED THESE NUMBERS/);
  assert.equal(RENDER_SERIES.label, "Synthetic simulation");
});

test("the fixture series builds cumulatively and stays consistent", () => {
  const worlds = buildSeriesWorlds();
  assert.equal(worlds.length, RENDER_SERIES.frames.length);
  assert.equal(worlds.length, 6);

  for (let i = 0; i < worlds.length; i += 1) {
    const world = worlds[i];
    const frame = RENDER_SERIES.frames[i];
    assert.equal(world.step, frame.step, `frame ${i} step`);
    assert.equal(
      world.state_version,
      frame.state_version,
      `frame ${i} version`,
    );
    assert.equal(world.paused, frame.paused, `frame ${i} paused`);
    assert.equal(Object.keys(world.cells).length, 60, `frame ${i} cell count`);
    // Steps and versions only ever move forward.
    if (i > 0) {
      assert.ok(world.step > worlds[i - 1].step, `frame ${i} step advances`);
      assert.ok(
        world.state_version >= worlds[i - 1].state_version,
        `frame ${i} version never goes back`,
      );
    }
    // No frame fabricates a metric.
    assert.equal(world.metrics_so_far, null, `frame ${i} metrics`);
  }

  // The hand-written story: R2 gets cleared, then R3 is lost and B2 fails.
  const cleared = worlds[3];
  assert.equal(cleared.roads.R2.status_override, "OPEN");
  const disrupted = worlds[4];
  assert.equal(disrupted.wind.direction, "SE");
  assert.equal(disrupted.wind.speed, 3);
  assert.equal(disrupted.roads.R3.status_override, "CLOSED_HARD");
  assert.equal(disrupted.resources.B2.available, false);
  // A crew carried to the Pass leaves its engine behind (PRD 5.3).
  const revised = worlds[5];
  assert.equal(revised.resources.C1.node, "PASS");
  assert.equal(revised.resources.C1.engine_node, "PR");
});

test("AC-022 in spirit: applying a frame never mutates its input world", () => {
  const before = resetWorld("normal");
  const snapshot = JSON.stringify(before);
  const frame = RENDER_SERIES.frames[1];
  const after = applyFrame(before, frame);
  assert.equal(JSON.stringify(before), snapshot, "the input world was mutated");
  assert.notEqual(JSON.stringify(after), snapshot, "the frame did nothing");
});

test("a frame that names an unknown object is rejected, not ignored", () => {
  const world = resetWorld("normal");
  assert.throws(
    () =>
      applyFrame(world, {
        step: 1,
        state_version: 1,
        paused: false,
        note: "bad",
        patch: { cells: { c99_9: { intensity: 2 } } },
      }),
    /unknown cell/,
  );
  assert.throws(
    () =>
      applyFrame(world, {
        step: 1,
        state_version: 1,
        paused: false,
        note: "bad",
        patch: { roads: { R99: { clear_progress: 1 } } },
      }),
    /unknown road/,
  );
});

test("every fixture frame renders without throwing", () => {
  for (const world of buildSeriesWorlds()) {
    const html = markup(
      createElement(IncidentViewer, {
        snapshot: world,
        scenario: scene,
        mode: "fixture",
        evaluation: null,
      }),
    );
    assert.ok(html.includes("Synthetic simulation"));
    assert.ok(html.includes("FIXTURE"));
  }
});
