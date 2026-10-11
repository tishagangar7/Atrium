// FIXTURE – hand-written envelopes for UI development (WS-D). NOT live output, NOT results.
// Scenario values follow PRD §5; every metric number is a layout placeholder.
import type {
  AgentId,
  AgentMessage,
  Commit,
  EscalationPackage,
  Evaluation,
  Metrics,
  MessageType,
  Objection,
  Plan,
  Resource,
  Snapshot,
  WorldState,
} from "../types";
import type { StreamEvent } from "../components/shell-data";
/** Builds a step-0 world for a preset (WS-A's `resetWorld`, passed in by the browser app so
 * Node unit tests don't have to load scenario JSON). Without it the world has no cells. */
export type BaseWorld = (scenario: string, runId: string) => WorldState | null;

const zeroMetrics: Metrics = {
  civilian_exposure: 0,
  assisted_completion: 0,
  assisted_sheltered: 0,
  assisted_demand: 110,
  evacuation_completion_step: null,
  fire_extent: 0,
  burning_cell_steps: 0,
  crew_risk_steps: 0,
  logistics_risk: 0,
  invalid_attempted: 0,
  invalid_executed: 0,
};

const resource = (
  id: string,
  type: Resource["type"],
  node: string,
  capacity: number,
  fuel: number | null,
  extra: Partial<Resource> = {},
): Resource => ({
  id,
  type,
  node,
  edge: null,
  edge_steps_left: 0,
  capacity,
  fuel_capacity: fuel,
  fuel_used: 0,
  aboard_people: {},
  aboard_crew: null,
  engine_node: type === "crew" ? node : null,
  available: true,
  ...extra,
});

function world(runId: string, scenario: string, step: number, version: number, moved = false, baseWorld?: BaseWorld): WorldState {
  const base = baseWorld?.(scenario, runId) ?? null;
  return {
    roads: {},
    cells: {},
    wind: { direction: "E", speed: 2 },
    ...base,
    schema_version: "1",
    run_id: runId,
    scenario_id: base?.scenario_id ?? scenario,
    seed: 1,
    step,
    state_version: version,
    zones: {
      NC: { id: "NC", name: "North Camp", cell: "c3_0", unassisted_initial: 20, assisted_initial: 20, self_evacuated: moved ? 20 : 0, assisted_picked_up: 0 },
      PR: { id: "PR", name: "Pine Ridge", cell: "c3_2", unassisted_initial: 90, assisted_initial: 30, self_evacuated: moved ? 90 : 0, assisted_picked_up: moved ? 10 : 0 },
      VJ: { id: "VJ", name: "Valley Junction", cell: "c5_4", unassisted_initial: 240, assisted_initial: 60, self_evacuated: moved ? 240 : 0, assisted_picked_up: moved ? 30 : 0 },
    },
    shelters: {
      SE: { id: "SE", name: "Shelter East", cell: "c9_2", capacity: 150, background: 40, arrivals: 0 },
      SS: { id: "SS", name: "Shelter South", cell: "c6_5", capacity: 350, background: 320, arrivals: moved ? 30 : 0 },
    },
    resources: {
      B1: resource("B1", "bus", moved ? "SS" : "BASE", 30, 40, moved ? { fuel_used: 9 } : {}),
      B2: resource("B2", "bus", "BASE", 30, 40),
      V1: resource("V1", "transport", moved ? "PR" : "BASE", 10, 30, moved ? { fuel_used: 6, aboard_people: { PR: 10 } } : {}),
      C1: resource("C1", "crew", "FORK", 0, null),
      C2: resource("C2", "crew", "FORK", 0, null),
      C3: resource("C3", "crew", moved ? "FORK" : "BASE", 0, null),
    },
    committed_plan_hash: null,
    active_legs: [],
    metrics_so_far: base?.metrics_so_far ?? zeroMetrics,
    paused: true,
  };
}

function flow(runId: string, scenario: string, baseWorld?: BaseWorld) {
  const events: StreamEvent[] = [];
  let seq = 0;
  const push = (type: string, data: unknown, at: { step?: number; v?: number; dp?: string | null; agent?: AgentId; round?: number } = {}) => {
    const dp = at.dp === undefined ? null : at.dp;
    events.push({
      schema_version: "1",
      run_id: runId,
      mode: "preview",
      seq: ++seq,
      type,
      step: at.step ?? 0,
      state_version: at.v ?? 0,
      dp_id: dp,
      trace_id: [runId, dp, at.round && `r${at.round}`, at.agent].filter(Boolean).join("/"),
      data,
    });
  };
  const snapshot = (step: number, v: number, status: Snapshot["negotiation_status"], moved = false): Snapshot => ({
    schema_version: "1",
    run_id: runId,
    mode: "live",
    last_seq: seq,
    world: world(runId, scenario, step, v, moved, baseWorld),
    evidence_holders: { "E-LOG-01": ["LOG"], "E-LOG-02": ["LOG"], "E-FIRE-02": ["FIRE"] },
    dp_id: null,
    negotiation_status: status,
    committed_plan: null,
    escalation: null,
    targets: null,
    label: "Synthetic simulation",
  });
  const message = (sender: AgentId, type: MessageType, dp: string, v: number, round: number, target: Plan | null, rationale: string, extra: { objection?: Objection; evidence?: string[]; step?: number } = {}): AgentMessage => ({
    message_type: type,
    recipients: [],
    plan: null,
    parent_plan_id: null,
    target_plan_id: target?.plan_id ?? null,
    target_plan_hash: target?.plan_hash ?? null,
    objection: extra.objection ?? null,
    evidence_ids: extra.evidence ?? [],
    caused_by: [],
    requested_evidence_id: null,
    requested_topic: null,
    shared_evidence_ids: [],
    reason: null,
    blocking: [],
    rationale,
    schema_version: "1",
    message_id: `${dp}:r${round}:${sender}:0`,
    sender,
    run_id: runId,
    scenario_id: scenario,
    dp_id: dp,
    state_version: v,
    round,
    ts: "2026-10-10T18:30:00.000Z",
    step: extra.step ?? 0,
    proposal_id: null,
    plan_hash: null,
    status: "delivered",
    drop_reason: null,
  });
  const plan = (id: string, hash: string, proposer: AgentId, dp: string, v: number, evidence: string[] = []): Plan => ({
    schema_version: "1",
    plan_id: `${dp}:${id}`,
    plan_hash: hash,
    proposer,
    parent_plan_id: null,
    run_id: runId,
    dp_id: dp,
    state_version: v,
    assignments: [],
    evidence_ids: evidence,
    state: "EVALUATED",
    evaluation_ids: [`ev-${hash}-authoritative-v${v}`],
    tradeoffs: [],
    expected_shelter_use: {},
  });
  const evaluation = (p: Plan, assisted: number, fire: number, violations: Evaluation["violations"] = []): Evaluation => ({
    schema_version: "1",
    evaluation_id: `ev-${p.plan_hash}-authoritative-v${p.state_version}`,
    plan_hash: p.plan_hash,
    basis: "authoritative",
    kind: "forecast",
    run_id: runId,
    state_version: p.state_version,
    from_step: 0,
    horizon: 60,
    seed: 1,
    valid: violations.length === 0,
    violations,
    metrics: violations.length ? null : { ...zeroMetrics, assisted_completion: assisted, assisted_sheltered: Math.round(110 * assisted), fire_extent: fire },
    target_checks: [],
    leg_timing: [],
    trace_ref: null,
    sim_ms: 0,
  });
  const commit = (p: Plan, step: number): Commit => ({
    schema_version: "1",
    run_id: runId,
    dp_id: p.dp_id,
    plan_hash: p.plan_hash,
    plan_id: p.plan_id,
    state_version_before: p.state_version,
    state_version_after: p.state_version + 1,
    acceptances: [],
    ordering_rule: "first_proposed_seq",
    authority: "unanimous",
    authoritative_evaluation_id: `ev-${p.plan_hash}-authoritative-v${p.state_version}`,
    ts: "2026-10-10T18:30:30.000Z",
    step,
  });

  // dp-1: conflict over V1, Logistics shares the R2 blockage, all three accept P3.
  push("run.reset", { scenario_id: scenario, seed: 1 });
  push("state.snapshot", snapshot(0, 0, "idle"));
  const d1 = { dp: "dp-1", v: 1 };
  push("negotiation.started", { dp_id: "dp-1" }, d1);
  for (const agent of ["EVAC", "FIRE", "LOG"] as AgentId[]) push("agent.turn", { agent, status: "submitted" }, { ...d1, agent, round: 1 });
  const p1 = plan("P1", "5c1e9a0b7d2f", "EVAC", "dp-1", 1);
  const p2 = plan("P2", "7a42d0c19e63", "FIRE", "dp-1", 1);
  push("plan.proposed", p1, { ...d1, agent: "EVAC", round: 1 });
  push("evaluation.created", evaluation(p1, 0.71, 24), d1);
  push("plan.proposed", p2, { ...d1, agent: "FIRE", round: 1 });
  push("evaluation.created", evaluation(p2, 0.52, 18), d1);
  for (const agent of ["EVAC", "FIRE", "LOG"] as AgentId[]) push("agent.turn", { agent, status: "submitted" }, { ...d1, agent, round: 1 });
  push("message.delivered", message("LOG", "CHALLENGE", "dp-1", 1, 2, p1, "P1 sends V1 over R2, which is blocked. No valid arrival at Pine Ridge.", { objection: { kind: "infeasible", metric: null, evaluation_id: null, proposed_amendment: "Route V1 via R3 and R4 instead of R2" }, evidence: ["E-LOG-01"] }), { ...d1, agent: "LOG", round: 2 });
  push("message.delivered", message("EVAC", "CHALLENGE", "dp-1", 1, 2, p2, "P2 leaves Pine Ridge's assisted residents waiting past step 30.", { objection: { kind: "target_unmet", metric: "assisted_completion", evaluation_id: null, proposed_amendment: "Give V1 two Pine Ridge trips first" } }), { ...d1, agent: "EVAC", round: 2 });
  push("plan.state", { plan_hash: p1.plan_hash, state: "CHALLENGED" }, d1);
  const p3 = plan("P3", "9f03c2d4e1aa", "LOG", "dp-1", 1, ["E-LOG-01"]);
  push("plan.proposed", p3, { ...d1, agent: "LOG", round: 2 });
  push("evaluation.created", evaluation(p3, 0.88, 21), d1);
  push("plan.state", { plan_hash: p1.plan_hash, state: "SUPERSEDED" }, d1);
  push("message.delivered", message("EVAC", "ACCEPT", "dp-1", 1, 3, p3, "P3 reaches Pine Ridge via R3/R4 and meets our floor."), { ...d1, agent: "EVAC", round: 3 });
  push("message.delivered", message("FIRE", "ACCEPT", "dp-1", 1, 3, p3, "C3 still holds the east line under P3."), { ...d1, agent: "FIRE", round: 3 });
  push("plan.committed", commit(p3, 0), { dp: "dp-1", v: 2 });
  push("plan.state", { plan_hash: p3.plan_hash, state: "COMMITTED" }, { dp: "dp-1", v: 2 });
  push("plan.state", { plan_hash: p2.plan_hash, state: "SUPERSEDED" }, { dp: "dp-1", v: 2 });
  push("state.snapshot", snapshot(15, 2, "committed", true), { step: 15, v: 2, dp: "dp-1" });
  return { events, push, plan, evaluation, message, snapshot };
}

export function normalFlow(runId: string, scenario: string, baseWorld?: BaseWorld): StreamEvent[] {
  return flow(runId, scenario, baseWorld).events;
}

// Adds a wind shift + road closure at step 15, a second negotiation and an escalation.
export function disruptionFlow(runId: string, scenario: string, baseWorld?: BaseWorld): StreamEvent[] {
  const { events, push, plan, evaluation, message, snapshot } = flow(runId, scenario, baseWorld);
  push("event.applied", { event_id: "EV-1", step: 15, kind: "road_status", target: "R3", value: "CLOSED_HARD", public: true }, { step: 15, v: 3, dp: "dp-1" });
  const d2 = { step: 15, v: 3, dp: "dp-2" };
  push("negotiation.started", { dp_id: "dp-2" }, d2);
  const p1 = plan("P1", "b22ce0000001", "FIRE", "dp-2", 3);
  push("plan.proposed", p1, { ...d2, agent: "FIRE", round: 1 });
  push("evaluation.created", evaluation(p1, 0.64, 19), d2);
  push("message.delivered", message("EVAC", "CHALLENGE", "dp-2", 3, 2, p1, "P1 misses our assisted-evacuation floor now that R3 is closed.", { objection: { kind: "target_unmet", metric: "assisted_completion", evaluation_id: null, proposed_amendment: "Send B2 to Pine Ridge first" }, step: 15 }), { ...d2, agent: "EVAC", round: 2 });
  const p2 = plan("P2", "b22ce0000002", "EVAC", "dp-2", 3);
  push("plan.proposed", p2, { ...d2, agent: "EVAC", round: 2 });
  push("evaluation.created", evaluation(p2, 0, 0, [{ code: "ROAD_CLOSED", assignment_order: 1, resource_id: "B2", road_id: "R3", detail: "R3 is closed" }]), d2);
  push("message.delivered", message("LOG", "CHALLENGE", "dp-2", 3, 3, p2, "P2 routes B2 over R3, closed since step 15.", { objection: { kind: "infeasible", metric: null, evaluation_id: null, proposed_amendment: null }, step: 15 }), { ...d2, agent: "LOG", round: 3 });
  push("agent.turn", { agent: "FIRE", status: "degraded" }, { ...d2, agent: "FIRE", round: 4 });
  push("plan.state", { plan_hash: p1.plan_hash, state: "ESCALATED" }, d2);
  const escalation: EscalationPackage = {
    schema_version: "1",
    run_id: events[0].run_id ?? "",
    dp_id: "dp-2",
    state_version: 3,
    trigger: "ROUNDS_EXHAUSTED",
    candidates: [p1.plan_hash],
    candidate_checks: {},
    unmet_targets: { EVAC: ["assisted_completion"], FIRE: [], LOG: [] },
    open_objections: ["dp-2:r2:EVAC:0"],
    blocking_constraints: ["R3 CLOSED_HARD"],
    fallback_plan_hash: p1.plan_hash,
  };
  push("escalation.opened", escalation, d2);
  push("state.snapshot", { ...snapshot(15, 3, "escalated", true), escalation }, d2);
  return events;
}
