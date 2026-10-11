import { expect, test } from "@playwright/test";
import {
  acceptances,
  agentStatus,
  authoritativeEval,
  comparison,
  describe as describeEvent,
  emptyIncident,
  reduceIncident,
} from "../src/incident";
import { disruptionFlow, normalFlow } from "../src/fixtures/preview";
import type { StreamEvent } from "../src/components/shell-data";
import type { AgentMessage, Evaluation } from "../src/types";

const run = (events: StreamEvent[]) => events.reduce(reduceIncident, emptyIncident);
const upTo = (events: StreamEvent[], type: string) =>
  run(events.slice(0, events.findIndex((event) => event.type === type) + 1));

test("normal fixture commits P3 with all three accepting", () => {
  const model = run(normalFlow("r", "normal"));
  expect(model.commits.at(-1)?.plan_id).toBe("dp-1:P3");
  expect(acceptances(model)["9f03c2d4e1aa"].sort()).toEqual(["EVAC", "FIRE", "LOG"]);
  expect(model.plans["9f03c2d4e1aa"].state).toBe("COMMITTED");
});

test("invariant 6: an ACCEPT at an old state_version is not counted", () => {
  const events = normalFlow("r", "normal");
  const accept = events.find(
    (event) => (event.data as AgentMessage).message_type === "ACCEPT",
  )!;
  const stale = {
    ...accept,
    seq: 999,
    data: { ...(accept.data as AgentMessage), sender: "FIRE", state_version: 0 },
  };
  const model = run([...events.slice(0, events.indexOf(accept)), stale]);
  expect(acceptances(model)["9f03c2d4e1aa"]).not.toContain("FIRE");
});

test("PRD §9.4: event.applied marks open plans stale and keeps the committed one", () => {
  const events = disruptionFlow("r", "compound_failure");
  const model = upTo(events, "event.applied");
  expect(model.stale).toBe(true);
  expect(model.plans["9f03c2d4e1aa"].state).toBe("COMMITTED");
  const withOpen = reduceIncident(upTo(events, "plan.proposed"), {
    ...events.find((event) => event.type === "event.applied")!,
  });
  expect(withOpen.plans["5c1e9a0b7d2f"].state).toBe("STALE");
});

test("next negotiation clears stale; escalation and degraded agent are kept", () => {
  const events = disruptionFlow("r", "compound_failure");
  const start = events.findIndex(
    (event) => event.type === "negotiation.started" && event.dp_id === "dp-2",
  );
  expect(run(events.slice(0, start + 1)).stale).toBe(false);
  const model = run(events);
  expect(model.escalation?.trigger).toBe("ROUNDS_EXHAUSTED");
  expect(agentStatus(model, "FIRE")).toBe("Unavailable – not counted");
});

test("invariant 3: headline metrics use the authoritative evaluation only", () => {
  const events = normalFlow("r", "normal");
  const authoritative = events.find((event) => event.type === "evaluation.created")!;
  const agentView = {
    ...authoritative,
    seq: 998,
    data: {
      ...(authoritative.data as Evaluation),
      evaluation_id: "ev-view",
      basis: "view_EVAC",
      state_version: 9,
    },
  };
  const model = run([...events, agentView]);
  const plan = (authoritative.data as Evaluation).plan_hash;
  expect(authoritativeEval(model, plan)?.basis).toBe("authoritative");
});

test("partial message data never crashes the model or the activity text", () => {
  const partial: StreamEvent = {
    run_id: "r",
    dp_id: null,
    trace_id: "r",
    seq: 1,
    step: 0,
    state_version: 0,
    mode: "live",
    type: "message.delivered",
    data: {},
  };
  expect(run([partial]).messages).toHaveLength(0);
  expect(describeEvent(partial).title).toBe("Message received");
});

test("D4: real agent.turn statuses and human-decision lines", () => {
  const base: StreamEvent = {
    run_id: "r",
    dp_id: "dp-1",
    trace_id: "r",
    seq: 1,
    step: 0,
    state_version: 2,
    mode: "live",
    type: "negotiation.started",
    data: { dp_id: "dp-1" },
  };
  let model = run([base]);
  expect(agentStatus(model, "FIRE")).toBe("Working…");
  model = reduceIncident(model, { ...base, seq: 2, type: "agent.turn", data: { agent: "FIRE", status: "late" } });
  expect(agentStatus(model, "FIRE")).toBe("Missed the deadline");
  expect(model.negotiationVersion).toBe(2);
  expect(
    describeEvent({ ...base, type: "plan.committed", data: { plan_id: "dp-1:P2", authority: "human_choice" } }).title,
  ).toBe("HUMAN DECISION – committed P2");
});

test("D5: comparison pairs the commit before a disruption with the first one after", () => {
  const events = disruptionFlow("r", "compound_failure");
  // The disruption flow escalates, so there is no commit after the event yet.
  expect(comparison(run(events))).toBeNull();
  const commit = events.find((event) => event.type === "plan.committed")!;
  const after = { ...commit, seq: 999, data: { ...(commit.data as object), plan_id: "dp-2:P9", plan_hash: "b22ce0000001" } };
  const pair = comparison(run([...events, after]));
  expect(pair?.before.commit.plan_id).toBe("dp-1:P3");
  expect(pair?.after.commit.plan_id).toBe("dp-2:P9");
  expect(pair?.after.evaluation?.basis).toBe("authoritative");
});
