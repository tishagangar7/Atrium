import { expect, test, type Page } from "@playwright/test";

// D4: negotiation, disruptions and escalation against mocked WS-C routes (PRD §8.2, §9.7).
const RUN = "run-n";
const snapshot = {
  schema_version: "1",
  run_id: RUN,
  mode: "live",
  last_seq: 2,
  negotiation_status: "idle",
  label: "Synthetic simulation",
  evidence_holders: {},
  dp_id: null,
  committed_plan: null,
  escalation: null,
  world: { scenario_id: "normal", step: 0, state_version: 1, resources: {}, shelters: {}, zones: {} },
};
const envelope = (seq: number, type: string, data: unknown, extra: Record<string, unknown> = {}) => ({
  schema_version: "1",
  run_id: RUN,
  dp_id: "dp-1",
  trace_id: `${RUN}/dp-1`,
  seq,
  step: 0,
  state_version: 4,
  mode: "live",
  type,
  data,
  ...extra,
});
const plan = {
  schema_version: "1",
  plan_id: "dp-1:P1",
  plan_hash: "aaaabbbbcccc",
  proposer: "LOG",
  parent_plan_id: null,
  run_id: RUN,
  dp_id: "dp-1",
  state_version: 4,
  assignments: [],
  evidence_ids: [],
  state: "EVALUATED",
  evaluation_ids: [],
  tradeoffs: [],
  expected_shelter_use: {},
};
const escalation = {
  schema_version: "1",
  run_id: RUN,
  dp_id: "dp-1",
  state_version: 4,
  trigger: "ROUNDS_EXHAUSTED",
  candidates: ["aaaabbbbcccc"],
  candidate_checks: {},
  unmet_targets: { EVAC: ["assisted_completion"], FIRE: [], LOG: [] },
  open_objections: [],
  blocking_constraints: ["R3 CLOSED_HARD"],
  fallback_plan_hash: "f0f0f0f0f0f0",
};

async function backend(page: Page, opts: { stream?: unknown[]; negotiateStatus?: number } = {}) {
  const posts: Record<string, unknown[]> = {};
  const record = (name: string) => async (route: import("@playwright/test").Route) => {
    (posts[name] ??= []).push(route.request().postDataJSON());
    if (name === "negotiate" && opts.negotiateStatus === 503)
      return route.fulfill({ status: 503, json: { error: { code: "MODEL_UNAVAILABLE", message: "no provider", retryable: true } } });
    if (name === "negotiate") return route.fulfill({ status: 202, json: { dp_id: "dp-1" } });
    if (name === "inject") return route.fulfill({ json: { state_version: 5, applied_events: ["compound_failure"] } });
    return route.fulfill({ json: { commit: {} } });
  };
  await page.route("**/api/health", (route) =>
    route.fulfill({ json: { ok: true, model_available: false, provider: null, mode: "live" } }),
  );
  await page.route("**/api/state", (route) => route.fulfill({ json: snapshot }));
  await page.route("**/api/negotiate", record("negotiate"));
  await page.route("**/api/events/inject", record("inject"));
  await page.route("**/api/escalations/*/resolve", record("resolve"));
  await page.route("**/api/events/stream", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body:
        "retry: 300\n\n" +
        (opts.stream ?? [])
          .map((item) => {
            const e = item as { type: string; seq: number };
            return `event: ${e.type}\nid: ${RUN}:${e.seq}\ndata: ${JSON.stringify(item)}\n\n`;
          })
          .join(""),
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Connect simulator" }).click();
  await expect(page.locator(".stage-caption")).toHaveText(RUN);
  return posts;
}

test("D4: Start negotiation sends the guard; agents show working and TEST PROVIDER is labeled", async ({ page }) => {
  const posts = await backend(page, {
    stream: [
      envelope(3, "negotiation.started", { dp_id: "dp-1", state_version: 4 }),
      envelope(4, "agent.turn", { agent: "EVAC", status: "submitted", model_calls: 1, latency_ms: 900 }),
    ],
  });
  await expect(page.getByText("Working…").first()).toBeVisible();
  await expect(page.locator(".mode-label")).toHaveText("TEST PROVIDER");
  await expect(page.getByRole("button", { name: "Cancel negotiation" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Step", exact: true })).toBeDisabled();
  await expect(page.locator(".incident-summary")).toContainText("Round 1 of 4");
  expect(posts.negotiate).toBeUndefined();
});

test("D4: Start negotiation posts run_id and expected_state_version", async ({ page }) => {
  const posts = await backend(page);
  await page.getByRole("button", { name: "Start negotiation" }).click();
  await expect(page.getByRole("status")).toContainText("Negotiation dp-1 started");
  expect(posts.negotiate[0]).toMatchObject({ run_id: RUN, expected_state_version: 1 });
});

test("D4: model unavailable shows a clear notice", async ({ page }) => {
  await backend(page, { negotiateStatus: 503 });
  await page.getByRole("button", { name: "Start negotiation" }).click();
  await expect(page.getByRole("status")).toContainText("Model unavailable");
});

test("D4: disruption uses the negotiation session's version from the stream", async ({ page }) => {
  const posts = await backend(page, {
    stream: [envelope(3, "plan.committed", { plan_id: "dp-1:P1", plan_hash: "aaaabbbbcccc", authority: "unanimous" })],
  });
  await expect(page.getByText("All three accepted P1 – committed")).toBeVisible();
  await page.getByRole("button", { name: "Compound failure" }).click();
  await expect(page.getByRole("status")).toContainText("Conditions changed");
  expect(posts.inject[0]).toMatchObject({ run_id: RUN, expected_state_version: 4, event: "compound_failure" });
});

test("PRD §9.7: escalation lists only package candidates and forwards the human's choice", async ({ page }) => {
  const posts = await backend(page, {
    stream: [
      envelope(3, "negotiation.started", { dp_id: "dp-1" }),
      envelope(4, "plan.proposed", plan),
      envelope(5, "escalation.opened", escalation),
    ],
  });
  const panel = page.locator(".escalation");
  await expect(panel).toContainText("A human decision is needed");
  await expect(panel).toContainText("R3 CLOSED_HARD");
  await expect(panel).toContainText("You cannot add vehicles or open closed roads");
  await expect(panel.getByRole("button", { name: "Choose this plan" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Start negotiation" })).toBeDisabled();
  await panel.getByRole("button", { name: "Choose this plan" }).click();
  await expect(page.getByRole("status")).toContainText("HUMAN DECISION");
  expect(posts.resolve[0]).toMatchObject({
    run_id: RUN,
    choice: "candidate",
    plan_hash: "aaaabbbbcccc",
    expected_state_version: 4,
  });
  await page.screenshot({ path: "test-results/d4-escalation.png", fullPage: true });
});
