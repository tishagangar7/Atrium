import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowUpRight,
  ChevronDown,
  Compass,
  Flame,
  Focus,
  Layers3,
  Leaf,
  MapPin,
  Pause,
  Play,
  Radio,
  RotateCcw,
  Shield,
  SkipForward,
  SlidersHorizontal,
  Thermometer,
  Users,
  Wind,
  X,
} from "lucide-react";
import { createWorld } from "./engine";
import { scenario } from "./terrain";
import { Scene, type Layer } from "./Scene";
import type {
  Intervention,
  Snapshot,
  Weather,
  WorkerCommand,
  WorkerReply,
} from "./types";
import "./simulation.css";

const presetLabels = {
  dry: "Dry autumn afternoon",
  coastal: "Coastal marine layer",
  offshore: "Offshore wind event",
};
const initial = createWorld();
const timeLabel = (seconds: number) =>
  `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
export function App() {
  const [world, setWorld] = useState<Snapshot>(initial);
  const [playing, setPlaying] = useState(false);
  const [ready, setReady] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [preset, setPreset] = useState<keyof typeof presetLabels>("dry");
  const [weather, setWeather] = useState<Weather>(scenario.weather);
  const [layer, setLayer] = useState<Layer>("landscape");
  const [selected, setSelected] = useState<number | null>(null);
  const [cameraMode, setCameraMode] = useState<"orbit" | "top">("orbit");
  const [cameraReset, setCameraReset] = useState(0);
  const [tab, setTab] = useState<"environment" | "agents">("environment");
  const [error, setError] = useState("");
  const [info, setInfo] = useState(false);
  const [seed, setSeed] = useState(42);
  const [forecast, setForecast] = useState<Extract<
    WorkerReply,
    { type: "evaluation" }
  > | null>(null);
  const worker = useRef<Worker | null>(null);
  const dialog = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!info || !dialog.current) return;
    const previous = document.activeElement as HTMLElement | null;
    const panel = dialog.current;
    const focusable = () =>
      Array.from(
        panel.querySelectorAll<HTMLElement>(
          'button, a[href], input, select, [tabindex="0"]',
        ),
      );
    focusable()[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setInfo(false);
      if (event.key !== "Tab") return;
      const items = focusable(),
        first = items[0],
        last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      }
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    panel.addEventListener("keydown", onKey);
    return () => {
      panel.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [info]);
  useEffect(() => {
    const w = new Worker(new URL("./simulation.worker.ts", import.meta.url), {
      type: "module",
    });
    worker.current = w;
    w.onmessage = (event: MessageEvent<WorkerReply>) => {
      const reply = event.data;
      if (reply.type === "snapshot") {
        setWorld(reply.snapshot);
        setPlaying(reply.playing);
        setReady(true);
        window.dispatchEvent(
          new CustomEvent("rescuemesh:snapshot", {
            detail: structuredClone(reply.snapshot),
          }),
        );
      } else if (reply.type === "error") setError(reply.message);
      else {
        setForecast(reply);
        window.dispatchEvent(
          new CustomEvent("rescuemesh:evaluation", { detail: reply }),
        );
      }
    };
    w.onerror = () => {
      setError("Simulation worker failed. Reload the page to restart.");
      setReady(false);
    };
    // Same-page integration seam. Agent integrations may observe/evaluate, never bypass a commit gate.
    const evaluate = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (detail?.type !== "evaluate" || typeof detail.requestId !== "string")
        return;
      w.postMessage(detail);
    };
    window.addEventListener("rescuemesh:evaluate", evaluate);
    return () => {
      w.terminate();
      worker.current = null;
      window.removeEventListener("rescuemesh:evaluate", evaluate);
    };
  }, []);
  function send(command: WorkerCommand) {
    setError("");
    worker.current?.postMessage(command);
  }
  function intervene(intervention: Intervention) {
    send({
      type: "intervene",
      expectedVersion: world.state_version,
      intervention,
    });
  }
  function reset(nextPreset = preset) {
    const nextWeather = scenario.presets[nextPreset];
    setWeather(nextWeather);
    setForecast(null);
    setSelected(null);
    send({ type: "reset", seed, weather: nextWeather });
  }
  function exportRun() {
    const blob = new Blob(
      [
        JSON.stringify(
          {
            ...world,
            mode: "synthetic-browser-simulation",
            scenario,
            note: "Snapshot and last 80 events; not a replay trace or a validated forecast.",
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${world.run_id}-v${world.state_version}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const cell = selected === null ? null : world.cells[selected];
  const draftChanged =
    JSON.stringify(weather) !== JSON.stringify(world.weather);
  return (
    <div className="simulation-app">
      <header className="topbar">
        <a className="brand" href="#" aria-label="RescueMesh home">
          <span className="brand-mark">
            <Flame size={21} />
          </span>
          rescue<span>mesh</span>
          <span className="brand-divider" />
          <small>FIELD LAB</small>
        </a>
        <nav aria-label="Main navigation">
          <span className="nav-active">Simulation</span>
          <button onClick={() => setInfo(true)}>
            Model & sources <ArrowUpRight size={13} />
          </button>
        </nav>
        <div className="synthetic-pill">
          <span className="status-dot" /> Synthetic simulation
        </div>
      </header>
      <div className="workspace-header">
        <div>
          <div className="breadcrumb">
            SANTA CRUZ, CALIFORNIA <span>/</span> UCSC FOREST INTERFACE
          </div>
          <h1>
            A spark at the forest edge<span>.</span>
          </h1>
          <p>
            Music Center & Great Meadow <span>·</span> A small landscape. A
            connected response.
          </p>
        </div>
        <button className="export-button" onClick={exportRun}>
          <ArrowDownToLine size={15} /> Export snapshot
        </button>
      </div>
      <main className="lab-grid">
        <section className="scene-panel" aria-label="3D simulation">
          <div className="scene-heading">
            <div>
              <span className="live-dot" />{" "}
              {playing
                ? "SIMULATION RUNNING"
                : world.completed
                  ? "RUN COMPLETE"
                  : "SIMULATION PAUSED"}
            </div>
            <span>
              SCENARIO 01 <span className="muted">/</span> REDWOOD EDGE
            </span>
          </div>
          <Scene
            snapshot={world}
            layer={layer}
            selected={selected}
            onSelect={setSelected}
            cameraMode={cameraMode}
            resetCamera={cameraReset}
          />
          <div className="scene-location">
            <MapPin size={14} />
            <span>
              Music Center forest opening
              <small>320 × 240 m · schematic terrain</small>
            </span>
          </div>
          <div className="view-tools">
            <button
              title="Reset camera"
              aria-label="Reset camera"
              onClick={() => setCameraReset((n) => n + 1)}
            >
              <Focus size={17} />
            </button>
            <button
              title="Toggle overhead view"
              aria-label="Toggle overhead view"
              aria-pressed={cameraMode === "top"}
              onClick={() =>
                setCameraMode((m) => (m === "top" ? "orbit" : "top"))
              }
            >
              <Compass size={17} />
            </button>
          </div>
          <div className="north-indicator">
            N<span>↑</span>
            <small>NORTH</small>
          </div>
          {cell && (
            <div className="cell-inspector">
              <button
                aria-label="Close cell inspector"
                onClick={() => setSelected(null)}
              >
                <X size={14} />
              </button>
              <div className="eyebrow">
                CELL {cell.id} · {cell.kind.toUpperCase()}
              </div>
              <strong>
                {cell.intensity
                  ? "Active surface fire"
                  : cell.burned
                    ? "Burn scar"
                    : "Unburned vegetation"}
              </strong>
              <p>
                {cell.fuel.toFixed(2)} kg/m² fuel · {cell.moisture.toFixed(1)}%
                moisture
              </p>
              <div>
                <button
                  disabled={playing || !cell.fuel || !ready || world.completed}
                  onClick={() => intervene({ type: "ignite", cell: cell.id })}
                >
                  Ignite here
                </button>
                <button
                  disabled={playing || !ready || world.completed}
                  onClick={() =>
                    intervene({ type: "suppress", cells: [cell.id] })
                  }
                >
                  Treat cell
                </button>
              </div>
            </div>
          )}
          <div className="scene-bottom">
            <div className="layers" aria-label="Map layers">
              <Layers3 size={14} />
              {(["landscape", "fuel", "heat"] as const).map((l) => (
                <button
                  key={l}
                  aria-pressed={layer === l}
                  className={layer === l ? "active" : ""}
                  onClick={() => setLayer(l)}
                >
                  {l === "landscape"
                    ? "Landscape"
                    : l === "fuel"
                      ? "Fuel beds"
                      : "Fire extent"}
                </button>
              ))}
            </div>
            <span className="scene-hint">
              Drag to orbit · Scroll to zoom · Click to inspect
            </span>
          </div>
          <div className="legend">
            <span>
              <i style={{ background: "#528365" }} />
              Redwood understory
            </span>
            <span>
              <i style={{ background: "#b8ac6c" }} />
              Dry grass
            </span>
            <span>
              <i style={{ background: "#f88d4c" }} />
              Active fire
            </span>
            <span>
              <i style={{ background: "#6ac4ac" }} />
              Treatment
            </span>
          </div>
        </section>
        <aside className="control-panel">
          <div className="panel-tabs">
            <button
              className={tab === "environment" ? "active" : ""}
              onClick={() => setTab("environment")}
            >
              <SlidersHorizontal size={15} />
              Environment
            </button>
            <button
              className={tab === "agents" ? "active" : ""}
              onClick={() => setTab("agents")}
            >
              <Radio size={15} />
              Agent link <i />
            </button>
          </div>
          {tab === "environment" ? (
            <>
              <div className="control-section">
                <div className="section-label">
                  SCENARIO CONDITIONS <span>01</span>
                </div>
                <label className="select-label">
                  Weather profile
                  <select
                    value={preset}
                    onChange={(e) => {
                      const next = e.target.value as typeof preset;
                      setPreset(next);
                      reset(next);
                    }}
                    disabled={!ready}
                  >
                    <option value="dry">{presetLabels.dry}</option>
                    <option value="coastal">{presetLabels.coastal}</option>
                    <option value="offshore">{presetLabels.offshore}</option>
                  </select>
                  <ChevronDown size={15} />
                </label>
                <p className="subtle">
                  Synthetic conditions, not a live weather feed.
                </p>
              </div>
              <div className="control-section">
                <div className="section-label">
                  ATMOSPHERE <Wind size={15} />
                </div>
                <Slider
                  label="Wind speed"
                  value={weather.windSpeed}
                  min={0}
                  max={25}
                  unit="m/s"
                  onChange={(windSpeed) =>
                    setWeather((w) => ({ ...w, windSpeed }))
                  }
                />
                <Slider
                  label="Wind blows toward"
                  value={weather.windToward}
                  min={0}
                  max={360}
                  step={5}
                  unit="°"
                  onChange={(windToward) =>
                    setWeather((w) => ({ ...w, windToward }))
                  }
                />
                <Slider
                  label="Relative humidity"
                  value={weather.humidity}
                  min={1}
                  max={100}
                  unit="%"
                  onChange={(humidity) =>
                    setWeather((w) => ({ ...w, humidity }))
                  }
                />
                <Slider
                  label="Air temperature"
                  value={weather.temperature}
                  min={0}
                  max={50}
                  unit="°C"
                  onChange={(temperature) =>
                    setWeather((w) => ({ ...w, temperature }))
                  }
                />
              </div>
              <div className="control-section fuel-section">
                <div className="section-label">
                  GROUND FUELS <Leaf size={15} />
                </div>
                <Slider
                  label="Fine dead fuel moisture"
                  value={weather.fuelMoisture}
                  min={1}
                  max={40}
                  unit="%"
                  onChange={(fuelMoisture) =>
                    setWeather((w) => ({ ...w, fuelMoisture }))
                  }
                />
                <div className="fuel-note">
                  <span />
                  <p>
                    Fire starts in litter and understory. Mature redwoods are
                    not modeled as instant canopy ignition.
                  </p>
                </div>
                <button
                  className="apply-button"
                  disabled={
                    !draftChanged || !ready || playing || world.completed
                  }
                  onClick={() => intervene({ type: "weather", weather })}
                >
                  {playing && draftChanged
                    ? "Pause to apply conditions"
                    : draftChanged
                      ? "Apply conditions"
                      : "Conditions applied"}
                  <ArrowUpRight size={14} />
                </button>
              </div>
            </>
          ) : (
            <AgentPanel world={world} forecast={forecast} />
          )}
        </aside>
        <section className="transport" aria-label="Playback controls">
          <div className="playback-buttons">
            <button
              className="play-button"
              disabled={!ready || world.completed}
              onClick={() => send({ type: "play", playing: !playing, speed })}
            >
              {playing ? (
                <Pause size={16} fill="currentColor" />
              ) : (
                <Play size={16} fill="currentColor" />
              )}
              {playing ? "Pause" : "Run simulation"}
            </button>
            <button
              className="square-button"
              disabled={!ready || playing || world.completed}
              aria-label="Advance 10 seconds"
              title="Advance 10 simulated seconds"
              onClick={() => send({ type: "step" })}
            >
              <SkipForward size={17} />
            </button>
            <button
              className="square-button"
              disabled={!ready}
              aria-label="Reset simulation"
              title="Reset simulation"
              onClick={() => reset()}
            >
              <RotateCcw size={16} />
            </button>
          </div>
          <div className="simulation-clock">
            <span>SIMULATED TIME</span>
            <strong>
              {timeLabel(world.seconds)}
              <small> / 120:00</small>
            </strong>
          </div>
          <div className="timeline-track">
            <div
              style={{
                width: `${(world.step / scenario.horizonSteps) * 100}%`,
              }}
            />
          </div>
          <div className="speed-controls">
            {[1, 2, 4].map((n) => (
              <button
                key={n}
                className={speed === n ? "active" : ""}
                onClick={() => {
                  setSpeed(n);
                  if (playing) send({ type: "play", playing: true, speed: n });
                }}
              >
                {n}×
              </button>
            ))}
          </div>
        </section>
        <section className="metrics" aria-label="Executed simulation metrics">
          <Metric
            icon={<Flame size={17} />}
            name="FIRE FOOTPRINT"
            value={world.metrics.affectedHa.toFixed(2)}
            unit="ha"
            description="Area ever ignited"
            tone="orange"
          />
          <Metric
            icon={<Activity size={17} />}
            name="ACTIVE FIRE"
            value={String(world.metrics.burning)}
            unit="cells"
            description="8 × 8 m ground cells"
            tone="orange"
          />
          <Metric
            icon={<Thermometer size={17} />}
            name="HEAT RELEASE"
            value={world.metrics.heatMW.toFixed(1)}
            unit="MW"
            description="Modeled surface combustion"
          />
          <Metric
            icon={<Wind size={17} />}
            name="SPOT IGNITIONS"
            value={String(world.metrics.spotIgnitions)}
            unit=""
            description="From landed windborne embers"
          />
        </section>
        <section className="lower-panel">
          <div className="section-label">
            EVENT OBSERVATIONS <span>STATE v{world.state_version}</span>
          </div>
          <div className="event-list">
            {world.events
              .slice(-4)
              .reverse()
              .map((event) => (
                <div key={event.seq}>
                  <span>{timeLabel(event.step * scenario.stepSeconds)}</span>
                  <i className={event.kind} />
                  <p>{event.text}</p>
                </div>
              ))}
          </div>
        </section>
        <section className="lower-panel experiment">
          <div className="section-label">
            EXPERIMENT TOOLS <Shield size={14} />
          </div>
          <div className="experiment-actions">
            <button
              disabled={playing || !ready || world.completed}
              onClick={() =>
                intervene({ type: "closure", closed: !world.roadClosed })
              }
            >
              {world.roadClosed ? "Reopen access road" : "Close access road"}
            </button>
            <button
              disabled={playing || !ready || world.completed}
              onClick={() => {
                const cells = world.cells
                  .filter((c) => c.intensity > 0)
                  .slice(0, 12)
                  .map((c) => c.id);
                if (!cells.length) {
                  setError("No active fire to treat.");
                  return;
                }
                send({
                  type: "evaluate",
                  requestId: `treatment-v${world.state_version}`,
                  expectedVersion: world.state_version,
                  intervention: { type: "suppress", cells },
                  steps: 60,
                });
                setTab("agents");
              }}
            >
              Forecast treatment
            </button>
          </div>
          <label className="seed-label">
            Deterministic seed
            <input
              aria-label="Scenario seed"
              type="number"
              min={0}
              max={999999}
              value={seed}
              onChange={(e) =>
                setSeed(
                  Math.max(
                    0,
                    Math.min(999999, Math.floor(Number(e.target.value) || 0)),
                  ),
                )
              }
            />
            <span>Applied on reset</span>
          </label>
        </section>
      </main>
      <footer>
        <span>
          <span className="status-dot" />{" "}
          {ready ? "Worker connected" : "Starting physics worker"} <b>·</b>{" "}
          Agent service not connected <b>·</b> Seed {world.seed}
        </span>
        <button onClick={() => setInfo(true)}>
          Synthetic research demo · Model limitations <ArrowUpRight size={12} />
        </button>
      </footer>
      {error && (
        <div className="error-toast" role="alert">
          {error}
          <button aria-label="Dismiss error" onClick={() => setError("")}>
            <X size={16} />
          </button>
        </div>
      )}
      {info && (
        <div className="modal-backdrop" onClick={() => setInfo(false)}>
          <section
            className="model-modal"
            ref={dialog}
            role="dialog"
            aria-modal="true"
            aria-label="Model and sources"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close"
              aria-label="Close model details"
              onClick={() => setInfo(false)}
            >
              <X />
            </button>
            <div className="eyebrow">MODEL CARD · UCSC VISUAL V1</div>
            <h2>
              A landscape to explore.
              <br />A model to question.
            </h2>
            <p>
              A synthetic 7.68 ha patch inspired by the Music Center / Great
              Meadow redwood edge. Terrain, buildings, fuels and weather are
              procedural, not surveyed or observed.
            </p>
            <h3>What is simulated</h3>
            <p>
              Seeded surface-fire spread responds to wind, upslope heating, fuel
              load and moisture. Combustion consumes finite fuel. Embers use
              gravity, drag and decaying buoyant lift. Humidity and temperature
              influence drying over time.
            </p>
            <h3>What is simplified</h3>
            <p>
              This is not a validated Rothermel implementation, CFD model,
              operational forecast or evacuation tool. It excludes crown-fire
              transitions, atmospheric feedback, structural fire, toxicology and
              actual campus routing. Smoke is a visual effect, not a
              concentration field. Treatments are operator experiments, not
              deployed crews.
            </p>
            <h3>California fire context</h3>
            <p>
              Dry summers and autumn fuels, low humidity, strong offshore winds,
              steep slopes and accumulated litter can favor spread. Human
              activity, equipment, power infrastructure and lightning can
              initiate fires. This demo injects an illustrative ignition; it
              attributes no incident or real risk rating to this site.
            </p>
            <h3>Grounding & references</h3>
            <ul>
              {scenario.sources.map((url, i) => (
                <li key={url}>
                  <a href={url} target="_blank" rel="noreferrer">
                    {
                      [
                        "UCSC Music Center: meadow meets redwood forest",
                        "USFS: wind, slope and fuel-moisture experiments",
                        "USFS: coast redwood fire ecology",
                        "USFS: surface, ladder and canopy fuels",
                        "CAL FIRE: utility ignition mechanisms",
                      ][i]
                    }{" "}
                    <ArrowUpRight size={12} />
                  </a>
                </li>
              ))}
            </ul>
            <button className="apply-button" onClick={() => setInfo(false)}>
              Back to the landscape
            </button>
          </section>
        </div>
      )}
    </div>
  );
}
function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  unit,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit: string;
  onChange: (v: number) => void;
}) {
  return (
    <label className="slider-label">
      <span>
        {label}
        <strong>
          {value}
          <small>{unit}</small>
        </strong>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={
          {
            "--progress": `${((value - min) / (max - min)) * 100}%`,
          } as React.CSSProperties
        }
      />
    </label>
  );
}
function Metric({
  icon,
  name,
  value,
  unit,
  description,
  tone = "",
}: {
  icon: React.ReactNode;
  name: string;
  value: string;
  unit: string;
  description: string;
  tone?: string;
}) {
  return (
    <article className={`metric ${tone}`}>
      <div>
        {icon}
        <span>{name}</span>
      </div>
      <strong>
        {value}
        <small>{unit}</small>
      </strong>
      <p>{description}</p>
    </article>
  );
}
function AgentPanel({
  world,
  forecast,
}: {
  world: Snapshot;
  forecast: Extract<WorkerReply, { type: "evaluation" }> | null;
}) {
  return (
    <div className="agent-panel">
      <div className="section-label">
        PARALLEL AGENT INTERFACE <Radio size={14} />
      </div>
      <h2>
        One world.
        <br />
        Three perspectives.
      </h2>
      <p>
        The physics worker runs independently of the page. Versioned snapshots
        are available to the agent integration.
      </p>
      {[
        {
          name: "Evacuation",
          icon: <Users size={17} />,
          detail: "Observe evolving fire and access status.",
        },
        {
          name: "Fire Operations",
          icon: <Flame size={17} />,
          detail: "Evaluate treatment on an isolated copy.",
        },
        {
          name: "Logistics",
          icon: <Shield size={17} />,
          detail: "Observe road closures and state revisions.",
        },
      ].map((a) => (
        <article className="agent-slot" key={a.name}>
          <span>{a.icon}</span>
          <div>
            <strong>{a.name}</strong>
            <p>{a.detail}</p>
            <small>NOT CONNECTED</small>
          </div>
        </article>
      ))}
      <div className="adapter-status">
        <span className="status-dot" /> Snapshot v{world.state_version}
        <small>No scripted negotiations or AI decisions.</small>
      </div>
      {forecast && (
        <div className="forecast-card">
          <div className="section-label">COUNTERFACTUAL · 10 MIN</div>
          <strong>{forecast.metrics.affectedHa.toFixed(2)} ha</strong>
          <p>
            Predicted footprint with up to 12 treated cells. Source v
            {forecast.state_version}
            {forecast.state_version !== world.state_version
              ? " · STALE: world has changed"
              : " · current state"}
            .
          </p>
          <small>
            Authoritative world was not changed. Not an agent proposal or a
            comparison against no treatment.
          </small>
        </div>
      )}
    </div>
  );
}
