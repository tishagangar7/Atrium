import type {
  AgentId,
  AgentMessage,
  Commit,
  EscalationPackage,
  Evaluation,
  Plan,
  Snapshot,
} from "./types";
import type { StreamEvent } from "./components/shell-data";

// Display model built from envelopes that already passed reduceEnvelope (PRD §8.4).
// It never decides anything: commits, staleness and escalation come from the stream.

// Values streamed by WS-B's router on agent.turn (backend/app/agents/actor.py).
export type TurnStatus =
  | "working" // local: negotiation started, no agent.turn yet this round
  | "submitted"
  | "silent"
  | "degraded"
  | "failed"
  | "late"
  | "cancelled";

export interface IncidentModel {
  snapshot: Snapshot | null;
  messages: AgentMessage[];
  plans: Record<string, Plan>;
  evaluations: Record<string, Evaluation>;
  commits: Commit[];
  turns: Partial<Record<AgentId, TurnStatus>>;
  escalation: EscalationPackage | null;
  /** True after event.applied until the next negotiation starts (PRD §9.4 Stale). */
  stale: boolean;
  dpId: string | null;
  round: number | null;
  /** Latest state_version seen on negotiation envelopes; /events/inject is guarded by it. */
  negotiationVersion: number | null;
  /** commits.length when the latest event.applied arrived (for the before/after view). */
  commitsAtEvent: number | null;
}

// Envelopes passed shape checks, but data may still be partial; never let it crash the screen.
function isMessage(value: unknown): value is AgentMessage {
  const message = value as AgentMessage | null;
  return (
    !!message &&
    typeof message.sender === "string" &&
    typeof message.message_type === "string" &&
    Array.isArray(message.evidence_ids)
  );
}

export const emptyIncident: IncidentModel = {
  snapshot: null,
  messages: [],
  plans: {},
  evaluations: {},
  commits: [],
  turns: {},
  escalation: null,
  stale: false,
  dpId: null,
  round: null,
  negotiationVersion: null,
  commitsAtEvent: null,
};

const negotiationTypes = new Set([
  "negotiation.started",
  "negotiation.round",
  "agent.turn",
  "message.delivered",
  "plan.proposed",
  "plan.committed",
  "escalation.opened",
  "event.applied",
  "human.decision",
]);

const openStates = new Set<Plan["state"]>([
  "PROPOSED",
  "EVALUATED",
  "CHALLENGED",
  "PARTIALLY_ACCEPTED",
  "UNANIMOUS",
]);
export const inactiveStates = new Set<Plan["state"]>([
  "STALE",
  "SUPERSEDED",
  "WITHDRAWN",
  "REJECTED_AT_COMMIT",
  "ESCALATED",
]);

export function reduceIncident(
  previous: IncidentModel,
  event: StreamEvent,
): IncidentModel {
  const model = negotiationTypes.has(event.type)
    ? { ...previous, negotiationVersion: event.state_version }
    : previous;
  switch (event.type) {
    case "run.reset":
      return { ...emptyIncident };
    case "state.snapshot": {
      const snapshot = event.data as Snapshot;
      return {
        ...model,
        snapshot,
        escalation: snapshot.escalation ?? model.escalation,
      };
    }
    case "negotiation.started":
      return {
        ...model,
        stale: false,
        escalation: null,
        turns: { EVAC: "working", FIRE: "working", LOG: "working" },
        dpId: event.dp_id,
        round: 1,
      };
    case "negotiation.round": {
      const round = (event.data as { round?: number } | null)?.round;
      return {
        ...model,
        round: typeof round === "number" ? round : model.round,
        turns: Object.fromEntries(
          Object.entries(model.turns).map(([agent, status]) => [
            agent,
            status === "degraded" ? status : "working",
          ]),
        ),
      };
    }
    case "negotiation.cancelled":
      return { ...model, turns: {}, round: null };
    case "agent.turn": {
      const { agent, status } = (event.data ?? {}) as {
        agent?: AgentId;
        status?: TurnStatus;
      };
      if (!agent || !status) return model;
      return { ...model, turns: { ...model.turns, [agent]: status } };
    }
    case "message.delivered":
    case "message.dropped":
      if (!isMessage(event.data)) return model;
      return {
        ...model,
        messages: [...model.messages, event.data as AgentMessage],
      };
    case "plan.proposed": {
      const plan = event.data as Plan;
      if (typeof plan?.plan_hash !== "string" || typeof plan.plan_id !== "string")
        return model;
      return { ...model, plans: { ...model.plans, [plan.plan_hash]: plan } };
    }
    case "plan.state": {
      const { plan_hash, state } = event.data as {
        plan_hash: string;
        state: Plan["state"];
      };
      const plan = model.plans[plan_hash];
      if (!plan) return model;
      return {
        ...model,
        plans: { ...model.plans, [plan_hash]: { ...plan, state } },
      };
    }
    case "evaluation.created": {
      const evaluation = event.data as Evaluation;
      if (typeof evaluation?.evaluation_id !== "string") return model;
      return {
        ...model,
        evaluations: {
          ...model.evaluations,
          [evaluation.evaluation_id]: evaluation,
        },
      };
    }
    case "plan.committed":
      if (typeof (event.data as Commit)?.plan_hash !== "string") return model;
      return { ...model, commits: [...model.commits, event.data as Commit] };
    case "event.applied":
      // Invariant 6: new evidence voids open plans. Display only; plan.state from the server wins.
      return {
        ...model,
        stale: true,
        commitsAtEvent: model.commits.length,
        plans: Object.fromEntries(
          Object.entries(model.plans).map(([hash, plan]) => [
            hash,
            openStates.has(plan.state)
              ? { ...plan, state: "STALE" as const }
              : plan,
          ]),
        ),
      };
    case "escalation.opened":
      // Rounds are over: drop "working", keep facts such as degraded.
      return {
        ...model,
        escalation: event.data as EscalationPackage,
        turns: Object.fromEntries(
          Object.entries(model.turns).filter(([, status]) => status !== "working"),
        ),
      };
    case "human.decision":
      return { ...model, escalation: null };
    default:
      return model;
  }
}

/** Accepting agents per plan hash: the proposer, plus ACCEPT messages at the plan's own state_version. */
export function acceptances(model: IncidentModel): Record<string, AgentId[]> {
  const out: Record<string, Set<AgentId>> = {};
  const add = (hash: string, agent: AgentId) =>
    (out[hash] ??= new Set()).add(agent);
  for (const plan of Object.values(model.plans))
    add(plan.plan_hash, plan.proposer);
  for (const message of model.messages) {
    if (message.message_type !== "ACCEPT" || !message.target_plan_hash)
      continue;
    if (
      model.plans[message.target_plan_hash]?.state_version !==
      message.state_version
    )
      continue;
    add(message.target_plan_hash, message.sender);
  }
  return Object.fromEntries(
    Object.entries(out).map(([hash, set]) => [hash, [...set]]),
  );
}

/** Latest simulator (authoritative) forecast for a plan. Agent-view forecasts are never headline numbers. */
export function authoritativeEval(
  model: IncidentModel,
  planHash: string,
): Evaluation | null {
  let best: Evaluation | null = null;
  for (const evaluation of Object.values(model.evaluations)) {
    if (
      evaluation.plan_hash !== planHash ||
      evaluation.basis !== "authoritative"
    )
      continue;
    if (!best || evaluation.state_version > best.state_version)
      best = evaluation;
  }
  return best;
}

/** Commit just before the latest disruption and the first one after it (D5 comparison). */
export function comparison(model: IncidentModel) {
  const at = model.commitsAtEvent;
  if (at === null || at === 0 || model.commits.length <= at) return null;
  const before = model.commits[at - 1];
  const after = model.commits[at];
  return {
    before: { commit: before, evaluation: authoritativeEval(model, before.plan_hash) },
    after: { commit: after, evaluation: authoritativeEval(model, after.plan_hash) },
  };
}

export const agentNames: Record<AgentId, string> = {
  EVAC: "Evacuation",
  FIRE: "Fire Operations",
  LOG: "Logistics",
};

export const planLabel = (plan: Plan, currentDp: string | null) =>
  plan.dp_id === currentDp
    ? (plan.plan_id.split(":").at(-1) ?? plan.plan_id)
    : plan.plan_id;

/** One-line status for an agent's collapsed row. */
export function agentStatus(model: IncidentModel, agent: AgentId): string {
  const turn = model.turns[agent];
  if (turn === "degraded") return "Unavailable – not counted";
  if (turn === "working") return "Working…";
  if (turn === "late" || turn === "failed") return "Missed the deadline";
  const accepted = acceptances(model);
  const current = Object.values(model.plans).filter(
    (plan) => plan.dp_id === model.dpId && !inactiveStates.has(plan.state),
  );
  const accepting = current.findLast((plan) =>
    accepted[plan.plan_hash]?.includes(agent),
  );
  const last = model.messages.findLast(
    (message) => message.sender === agent && message.dp_id === model.dpId,
  );
  if (last?.message_type === "CHALLENGE" && last.target_plan_id)
    return `Objects to ${last.target_plan_id.split(":").at(-1)}`;
  if (accepting) return `Accepts ${planLabel(accepting, model.dpId)}`;
  if (turn === "silent") return "Silent this round";
  return last ? "Waiting" : "No messages yet";
}

export type Tone = "neutral" | "agree" | "object" | "alert";

/** Human-readable line for the Activity list. */
export function describe(event: StreamEvent): {
  title: string;
  tone: Tone;
} {
  const data = (event.data ?? {}) as Record<string, unknown>;
  switch (event.type) {
    case "run.reset":
      return { title: "Scenario loaded", tone: "neutral" };
    case "state.snapshot":
      return { title: "Incident state updated", tone: "neutral" };
    case "negotiation.started":
      return { title: `Negotiation ${event.dp_id} started`, tone: "neutral" };
    case "plan.proposed": {
      const plan = data as unknown as Plan;
      if (typeof plan.plan_id !== "string")
        return { title: "A plan was proposed", tone: "neutral" };
      return {
        title: `${agentNames[plan.proposer]} proposed ${plan.plan_id.split(":").at(-1)}`,
        tone: "neutral",
      };
    }
    case "message.delivered":
    case "message.dropped": {
      if (!isMessage(data)) return { title: "Message received", tone: "neutral" };
      const message = data;
      const who = agentNames[message.sender];
      const target = message.target_plan_id?.split(":").at(-1) ?? "a plan";
      const cites = message.evidence_ids.length
        ? ` · cites ${message.evidence_ids.join(", ")}`
        : "";
      const verb: Record<string, string> = {
        ACCEPT: `accepted ${target}`,
        CHALLENGE: `challenged ${target}`,
        SHARE_EVIDENCE: "shared evidence",
        REQUEST_EVIDENCE: "requested evidence",
        WITHDRAW: `withdrew from ${target}`,
        ESCALATE: "asked to escalate",
        PROPOSE: "proposed a plan",
        COUNTERPROPOSE: "counter-proposed",
      };
      const dropped = event.type === "message.dropped" ? " (dropped)" : "";
      return {
        title: `${who} ${verb[message.message_type] ?? message.message_type.toLowerCase()}${cites}${dropped}`,
        tone:
          message.message_type === "ACCEPT"
            ? "agree"
            : message.message_type === "CHALLENGE"
              ? "object"
              : "neutral",
      };
    }
    case "evaluation.created":
      return { title: "Simulator tested a plan", tone: "neutral" };
    case "plan.committed": {
      const commit = data as unknown as Commit;
      const label = String(commit.plan_id ?? "a plan").split(":").at(-1);
      if (commit.authority === "human_choice")
        return { title: `HUMAN DECISION – committed ${label}`, tone: "alert" };
      if (commit.authority === "auto_fallback")
        return { title: `Fallback ${label} applied automatically`, tone: "alert" };
      return { title: `All three accepted ${label} – committed`, tone: "agree" };
    }
    case "human.decision":
      return {
        title: `HUMAN DECISION – chose ${data.choice === "fallback" ? "the fallback plan" : data.choice === "relax" ? "to relax targets" : "a candidate plan"}`,
        tone: "alert",
      };
    case "target.revised":
      return { title: `Target relaxed: ${String(data.metric ?? "a target")}`, tone: "neutral" };
    case "negotiation.cancelled":
      return { title: "Negotiation cancelled", tone: "neutral" };
    case "event.applied":
      return { title: "Conditions changed – earlier plans are stale", tone: "alert" };
    case "escalation.opened":
      return { title: "Escalated to a human decision", tone: "alert" };
    case "agent.turn":
      return {
        title: `${agentNames[data.agent as AgentId] ?? "Agent"} ${data.status === "degraded" ? "became unavailable" : data.status === "submitted" ? "responded" : String(data.status)}`,
        tone: data.status === "degraded" ? "alert" : "neutral",
      };
    default:
      return { title: event.type, tone: "neutral" };
  }
}

/** Activity shows decisions, not every bookkeeping envelope. */
export const activityTypes = new Set([
  "run.reset",
  "negotiation.started",
  "plan.proposed",
  "message.delivered",
  "message.dropped",
  "plan.committed",
  "event.applied",
  "escalation.opened",
  "human.decision",
  "negotiation.cancelled",
  "target.revised",
  "error",
]);
