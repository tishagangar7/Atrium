import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, isStale, previewApi, type InjectEvent, type SavedRun } from "./api";
import { subscribeToEvents } from "./stream";
import { Icon } from "./components/Icon";
import { EscalationPanel } from "./components/EscalationPanel";
import { Inspector } from "./components/Inspector";
// WS-A's incident scene (PRD §12.2); WS-D only mounts it.
import { IncidentViewer } from "./simulation/prd/IncidentViewer";
import "./simulation/prd/incident.css";
import { PRESET_IDS, resetWorld, type PresetId } from "./simulation/prd/scenario";
import type {
  Evaluation as SceneEvaluation,
  Plan as ScenePlan,
  WorldState as SceneWorld,
} from "./simulation/prd/types";
import {
  agents,
  presets,
  type ScreenState,
  type StreamEvent,
  readScreenState,
} from "./components/shell-data";
import {
  acceptances,
  activityTypes,
  agentNames,
  agentStatus,
  authoritativeEval,
  comparison,
  describe,
  emptyIncident,
  inactiveStates,
  planLabel,
  reduceIncident,
  type Tone,
} from "./incident";
import type { AgentId, Plan, Resource, Snapshot } from "./types";
import "./App.css";

const agentIds: Record<string, AgentId> = { evac: "EVAC", fire: "FIRE", log: "LOG" };
const toneIcon: Record<Tone, "check" | "close" | "info" | "activity"> = {
  agree: "check",
  object: "close",
  alert: "info",
  neutral: "activity",
};
/** Step-0 world for the fixture preview, from WS-A's scenario data (shapes match the generated types). */
const sceneBaseWorld = (scenario: string, runId: string) =>
  (PRESET_IDS as readonly string[]).includes(scenario)
    ? (resetWorld(scenario as PresetId, { run_id: runId }) as unknown as Snapshot["world"])
    : null;

const percent = (value: number | null | undefined) =>
  value == null ? "N/A" : `${Math.round(value * 100)}%`;

type Panel = "activity" | "proposals" | "resources";
const panelNames: Record<Panel, string> = {
  activity: "Activity",
  proposals: "Proposals",
  resources: "Resources",
};

function App() {
  const [screen, setScreen] = useState<ScreenState | null>(null);
  const [preset, setPreset] = useState("normal");
  const [source, setSource] = useState<"preview" | "backend">("preview");
  const [connection, setConnection] = useState("Not connected");
  const [pending, setPending] = useState(false);
  const [testProvider, setTestProvider] = useState(false);
  const [modelAvailable, setModelAvailable] = useState(false);
  const [notice, setNotice] = useState("");
  const [subscription, setSubscription] = useState<{
    runId: string;
    afterSeq: number;
  } | null>(null);
  const [panel, setPanel] = useState<Panel>(() => {
    const value = new URLSearchParams(location.search).get("panel");
    return value === "proposals" || value === "resources" ? value : "activity";
  });
  const [events, setEvents] = useState<StreamEvent[]>([]);
  // Snapshot the stream continues from (§8.4): its own envelopes are at or below last_seq.
  const [baseSnapshot, setBaseSnapshot] = useState<Snapshot | null>(null);
  const [savedRuns, setSavedRuns] = useState<SavedRun[]>([]);
  const [replayChoice, setReplayChoice] = useState("");
  const [replaySpeed, setReplaySpeed] = useState<1 | 2 | 4>(1);
  const [replaySource, setReplaySource] = useState<SavedRun | null>(null);
  // Plan whose route the map highlights (set by clicking a proposal).
  const [routeHash, setRouteHash] = useState<string | null>(null);
  const [mapDetails, setMapDetails] = useState(false);
  const [inspection, setInspection] = useState<{
    title: string;
    value: unknown;
  } | null>(null);
  const replayTimer = useRef<number | null>(null);
  const selectedPreset = presets.find((item) => item.id === preset)!;
  const isPreview = source === "preview";
  // PRD §9.4 Replay: commands other than reset are disabled; a recording can't be changed.
  const isReplay = !isPreview && screen?.mode === "replay";
  const incident = useMemo(
    () =>
      events.reduce(reduceIncident, {
        ...emptyIncident,
        snapshot: baseSnapshot,
        escalation: baseSnapshot?.escalation ?? null,
      }),
    [events, baseSnapshot],
  );
  const accepted = useMemo(() => acceptances(incident), [incident]);
  const plans = useMemo(
    () => Object.values(incident.plans).reverse(),
    [incident.plans],
  );
  const committedHash = incident.commits.at(-1)?.plan_hash ?? null;
  const latest = events.at(-1);
  const activity = events
    .filter((event) => activityTypes.has(event.type))
    .slice(-40)
    .reverse();
  const world = incident.snapshot?.world;
  const beforeAfter = comparison(incident);
  const lifecycle = events.findLast((event) =>
    [
      "negotiation.started",
      "negotiation.cancelled",
      "plan.committed",
      "escalation.opened",
      "event.applied",
    ].includes(event.type),
  );
  const negotiating = lifecycle
    ? lifecycle.type === "negotiation.started"
    : screen?.status === "running";

  useEffect(
    () => () => {
      if (replayTimer.current) window.clearInterval(replayTimer.current);
    },
    [],
  );

  function stopReplay() {
    if (replayTimer.current) window.clearInterval(replayTimer.current);
    replayTimer.current = null;
  }

  /** Adopt a snapshot as the new starting point and stream from its last_seq (§8.4). */
  function follow(snapshot: Snapshot) {
    const next = readScreenState(snapshot);
    stopReplay();
    setBaseSnapshot(snapshot);
    setEvents([]);
    setScreen(next);
    setSubscription({ runId: next.runId, afterSeq: next.lastSeq });
    return next;
  }

  async function loadRuns() {
    try {
      const runs = await api.runs();
      setSavedRuns(runs);
      setReplayChoice((current) => current || runs[0]?.runId || "");
    } catch {
      setSavedRuns([]);
    }
  }

  async function startReplay() {
    const source = savedRuns.find((run) => run.runId === replayChoice);
    if (!source) return;
    setPending(true);
    try {
      await api.replay(source.runId, replaySpeed);
      const snapshot = await api.state();
      const next = readScreenState(snapshot);
      stopReplay();
      // A replay re-serves the whole recording, so stream it from the start (not last_seq).
      setBaseSnapshot(null);
      setEvents([]);
      setScreen(next);
      setReplaySource(source);
      setSubscription({ runId: next.runId, afterSeq: 0 });
      setNotice("Playing a recording of an earlier run. Nothing here is live.");
    } catch (error) {
      failed(error, "Couldn't start the replay.");
    } finally {
      setPending(false);
    }
  }

  async function refresh(message: string) {
    try {
      follow(await api.state());
      setNotice(message);
    } catch {
      setNotice("Couldn't refresh the incident. Check the backend, then reconnect.");
    }
  }

  async function resetBackend() {
    setPending(true);
    setNotice("");
    try {
      follow(await api.reset(preset));
      setReplaySource(null);
      void loadRuns();
      setNotice(`New run started: ${presets.find((item) => item.id === preset)?.name}.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Reset failed.");
    } finally {
      setPending(false);
    }
  }

  async function stepBackend() {
    if (!screen) return;
    setPending(true);
    try {
      const result = await api.step(screen);
      setScreen({ ...screen, step: result.step, version: result.version });
    } catch (error) {
      if (isStale(error))
        await refresh("The incident changed elsewhere – refreshed. Try again.");
      else setNotice(error instanceof Error ? error.message : "Step failed.");
    } finally {
      setPending(false);
    }
  }

  function failed(error: unknown, fallback: string) {
    if (error instanceof ApiError && error.code === "MODEL_UNAVAILABLE")
      setNotice("Model unavailable – live negotiation paused. Try again, or use the preview.");
    else if (error instanceof ApiError && error.code === "NEGOTIATION_IN_PROGRESS")
      setNotice("A negotiation is already running.");
    else setNotice(error instanceof Error ? error.message : fallback);
  }

  async function startNegotiation() {
    if (!screen) return;
    setPending(true);
    try {
      const { dpId } = await api.negotiate(screen);
      setNotice(`Negotiation ${dpId} started. The world is paused until it ends.`);
    } catch (error) {
      if (isStale(error))
        await refresh("The incident changed elsewhere – refreshed. Try again.");
      else failed(error, "Couldn't start the negotiation.");
    } finally {
      setPending(false);
    }
  }

  async function cancelNegotiation() {
    if (!screen) return;
    setPending(true);
    try {
      await api.cancel(screen.runId);
      setNotice("Cancel requested.");
    } catch (error) {
      failed(error, "Couldn't cancel.");
    } finally {
      setPending(false);
    }
  }

  async function injectEvent(event: InjectEvent) {
    if (!screen) return;
    setPending(true);
    try {
      // The inject guard is the negotiation session's version (see backend main.py).
      const version = incident.negotiationVersion ?? screen.version;
      await api.inject(screen.runId, version, event);
      setNotice("Conditions changed. Earlier plans are stale; the agents will renegotiate.");
    } catch (error) {
      if (isStale(error))
        await refresh("The incident changed before that landed – refreshed. Try again.");
      else failed(error, "Couldn't apply the event.");
    } finally {
      setPending(false);
    }
  }

  async function resolveEscalation(choice: "candidate" | "fallback", planHash?: string) {
    const escalation = incident.escalation;
    if (!screen || !escalation) return;
    setPending(true);
    try {
      await api.resolve(
        screen.runId,
        escalation.dp_id,
        incident.negotiationVersion ?? escalation.state_version,
        choice,
        planHash,
      );
      setNotice("Your decision was sent. It will appear as HUMAN DECISION.");
    } catch (error) {
      if (error instanceof ApiError && error.code === "PLAN_INFEASIBLE")
        setNotice("That plan is no longer feasible. Pick another option.");
      else if (error instanceof ApiError && error.code === "NO_ACTIVE_ESCALATION")
        setNotice("This escalation was already resolved.");
      else failed(error, "Couldn't send the decision.");
    } finally {
      setPending(false);
    }
  }

  function inspectPlan(plan: Plan) {
    setRouteHash(plan.plan_hash);
    setInspection({
      title: `Plan ${plan.plan_id}`,
      value: { plan, evaluation: authoritativeEval(incident, plan.plan_hash) },
    });
  }

  useEffect(() => {
    if (!subscription) return;
    let disposed = false;
    const unsubscribe = subscribeToEvents({
      ...subscription,
      onEvent(event) {
        setEvents((previous) => [...previous, event].slice(-2000));
        if (event.type === "state.snapshot") {
          try {
            setScreen(readScreenState(event.data));
          } catch {
            setNotice(
              "Snapshot format changed. Reconnect to refresh the incident.",
            );
          }
        }
      },
      onConnection: setConnection,
      onSnapshotRequired() {
        setNotice("The active run changed. Refreshing the incident…");
        void api
          .state()
          .then((snapshot) => {
            if (disposed) return;
            follow(snapshot);
            setNotice("Incident refreshed from the current snapshot.");
          })
          .catch(() => {
            if (!disposed)
              setNotice(
                "No current snapshot is available. Reconnect once the backend has an active run.",
              );
          });
      },
    });
    return () => {
      disposed = true;
      unsubscribe();
    };
  }, [subscription]);

  async function loadPreview() {
    setPending(true);
    setNotice("");
    try {
      const result = await previewApi.reset(preset, sceneBaseWorld);
      setSubscription(null);
      setSource("preview");
      setConnection("Not connected");
      setScreen(result.screen);
      setBaseSnapshot(null);
      stopReplay();
      setEvents([]);
      let index = 0;
      replayTimer.current = window.setInterval(() => {
        const next = result.events[index++];
        if (!next) return stopReplay();
        setEvents((previous) => [...previous, next]);
      }, 220);
      setNotice("Fixture preview playing. These are not simulator results.");
    } finally {
      setPending(false);
    }
  }

  async function connect() {
    setPending(true);
    setNotice("");
    try {
      const health = await api.health();
      if (!health.ok) throw new Error("Simulator is unavailable.");
      const snapshot = await api.state();
      setTestProvider(health.testProvider);
      setModelAvailable(health.modelAvailable);
      setSource("backend");
      setConnection("Connecting…");
      follow(snapshot);
      setReplaySource(null);
      void loadRuns();
      setNotice(
        health.modelAvailable
          ? "Connected. Reset and Step drive the backend; agents are not connected yet."
          : "Backend connected. Model unavailable, so negotiation is paused. Reset and Step work.",
      );
    } catch (error) {
      setNotice(
        `${error instanceof Error ? error.message : "Connection failed."} Start the backend on port 8000, then retry.`,
      );
    } finally {
      setPending(false);
    }
  }

  function selectPanel(next: Panel) {
    setPanel(next);
    const url = new URL(location.href);
    url.searchParams.set("panel", next);
    history.replaceState(null, "", url);
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#incident">
        Skip to incident
      </a>
      <header className="app-header">
        <a className="brand" href="/" aria-label="RescueMesh home">
          <span className="brand-symbol">
            <Icon name="mesh" />
          </span>
          RescueMesh
        </a>
        <span className="simulation-label">Synthetic simulation</span>
        <div className="header-end">
          <span className={`mode-label ${isPreview ? "" : "connected"}`}>
            {isPreview
              ? "FIXTURE"
              : screen?.mode === "replay"
                ? "REPLAY"
                : testProvider ||
                    (!modelAvailable &&
                      events.some((event) => event.type === "agent.turn"))
                  ? "TEST PROVIDER"
                  : !modelAvailable
                    ? "BACKEND PREVIEW"
                    : "LIVE"}
          </span>
          {isReplay && replaySource && (
            <span className="replay-source">
              ▶ {replaySource.preset ?? replaySource.runId}
              {replaySource.createdTs &&
                ` · recorded ${new Date(replaySource.createdTs).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}`}
            </span>
          )}
          <button
            className="text-button connection-button"
            onClick={connect}
            disabled={pending}
          >
            <span
              className={`status-dot ${connection === "Connected" ? "online" : ""}`}
            />
            {pending
              ? "Connecting…"
              : source === "backend"
                ? connection
                : "Connect simulator"}
            <Icon name="link" size={15} />
          </button>
        </div>
      </header>

      <main id="incident" tabIndex={-1}>
        <div className="page-heading">
          <div>
            <div className="breadcrumb">
              Operations <span>/</span> Wildfire response
            </div>
            <h1>One incident. Three perspectives.</h1>
            <p>
              A shared view of the response, from first proposal to agreement.
            </p>
          </div>
          <button
            className="secondary-button"
            onClick={() =>
              setInspection({
                title: "About this workspace",
                value:
                  "RescueMesh is a synthetic wildfire simulation. Evacuation, Fire Operations and Logistics negotiate independently. A plan commits only when all three accept the same plan hash at the current state version. This D1 UI preview contains no model-generated messages or simulation outcomes.",
              })
            }
          >
            <Icon name="info" size={16} />
            How it works
          </button>
        </div>

        {incident.escalation ? (
          <EscalationPanel
            escalation={incident.escalation}
            incident={incident}
            pending={pending}
            disabledReason={
              isPreview
                ? "Fixture preview – choices are disabled. Connect the simulator to decide for real."
                : isReplay
                  ? "Replay – choices are disabled."
                  : null
            }
            onChoose={resolveEscalation}
          />
        ) : (
          incident.stale && (
            <div className="banner stale" role="status">
              <Icon name="info" size={17} />
              <span>
                <strong>New evidence.</strong> The previous agreement is no
                longer valid.
              </span>
            </div>
          )
        )}

        <section className="forest-hero" aria-label="3D forest simulation">
          <iframe
            src="/forest.html"
            title="3D forest simulation (WS-A visual model)"
            loading="lazy"
          />
        </section>

        <div className="workspace">
          <section
            className="incident-panel"
            aria-labelledby="incident-heading"
          >
            <div className="panel-heading">
              <div className="title-with-icon">
                <Icon name="map" size={18} />
                <h2 id="incident-heading">Incident overview</h2>
              </div>
              <span className="quiet-label">
                {screen ? "Awaiting scene" : "No active incident"}
              </span>
            </div>
            <div className="incident-stage">
              {isReplay && (
                <div className="watermark" aria-hidden="true">
                  REPLAY
                </div>
              )}
              <div className="contour-art" aria-hidden="true">
                <svg viewBox="0 0 900 600" preserveAspectRatio="xMidYMid slice">
                  <g fill="none" stroke="currentColor" strokeWidth="1">
                    {Array.from({ length: 16 }, (_, index) => (
                      <path
                        key={index}
                        d={`M ${-220 + index * 19} -50 C ${550 + index * 12} ${60 + index * 10}, ${130 + index * 17} ${265 + index * 9}, ${520 + index * 22} 380 S ${680 + index * 20} 550, ${1080 + index * 19} 710`}
                      />
                    ))}
                    {Array.from({ length: 10 }, (_, index) => (
                      <ellipse
                        key={index}
                        cx="40"
                        cy="570"
                        rx={170 + index * 24}
                        ry={65 + index * 22}
                        transform="rotate(-25 40 570)"
                      />
                    ))}
                  </g>
                </svg>
              </div>
              <span className="stage-caption">
                {isPreview
                  ? "Preview workspace"
                  : `${screen?.mode === "replay" ? "REPLAY · " : ""}${screen?.runId}`}
              </span>
              {world && Object.keys(world.cells ?? {}).length > 0 ? (
                <div className={`viewer-mount ${mapDetails ? "details" : ""}`}>
                  <button
                    className="text-button map-details-toggle"
                    aria-expanded={mapDetails}
                    onClick={() => setMapDetails((open) => !open)}
                  >
                    {mapDetails ? "Hide map details" : "Map details"}
                  </button>
                  <IncidentViewer
                    snapshot={world as unknown as SceneWorld}
                    mode={isPreview ? "fixture" : isReplay ? "replay" : "live"}
                    selectedPlan={
                      (routeHash ? (incident.plans[routeHash] ?? null) : null) as unknown as ScenePlan | null
                    }
                    evaluation={
                      (routeHash ? authoritativeEval(incident, routeHash) : null) as unknown as SceneEvaluation | null
                    }
                  />
                  {routeHash && incident.plans[routeHash] && (
                    <button
                      className="route-chip"
                      onClick={() => setRouteHash(null)}
                    >
                      Showing route of {planLabel(incident.plans[routeHash], incident.dpId)} · clear
                      <Icon name="close" size={13} />
                    </button>
                  )}
                </div>
              ) : (
              <div className="stage-empty">
                  <span className="empty-symbol">
                    <Icon name="map" size={28} />
                  </span>
                  <h3>
                    {screen
                      ? "Ready for the incident scene"
                      : "Start with a scenario"}
                  </h3>
                  <p>
                    {screen
                      ? "Fire, roads and response routes will appear here once the incident viewer is integrated."
                      : "Load a preview to explore the workspace. No agents or simulation are running yet."}
                  </p>
                  {!screen && (
                    <button
                      className="primary-button"
                      onClick={loadPreview}
                      disabled={pending}
                    >
                      Load preview
                      <Icon name="arrow" size={17} />
                    </button>
                  )}
                  {screen && (
                    <span className="scene-placeholder">
                      Incident viewer pending
                    </span>
                  )}
                </div>
              )}
              <div className="stage-footer">
                <span>
                  <span className="small-cross" />
                  Scene placeholder
                </span>
                <span>No simulated outcomes</span>
              </div>
            </div>
            <div className="incident-summary">
              <div>
                <span>Scenario</span>
                <strong>
                  {screen
                    ? (presets.find((item) => item.id === screen.scenarioId)
                        ?.name ?? screen.scenarioId)
                    : "Not loaded"}
                </strong>
              </div>
              <div>
                <span>Step</span>
                <strong>{latest?.step ?? screen?.step ?? "—"}</strong>
              </div>
              {negotiating && incident.round && (
                <div>
                  <span>Negotiation</span>
                  <strong>Round {incident.round} of 4</strong>
                </div>
              )}
              <div>
                <span>State version</span>
                <strong>
                  {screen ? `v${latest?.state_version ?? screen.version}` : "—"}
                </strong>
              </div>
              <button
                className="text-button"
                disabled={!screen}
                onClick={() =>
                  setInspection({ title: "Incident state", value: screen?.raw })
                }
              >
                Inspect
                <Icon name="expand" size={15} />
              </button>
            </div>
          </section>

          <aside className="response-panel" aria-labelledby="response-heading">
            <div className="panel-heading">
              <h2 id="response-heading">Response team</h2>
              <span className="quiet-label">3 agents</span>
            </div>
            <p className="team-intro">
              Independent priorities.
              <br />
              One shared plan.
            </p>
            <div className="agents">
              {agents.map((agent) => {
                const id = agentIds[agent.id];
                const status = screen ? agentStatus(incident, id) : null;
                const mine = incident.messages.filter(
                  (message) => message.sender === id,
                );
                const last = mine.at(-1);
                const objection = mine.findLast(
                  (message) => message.objection,
                )?.objection;
                return (
                <details className={`agent-row ${agent.id}`} key={agent.id}>
                  <summary>
                    <span className="agent-icon">
                      <Icon name={agent.icon} size={20} />
                    </span>
                    <span className="agent-name">
                      <strong>{agent.name}</strong>
                      <span>{agent.summary}</span>
                      {status && (
                        <span
                          className={`chip ${status.startsWith("Accepts") ? "agree" : status.startsWith("Objects") ? "object" : status.startsWith("Unavailable") ? "alert" : ""}`}
                        >
                          {status}
                        </span>
                      )}
                    </span>
                    <Icon name="chevron" size={14} />
                  </summary>
                  <div className="agent-detail">
                    <p>{agent.objective}</p>
                    {last && <p className="rationale">“{last.rationale}”</p>}
                    {objection?.proposed_amendment && (
                      <p className="objection">
                        Suggests: {objection.proposed_amendment}
                      </p>
                    )}
                    <span className="agent-status">
                      {isPreview
                        ? "Fixture · not a live agent"
                        : (status ?? "No messages yet")}
                    </span>
                  </div>
                </details>
                );
              })}
            </div>
            <div className="agreement-note">
              <Icon name="agreement" size={19} />
              <div>
                <strong>Agreement takes all three</strong>
                <p>
                  Same plan. Same state version.
                  <br />
                  Otherwise, a human decides.
                </p>
              </div>
            </div>
            <div className="team-footer">
              <span className="status-dot" />
              <span>
                {incident.escalation
                  ? "Escalated · awaiting a human"
                  : committedHash && !incident.stale
                    ? "Plan committed by all three"
                    : incident.dpId
                      ? `Negotiating ${incident.dpId}`
                      : isPreview
                        ? "Awaiting a run"
                        : `Negotiation: ${screen?.status}`}
              </span>
            </div>
          </aside>
        </div>

        <section className="detail-panel" aria-label="Incident details">
          <div className="detail-heading">
            <div className="panel-tabs" aria-label="Detail views">
              {(Object.keys(panelNames) as Panel[]).map((key) => (
                <button
                  key={key}
                  aria-pressed={panel === key}
                  onClick={() => selectPanel(key)}
                >
                  {panelNames[key]}
                  {key === "activity" && activity.length > 0 && (
                    <span className="count">{activity.length}</span>
                  )}
                  {key === "proposals" && plans.length > 0 && (
                    <span className="count">{plans.length}</span>
                  )}
                </button>
              ))}
            </div>
            <span className="quiet-label">
              {panel === "activity"
                ? "Decision trail"
                : panel === "proposals"
                  ? "Simulator forecasts only"
                  : "Authoritative state only"}
            </span>
          </div>
          <div className="detail-body">
            {panel === "activity" &&
              (activity.length ? (
                <ol className="event-list">
                  {activity.map((event) => {
                    const line = describe(event);
                    return (
                    <li key={`${event.run_id}:${event.seq}`} className={`tone-${line.tone}`}>
                      <span className="event-mark">
                        <Icon name={toneIcon[line.tone]} size={14} />
                      </span>
                      <div>
                        <strong>{line.title}</strong>
                        <span>
                          {event.dp_id ? `${event.dp_id} · ` : ""}Step{" "}
                          {event.step} · state v{event.state_version}
                          {isPreview ? " · fixture" : ""}
                        </span>
                      </div>
                      <button
                        className="text-button"
                        onClick={() =>
                          setInspection({
                            title: "Event details",
                            value: event,
                          })
                        }
                      >
                        View event
                        <Icon name="arrow" size={15} />
                      </button>
                    </li>
                    );
                  })}
                </ol>
              ) : (
                <div className="inline-empty">
                  <Icon name="activity" size={23} />
                  <div>
                    <strong>The decision trail starts here</strong>
                    <p>
                      Proposals, shared evidence and agreements will appear as
                      the response unfolds.
                    </p>
                  </div>
                </div>
              ))}
            {panel === "proposals" &&
              (plans.length ? (
                <div className="plan-list">
                  {beforeAfter && (
                    <div className="compare" aria-label="Before and after the change">
                      {(["before", "after"] as const).map((side) => {
                        const { commit, evaluation } = beforeAfter[side];
                        return (
                          <div key={side}>
                            <span className="compare-label">
                              {side === "before" ? "Before the change" : "After"} ·{" "}
                              {commit.plan_id} · v{commit.state_version_before}
                            </span>
                            <span>
                              Assisted{" "}
                              <strong>
                                {evaluation?.valid
                                  ? percent(evaluation.metrics?.assisted_completion)
                                  : "—"}
                              </strong>
                            </span>
                            <span>
                              Fire{" "}
                              <strong>
                                {evaluation?.metrics ? `${evaluation.metrics.fire_extent} cells` : "—"}
                              </strong>
                            </span>
                            <span>
                              Violations <strong>{evaluation ? evaluation.violations.length : "—"}</strong>
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {plans.map((plan) => {
                    const evaluation = authoritativeEval(incident, plan.plan_hash);
                    const who = accepted[plan.plan_hash] ?? [];
                    const inactive = inactiveStates.has(plan.state);
                    return (
                      <button
                        key={plan.plan_hash}
                        className={`plan-row ${inactive ? "inactive" : ""}`}
                        onClick={() => inspectPlan(plan)}
                      >
                        <span className="plan-name">
                          <strong>
                            {planLabel(plan, incident.dpId)}
                            {plan.plan_hash === committedHash && (
                              <span title="Committed plan (not a recommendation)"> ★</span>
                            )}
                          </strong>
                          <span>by {agentNames[plan.proposer]}</span>
                        </span>
                        <span className={`state-pill ${plan.state.toLowerCase()}`}>
                          {plan.state.replace(/_/g, " ").toLowerCase()}
                        </span>
                        <span
                          className="dots"
                          aria-label={`${who.length} of 3 accept`}
                        >
                          {(["EVAC", "FIRE", "LOG"] as AgentId[]).map((agent) => (
                            <span
                              key={agent}
                              className={`dot ${agent.toLowerCase()} ${who.includes(agent) ? "on" : ""}`}
                              title={`${agentNames[agent]}${who.includes(agent) ? " accepts" : ""}`}
                            />
                          ))}
                        </span>
                        <span className="metric">
                          <span>Assisted</span>
                          {evaluation
                            ? evaluation.valid
                              ? percent(evaluation.metrics?.assisted_completion)
                              : "Invalid"
                            : "—"}
                        </span>
                        <span className="metric">
                          <span>Fire extent</span>
                          {evaluation?.metrics ? `${evaluation.metrics.fire_extent} cells` : "—"}
                        </span>
                        <span className={`metric ${evaluation?.violations.length ? "bad" : ""}`}>
                          <span>Violations</span>
                          {evaluation ? evaluation.violations.length : "—"}
                        </span>
                      </button>
                    );
                  })}
                  <p className="fine-print">
                    Forecasts by the simulator from the full operator view
                    {isPreview ? " · fixture placeholders, not results" : ""}.
                  </p>
                </div>
              ) : (
                <div className="inline-empty">
                  <Icon name="layers" size={23} />
                  <div>
                    <strong>No proposals yet</strong>
                    <p>
                      Plans and simulator forecasts appear after negotiation
                      begins. Nothing has been accepted.
                    </p>
                  </div>
                </div>
              ))}
            {panel === "resources" &&
              (world ? (
                <div className="resource-grid">
                  <div>
                    <h3>Vehicles &amp; crews</h3>
                    <ul>
                      {Object.values(world.resources as Record<string, Resource>).map((item) => {
                        const aboard = Object.values(item.aboard_people).reduce((a, b) => a + b, 0);
                        return (
                          <li key={item.id} className={item.available ? "" : "inactive"}>
                            <strong>{item.id}</strong>
                            <span>
                              {item.type === "transport" ? "shared transport" : item.type}
                              {" · "}
                              {item.edge ? `on ${item.edge}` : `at ${item.node ?? "?"}`}
                              {aboard ? ` · ${aboard} aboard` : ""}
                              {!item.available && " · out of service"}
                            </span>
                            {item.fuel_capacity != null && (
                              <span className="meter" title={`Fuel ${item.fuel_capacity - item.fuel_used}/${item.fuel_capacity}`}>
                                <span style={{ width: `${((item.fuel_capacity - item.fuel_used) / item.fuel_capacity) * 100}%` }} />
                              </span>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                  <div>
                    <h3>Shelters</h3>
                    <ul>
                      {Object.values(world.shelters).map((shelter) => {
                        const used = shelter.background + shelter.arrivals;
                        return (
                          <li key={shelter.id}>
                            <strong>{shelter.name}</strong>
                            <span>
                              {used} / {shelter.capacity} occupied
                            </span>
                            <span className={`meter ${used / shelter.capacity > 0.9 ? "warn" : ""}`}>
                              <span style={{ width: `${(used / shelter.capacity) * 100}%` }} />
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                  <div>
                    <h3>Assisted residents waiting</h3>
                    <ul>
                      {Object.values(world.zones).map((zone) => (
                        <li key={zone.id}>
                          <strong>{zone.name}</strong>
                          <span>
                            {zone.assisted_initial - zone.assisted_picked_up} of{" "}
                            {zone.assisted_initial} waiting
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              ) : (
                <div className="inline-empty">
                  <Icon name="truck" size={23} />
                  <div>
                    <strong>Resources await the simulator</strong>
                    <p>
                      Vehicles, crews and shelter capacity will come from the
                      incident’s authoritative state.
                    </p>
                  </div>
                </div>
              ))}
          </div>
        </section>

        <section className="control-bar" aria-label="Scenario controls">
          <div className="scenario-control">
            <Icon name="layers" size={19} />
            <div>
              <label htmlFor="scenario">Scenario preset</label>
              <select
                id="scenario"
                name="scenario"
                value={preset}
                onChange={(event) => setPreset(event.target.value)}
                disabled={pending}
              >
                {presets.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {isPreview && (
            <p className="preset-description">{selectedPreset.description}</p>
          )}
          {!isPreview && (
            <div className="replay-control">
              <label htmlFor="replay-run">Replay a run</label>
              <div>
                <select
                  id="replay-run"
                  value={replayChoice}
                  onChange={(event) => setReplayChoice(event.target.value)}
                  disabled={pending || savedRuns.length === 0}
                >
                  {savedRuns.length === 0 && <option value="">No saved runs yet</option>}
                  {savedRuns.map((run) => (
                    <option key={run.runId} value={run.runId}>
                      {(presets.find((item) => item.id === run.preset)?.name ?? run.preset ?? "Run")}
                      {run.createdTs
                        ? ` · ${new Date(run.createdTs).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
                        : ""}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="Replay speed"
                  value={replaySpeed}
                  onChange={(event) => setReplaySpeed(Number(event.target.value) as 1 | 2 | 4)}
                  disabled={pending}
                >
                  <option value={1}>1×</option>
                  <option value={2}>2×</option>
                  <option value={4}>4×</option>
                </select>
                <button
                  className="text-button"
                  disabled={pending || !replayChoice}
                  onClick={startReplay}
                >
                  <Icon name="play" size={14} />
                  Play
                </button>
              </div>
            </div>
          )}
          <div className="control-actions">
            {isPreview ? (
              <button
                className="secondary-button"
                disabled={pending}
                onClick={loadPreview}
              >
                <Icon name={screen ? "reset" : "play"} size={16} />
                {screen ? "Reload preview" : "Load preview"}
              </button>
            ) : (
              <>
                <button
                  className="secondary-button"
                  disabled={pending}
                  onClick={resetBackend}
                >
                  <Icon name="reset" size={16} />
                  Reset scenario
                </button>
                <button
                  className="secondary-button"
                  disabled={pending || !screen || negotiating || isReplay}
                  onClick={stepBackend}
                  title={negotiating ? "The world is paused during negotiation" : undefined}
                >
                  <Icon name="arrow" size={16} />
                  Step
                </button>
              </>
            )}
            {!isPreview && (
              <>
                <button
                  className="secondary-button"
                  disabled={pending || !screen || isReplay}
                  onClick={() => injectEvent("wind_shift_road_closure")}
                >
                  Wind shift + road closure
                </button>
                <button
                  className="secondary-button"
                  disabled={pending || !screen || isReplay}
                  onClick={() => injectEvent("compound_failure")}
                >
                  Compound failure
                </button>
              </>
            )}
            {!isPreview && !isReplay && negotiating ? (
              <button
                className="primary-button"
                disabled={pending}
                onClick={cancelNegotiation}
              >
                <Icon name="close" size={16} />
                Cancel negotiation
              </button>
            ) : (
              <button
                className="primary-button"
                disabled={isPreview || isReplay || pending || !screen || !!incident.escalation}
                aria-describedby="control-help"
                onClick={startNegotiation}
              >
                <Icon name="play" size={16} />
                Start negotiation
              </button>
            )}
          </div>
        </section>
        <footer className="workspace-footer">
          <span id="control-help">
            {isPreview
              ? "UI preview — connect the simulator to run a response."
              : isReplay
                ? "Replay – a recording of an earlier run. Commands are disabled."
                : incident.escalation
                ? "Resolve the escalation above before negotiating again."
                : negotiating
                  ? "Negotiating – the world is paused until it ends."
                  : "Start a negotiation, or change conditions to see the agents adapt."}
          </span>
          <button
            className="text-button"
            onClick={() =>
              setInspection({
                title: "Run results",
                value:
                  "No results are available. Comparisons, costs and executed outcomes will be shown only after recorded simulator runs exist.",
              })
            }
          >
            Run results
            <Icon name="arrow" size={14} />
          </button>
        </footer>
        <div className={`notice ${notice ? "visible" : ""}`} role="status">
          {notice && (
            <>
              <Icon name="info" size={18} />
              <span>{notice}</span>
              <button aria-label="Dismiss notice" onClick={() => setNotice("")}>
                <Icon name="close" size={16} />
              </button>
            </>
          )}
        </div>
      </main>
      {inspection && (
        <Inspector
          title={inspection.title}
          value={inspection.value}
          onClose={() => setInspection(null)}
        />
      )}
    </div>
  );
}
export default App;
