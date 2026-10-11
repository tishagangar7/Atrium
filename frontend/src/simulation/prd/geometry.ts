/**
 * Pure layout maths for the incident scene: grid cells, node placement, road
 * curves, resource markers and the wind vector. No React, no DOM, no physics.
 *
 * Everything here is deterministic and depends only on its arguments, so the
 * projection can be asserted in tests without a browser.
 */

import type {
  Resource,
  Road,
  RoadStatus,
  SceneScenario,
  WindDir,
} from "./types";
import { parseCellId } from "./scenario";

export const CELL = 72;
export const MARGIN = 52;

export type Point = { x: number; y: number };

export function canvasSize(grid: [number, number]): {
  width: number;
  height: number;
} {
  return {
    width: grid[0] * CELL + MARGIN * 2,
    height: grid[1] * CELL + MARGIN * 2,
  };
}

/** Top-left corner and size of a grid cell's rectangle. */
export function cellRect(cellId: string): {
  x: number;
  y: number;
  size: number;
} {
  const { x, y } = parseCellId(cellId);
  return { x: MARGIN + x * CELL, y: MARGIN + y * CELL, size: CELL };
}

export function cellCenter(cellId: string): Point {
  const { x, y } = parseCellId(cellId);
  return { x: MARGIN + (x + 0.5) * CELL, y: MARGIN + (y + 0.5) * CELL };
}

/** A node sits at the centre of its cell (PRD section 5.2 node table). */
export function nodePoint(scenario: SceneScenario, nodeId: string): Point {
  const cell = scenario.nodes[nodeId];
  if (!cell) throw new Error(`unknown node "${nodeId}"`);
  return cellCenter(cell);
}

/**
 * Several roads share a corridor on this map - R1 BASE-FORK lies on top of
 * R6 FORK-SE, for instance, because BASE sits between FORK and SE on row 2.
 * Every road therefore gets a deterministic perpendicular bow derived from its
 * position in the scenario's road order, so no two roads are drawn on the same
 * line and each has a free midpoint for its label.
 */
export function roadBow(scenario: SceneScenario, roadId: string): number {
  const index = scenario.roads.findIndex((r) => r.id === roadId);
  if (index < 0) throw new Error(`unknown road "${roadId}"`);
  const magnitude = 16 + (index % 3) * 9;
  return index % 2 === 0 ? magnitude : -magnitude;
}

function controlPoint(a: Point, b: Point, bow: number): Point {
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = Math.hypot(dx, dy) || 1;
  // Unit normal, rotated 90 degrees from the a-to-b direction.
  return {
    x: mid.x + (-dy / length) * bow * 2,
    y: mid.y + (dx / length) * bow * 2,
  };
}

/** SVG path for a road, as a quadratic curve with its deterministic bow. */
export function roadPath(scenario: SceneScenario, road: Road): string {
  const a = nodePoint(scenario, road.a);
  const b = nodePoint(scenario, road.b);
  const c = controlPoint(a, b, roadBow(scenario, road.id));
  return `M ${round(a.x)} ${round(a.y)} Q ${round(c.x)} ${round(c.y)} ${round(b.x)} ${round(b.y)}`;
}

/** Point at parameter t along a road's curve, t in [0, 1] from `a` to `b`. */
export function pointAlongRoad(
  scenario: SceneScenario,
  road: Road,
  t: number,
): Point {
  const a = nodePoint(scenario, road.a);
  const b = nodePoint(scenario, road.b);
  const c = controlPoint(a, b, roadBow(scenario, road.id));
  const u = clamp(t, 0, 1);
  const inv = 1 - u;
  return {
    x: inv * inv * a.x + 2 * inv * u * c.x + u * u * b.x,
    y: inv * inv * a.y + 2 * inv * u * c.y + u * u * b.y,
  };
}

/** Where a road's label sits: the midpoint of its curve. */
export function roadLabelPoint(scenario: SceneScenario, road: Road): Point {
  return pointAlongRoad(scenario, road, 0.5);
}

/**
 * A non-colour-only description of a road's status (AC-035, NFR-008). The
 * scene renders `dash` as the stroke pattern, `glyph` next to the road label
 * and `text` in the tooltip and legend, so status never depends on hue.
 */
export type RoadStatusCue = {
  status: RoadStatus;
  dash: string | null;
  glyph: string;
  text: string;
};

export function roadStatusCue(status: RoadStatus): RoadStatusCue {
  switch (status) {
    case "OPEN":
      return { status, dash: null, glyph: "", text: "Open" };
    case "CLOSED_CLEARABLE":
      return {
        status,
        dash: "10 7",
        glyph: "△",
        text: "Closed, a crew can clear it",
      };
    case "CLOSED_HARD":
      return {
        status,
        dash: "2 8",
        glyph: "✕",
        text: "Closed, not clearable",
      };
  }
}

/**
 * Marker position for one resource.
 *
 * At a node, resources sharing that node are fanned deterministically by their
 * index among that node's occupants so markers never overlap. On an edge, the
 * marker is interpolated along the road curve by travel progress.
 *
 * `edge_to` names the node being driven toward. The PRD section 7.2 `Resource`
 * carries `edge` and `edge_steps_left` but no direction, so without `edge_to`
 * the scene can only assume travel from `road.a` toward `road.b`. Adding a
 * direction field is an open ask on WS-C (see the branch handoff).
 */
export function resourcePoint(
  scenario: SceneScenario,
  resource: Resource,
  roads: Record<string, Road>,
  fanIndex: number,
  fanCount: number,
): Point {
  if (resource.edge) {
    const road = roads[resource.edge];
    if (!road) throw new Error(`resource on unknown road "${resource.edge}"`);
    const total = Math.max(1, road.travel_steps);
    const remaining = clamp(resource.edge_steps_left, 0, total);
    const progress = (total - remaining) / total;
    const forward = resource.edge_to ? resource.edge_to === road.b : true;
    return pointAlongRoad(scenario, road, forward ? progress : 1 - progress);
  }

  if (!resource.node) throw new Error(`resource "${resource.id}" has no place`);
  const base = nodePoint(scenario, resource.node);
  return fanPoint(base, fanIndex, fanCount);
}

/**
 * Lay `count` markers out in a centred row below a node.
 *
 * Below, because a node's name is drawn above it; in a row rather than on an
 * arc because four resources start at BASE (B1, B2, V1, C3) and an arc puts
 * the middle two back on top of the node glyph.
 */
export const FAN_SPACING = 25;
export const FAN_DROP = 32;

export function fanPoint(base: Point, index: number, count: number): Point {
  const offset = (index - (count - 1) / 2) * FAN_SPACING;
  return { x: base.x + offset, y: base.y + FAN_DROP };
}

/** Group resources by the node they stand at, for deterministic fanning. */
export function fanGroups(
  resources: Resource[],
): Map<string, { index: number; count: number }> {
  const byNode = new Map<string, string[]>();
  for (const resource of resources) {
    if (resource.edge || !resource.node) continue;
    const list = byNode.get(resource.node) ?? [];
    list.push(resource.id);
    byNode.set(resource.node, list);
  }
  const out = new Map<string, { index: number; count: number }>();
  for (const ids of byNode.values()) {
    const ordered = [...ids].sort();
    ordered.forEach((id, index) => {
      out.set(id, { index, count: ordered.length });
    });
  }
  return out;
}

/**
 * Unit vector the wind blows TOWARD. PRD section 5.2 defines direction as the
 * heading the wind blows toward, not where it comes from; screen y grows
 * downward, so north is negative y.
 */
export function windVector(direction: WindDir): Point {
  const table: Record<WindDir, Point> = {
    N: { x: 0, y: -1 },
    NE: { x: Math.SQRT1_2, y: -Math.SQRT1_2 },
    E: { x: 1, y: 0 },
    SE: { x: Math.SQRT1_2, y: Math.SQRT1_2 },
    S: { x: 0, y: 1 },
    SW: { x: -Math.SQRT1_2, y: Math.SQRT1_2 },
    W: { x: -1, y: 0 },
    NW: { x: -Math.SQRT1_2, y: -Math.SQRT1_2 },
  };
  return table[direction];
}

export const WIND_DIRECTIONS: readonly WindDir[] = [
  "N",
  "NE",
  "E",
  "SE",
  "S",
  "SW",
  "W",
  "NW",
] as const;

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
