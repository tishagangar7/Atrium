/**
 * `EnvironmentalControls` - the second A-to-D interface frozen at G0
 * (PRD section 12.2:
 * `EnvironmentalControls({environment, resources, roads, disabled, onCommand})`).
 *
 * This surface NEVER mutates world state. It emits typed `EnvironmentCommand`
 * values through `onCommand`; WS-D forwards them to WS-C, which applies them to
 * the authoritative world under the run lock and republishes a snapshot
 * (PRD section 12.2 "Atomic execution", section 12.3 "interactive minimum").
 * Nothing here is a decorative control: each command has a backend effect.
 *
 * Scope per PRD section 12.3: wind direction and speed with an explicit calm
 * option, selected road closure, and resource failure. Humidity and
 * click-to-ignite need new simulator rules plus WS-C schema wiring and are
 * deliberately absent rather than shown as dead controls.
 *
 * Hard constraints are never waived from here (PRD invariant 7): there is no
 * control to open a `CLOSED_HARD` road by fiat, add a resource, raise a
 * shelter's capacity or grant fuel.
 */

import { useState } from "react";

import { WIND_DIRECTIONS, roadStatusCue } from "./geometry";
import { roadStatus } from "./scenario";
import type {
  EnvironmentCommand,
  Resource,
  Road,
  RoadStatus,
  Wind,
  WindDir,
} from "./types";

export type EnvironmentalControlsProps = {
  /** Current wind, as shown in the scene. */
  environment: Wind;
  resources: Record<string, Resource>;
  roads: Record<string, Road>;
  /** True while the world is paused for negotiation, or in replay. */
  disabled: boolean;
  onCommand: (command: EnvironmentCommand) => void;
};

/** Wind choices: the eight PRD headings plus an explicit calm. */
type WindChoice = WindDir | "CALM";

export function EnvironmentalControls({
  environment,
  resources,
  roads,
  disabled,
  onCommand,
}: EnvironmentalControlsProps) {
  const [direction, setDirection] = useState<WindChoice>(environment.direction);
  const [speed, setSpeed] = useState<number>(environment.speed);
  const [roadId, setRoadId] = useState<string>(firstKey(roads));
  const [roadTo, setRoadTo] = useState<RoadStatus>("CLOSED_HARD");
  const [resourceId, setResourceId] = useState<string>(firstKey(resources));

  const roadList = Object.values(roads).sort(byRoadId);
  const resourceList = Object.values(resources).sort((a, b) =>
    a.id.localeCompare(b.id),
  );
  const selectedResource = resources[resourceId];
  const calm = direction === "CALM";

  return (
    <section className="ec" aria-label="Environmental controls">
      <header className="ec-head">
        <h3>Conditions</h3>
        <p className="ec-note">
          {disabled
            ? "Paused for negotiation. Conditions change only between decision points."
            : "Each change is sent to the simulator and opens a new decision point."}
        </p>
      </header>

      <fieldset className="ec-group" disabled={disabled}>
        <legend>Wind</legend>

        <label className="ec-field" htmlFor="ec-wind-dir">
          <span>Blowing toward</span>
          <select
            id="ec-wind-dir"
            value={direction}
            onChange={(event) => setDirection(event.target.value as WindChoice)}
          >
            <option value="CALM">Calm (no wind)</option>
            {WIND_DIRECTIONS.map((dir) => (
              <option key={dir} value={dir}>
                {dir}
              </option>
            ))}
          </select>
        </label>

        <div className="ec-field" role="group" aria-labelledby="ec-speed-label">
          <span id="ec-speed-label">Speed</span>
          <div className="ec-radios">
            {[1, 2, 3].map((value) => (
              <label key={value} className="ec-radio">
                <input
                  type="radio"
                  name="ec-wind-speed"
                  value={value}
                  checked={!calm && speed === value}
                  disabled={calm}
                  onChange={() => setSpeed(value)}
                />
                <span>
                  {value} {SPEED_WORD[value]}
                </span>
              </label>
            ))}
          </div>
        </div>

        <p className="ec-current">
          Now: {environment.direction} at speed {environment.speed}
        </p>

        <button
          type="button"
          className="ec-apply"
          onClick={() =>
            onCommand({
              type: "set_wind",
              direction,
              speed: calm ? 0 : speed,
            })
          }
        >
          Apply wind
        </button>
      </fieldset>

      <fieldset className="ec-group" disabled={disabled}>
        <legend>Road status</legend>

        <label className="ec-field" htmlFor="ec-road">
          <span>Road</span>
          <select
            id="ec-road"
            value={roadId}
            onChange={(event) => setRoadId(event.target.value)}
          >
            {roadList.map((road) => (
              <option key={road.id} value={road.id}>
                {`${road.id} ${road.a}-${road.b} · ${roadStatusCue(roadStatus(road)).text}`}
              </option>
            ))}
          </select>
        </label>

        <label className="ec-field" htmlFor="ec-road-status">
          <span>Set to</span>
          <select
            id="ec-road-status"
            value={roadTo}
            onChange={(event) => setRoadTo(event.target.value as RoadStatus)}
          >
            <option value="CLOSED_HARD">Closed, not clearable</option>
            <option value="CLOSED_CLEARABLE">
              Closed, a crew can clear it
            </option>
          </select>
        </label>

        <p className="ec-note">
          Reopening a road is a crew&apos;s clear_road task, not an operator
          action.
        </p>

        <button
          type="button"
          className="ec-apply"
          onClick={() =>
            onCommand({
              type: "set_road_status",
              road_id: roadId,
              status: roadTo,
            })
          }
        >
          Apply closure
        </button>
      </fieldset>

      <fieldset className="ec-group" disabled={disabled}>
        <legend>Resource failure</legend>

        <label className="ec-field" htmlFor="ec-resource">
          <span>Resource</span>
          <select
            id="ec-resource"
            value={resourceId}
            onChange={(event) => setResourceId(event.target.value)}
          >
            {resourceList.map((resource) => (
              <option key={resource.id} value={resource.id}>
                {`${resource.id} ${resource.name}${resource.available ? "" : " · out of service"}`}
              </option>
            ))}
          </select>
        </label>

        <p className="ec-note">
          Takes effect at the next arrival with nobody aboard, or after the next
          unload (PRD section 5.8).
        </p>

        <button
          type="button"
          className="ec-apply"
          onClick={() =>
            onCommand({
              type: "set_resource_available",
              resource_id: resourceId,
              available: selectedResource ? !selectedResource.available : false,
            })
          }
        >
          {selectedResource?.available === false
            ? "Return to service"
            : "Take out of service"}
        </button>
      </fieldset>

      <fieldset className="ec-group ec-group-demo" disabled={disabled}>
        <legend>Demo disruption</legend>
        <p className="ec-note">
          Injects the wind shift and the R3 closure together at the current step
          boundary (PRD section 5.11, DV-08). Not a benchmark preset.
        </p>
        <button
          type="button"
          className="ec-apply ec-apply-strong"
          onClick={() =>
            onCommand({
              type: "inject_preset",
              preset: "wind_shift_and_closure",
            })
          }
        >
          Wind shift + road closure
        </button>
      </fieldset>
    </section>
  );
}

const SPEED_WORD: Record<number, string> = {
  1: "light",
  2: "moderate",
  3: "strong",
};

function byRoadId(a: Road, b: Road): number {
  return numericSuffix(a.id) - numericSuffix(b.id) || a.id.localeCompare(b.id);
}

function numericSuffix(id: string): number {
  const m = /(\d+)$/.exec(id);
  return m ? Number(m[1]) : 0;
}

function firstKey(record: Record<string, unknown>): string {
  const keys = Object.keys(record);
  return keys.length > 0 ? keys[0] : "";
}
