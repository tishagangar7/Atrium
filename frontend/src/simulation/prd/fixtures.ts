/**
 * Fixture playback for the viewer harness.
 *
 * This is NOT a simulator. `applyFrame` copies a hand-written patch onto a
 * world so the scene can be exercised without a backend; it computes no
 * ignition probability, no travel time and no metric. The authoritative rules
 * live in `backend/app/sim/**` (PRD sections 5.5 to 5.7) and are the only
 * legitimate source of world progression.
 *
 * Frames are CUMULATIVE: frame n's patch applies on top of every earlier
 * frame, so a patch only names what changed.
 */

import seriesJson from "../../../../scenarios/fixtures/normal-render-series.json";
import { resetWorld } from "./scenario";
import type { Cell, Resource, Road, Shelter, WorldState, Zone } from "./types";

type Patch = {
  wind?: Partial<WorldState["wind"]>;
  cells?: Record<string, Partial<Cell>>;
  roads?: Record<string, Partial<Road>>;
  resources?: Record<string, Partial<Resource>>;
  zones?: Record<string, Partial<Zone>>;
  shelters?: Record<string, Partial<Shelter>>;
};

export type RenderFrame = {
  step: number;
  state_version: number;
  paused: boolean;
  note: string;
  patch: Patch;
};

export type RenderSeries = {
  fixture_id: string;
  label: string;
  provenance: string;
  base: string;
  frames: RenderFrame[];
};

export const RENDER_SERIES = seriesJson as unknown as RenderSeries;

/** Deep-ish clone of a world, so a frame never mutates the caller's copy. */
function cloneWorld(world: WorldState): WorldState {
  return JSON.parse(JSON.stringify(world)) as WorldState;
}

function mergeInto<T extends object>(
  target: Record<string, T>,
  patch: Record<string, Partial<T>> | undefined,
  kind: string,
): void {
  if (!patch) return;
  for (const [id, fields] of Object.entries(patch)) {
    const current = target[id];
    if (!current) throw new Error(`fixture patches unknown ${kind} "${id}"`);
    Object.assign(current, fields);
  }
}

/** Apply one hand-written frame to a world copy. Fixture playback only. */
export function applyFrame(world: WorldState, frame: RenderFrame): WorldState {
  const next = cloneWorld(world);
  next.step = frame.step;
  next.state_version = frame.state_version;
  next.paused = frame.paused;

  if (frame.patch.wind) Object.assign(next.wind, frame.patch.wind);
  mergeInto(next.cells, frame.patch.cells, "cell");
  mergeInto(next.roads, frame.patch.roads, "road");
  mergeInto(next.resources, frame.patch.resources, "resource");
  mergeInto(next.zones, frame.patch.zones, "zone");
  mergeInto(next.shelters, frame.patch.shelters, "shelter");

  return next;
}

/**
 * Build every frame of the series, each one cumulative on the last. Index 0 is
 * the untouched step-0 reset world.
 */
export function buildSeriesWorlds(): WorldState[] {
  const out: WorldState[] = [];
  let world = resetWorld("normal", { seed: 1 });
  for (const frame of RENDER_SERIES.frames) {
    world = applyFrame(world, frame);
    out.push(world);
  }
  return out;
}
