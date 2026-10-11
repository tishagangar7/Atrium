/**
 * Isolated viewer harness for WS-A queue item A1: "start isolated viewer
 * harness", completion evidence "reset fixture renders locally"
 * (PRD section 12.3). It exists so the incident scene and its controls can be
 * built and reviewed before any backend exists (PRD section 12.2
 * "Independent start").
 *
 * It is a HARNESS, not the command centre. Rohaan's dashboard (WS-D) mounts
 * `IncidentViewer` and `EnvironmentalControls` directly and forwards commands
 * through WS-C's API; this page only proves they work and shows the command
 * envelope they emit.
 *
 * No metric is shown anywhere, because no simulator has run. The outcome panel
 * reads em dashes by design (AC-023).
 */

import { useMemo, useState } from "react";

import { EnvironmentalControls } from "./EnvironmentalControls";
import { IncidentViewer } from "./IncidentViewer";
import { RENDER_SERIES, buildSeriesWorlds } from "./fixtures";
import { PRESET_IDS, loadSceneScenario, resetWorld, type PresetId } from "./scenario";
import type { EnvironmentCommand, Plan } from "./types";
import "./incident.css";

/**
 * A hand-written plan used only to show the route overlay. Its hash is the
 * literal string below, not a SHA-256 digest, so it can never be mistaken for
 * a real canonical plan hash (PRD section 6.7).
 */
const FIXTURE_PLAN: Plan = {
  schema_version: "1",
  plan_id: "fixture:P1",
  plan_hash: "fixture-not-hashed",
  proposer: "LOG",
  parent_plan_id: null,
  run_id: "run-fixture-normal-s1",
  dp_id: "dp-fixture",
  state_version: 0,
  state: "PROPOSED",
  evidence_ids: [],
  evaluation_ids: [],
  tradeoffs: [],
  expected_shelter_use: {},
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
    {
      order: 1,
      locked: false,
      resource_id: "B1",
      task: "drive",
      origin: "VJ",
      destination: "SS",
      route_ids: ["R5"],
      start_step: 7,
      end_step: 10,
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
};

export function Harness() {
  const [preset, setPreset] = useState<PresetId>("normal");
  const [frameIndex, setFrameIndex] = useState(0);
  const [showRoute, setShowRoute] = useState(false);
  const [log, setLog] = useState<string[]>([]);

  const scene = useMemo(() => loadSceneScenario(preset), [preset]);
  const seriesWorlds = useMemo(() => buildSeriesWorlds(), []);

  // The hand-written series describes the `normal` preset only. Any other
  // preset shows its own step-0 reset world.
  const seriesActive = preset === "normal";
  const world = seriesActive
    ? seriesWorlds[frameIndex]
    : resetWorld(preset, { seed: 1 });
  const frame = seriesActive ? RENDER_SERIES.frames[frameIndex] : null;

  function record(command: EnvironmentCommand) {
    const line = `${new Date().toISOString().slice(11, 19)}  ${JSON.stringify(command)}`;
    setLog((previous) => [line, ...previous].slice(0, 8));
  }

  return (
    <main className="hz">
      <header className="hz-head">
        <div>
          <h1>RescueMesh incident scene harness</h1>
          <p className="hz-sub">
            WS-A queue item A1. Renders the PRD section 5.2 world from committed
            fixtures with no backend, no agents and no model calls.
          </p>
        </div>
        <a className="hz-link" href="?">
          Open the UCSC forest-edge model instead
        </a>
      </header>

      <div className="hz-banner" role="note">
        <strong>Fixture data.</strong> Every number on this page comes from
        <code> scenarios/</code>. The authoritative simulator
        (<code>backend/app/sim</code>) is not built yet, so the outcome panel is
        empty on purpose: nothing here is a forecast, a replay or a result.
      </div>

      <section className="hz-bar" aria-label="Harness controls">
        <label className="hz-field" htmlFor="hz-preset">
          <span>Preset</span>
          <select
            id="hz-preset"
            value={preset}
            onChange={(event) => {
              setPreset(event.target.value as PresetId);
              setFrameIndex(0);
            }}
          >
            {PRESET_IDS.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>

        <label className="hz-field hz-field-wide" htmlFor="hz-frame">
          <span>
            Fixture frame{" "}
            {seriesActive
              ? `${frameIndex + 1} of ${seriesWorlds.length}`
              : "(normal only)"}
          </span>
          <input
            id="hz-frame"
            type="range"
            min={0}
            max={seriesWorlds.length - 1}
            step={1}
            value={frameIndex}
            disabled={!seriesActive}
            onChange={(event) => setFrameIndex(Number(event.target.value))}
          />
        </label>

        <label className="hz-check">
          <input
            type="checkbox"
            checked={showRoute}
            onChange={(event) => setShowRoute(event.target.checked)}
          />
          <span>Show fixture plan route (R1, R3, R5)</span>
        </label>

        <p className="hz-events">
          {scene.events.length === 0
            ? "No scheduled events."
            : `Scheduled: ${scene.events
                .map((e) => `${e.target ?? e.kind} to ${e.value} at step ${e.step}`)
                .join("; ")}`}
        </p>
      </section>

      {frame && (
        <p className="hz-note" aria-live="polite">
          <strong>Frame note:</strong> {frame.note}
        </p>
      )}

      <div className="hz-body">
        <IncidentViewer
          snapshot={world}
          scenario={scene}
          selectedPlan={showRoute ? FIXTURE_PLAN : null}
          evaluation={null}
          mode="fixture"
        />

        <aside className="hz-side">
          <EnvironmentalControls
            // A new state version voids in-flight work (PRD 5.8, FR-040), so
            // the pending selections reset with it rather than leaving a
            // stale choice sitting over a world that has already moved on.
            key={`${world.scenario_id}-${world.state_version}`}
            environment={world.wind}
            resources={world.resources}
            roads={world.roads}
            disabled={world.paused}
            onCommand={record}
          />

          <section className="hz-log" aria-label="Commands emitted">
            <h3>Commands emitted</h3>
            <p className="ec-note">
              In the real app WS-D forwards these to WS-C. Here they are only
              recorded, so the envelope can be reviewed.
            </p>
            {log.length === 0 ? (
              <p className="hz-empty">Nothing emitted yet.</p>
            ) : (
              <ol>
                {log.map((line, index) => (
                  <li key={`${line}-${index}`}>
                    <code>{line}</code>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <section className="hz-prov" aria-label="Fixture provenance">
            <h3>Provenance</h3>
            <p>{RENDER_SERIES.provenance}</p>
          </section>
        </aside>
      </div>
    </main>
  );
}
