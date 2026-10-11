import { expect, test, type Page } from "@playwright/test";

// D3: backend-mode Reset / Step and snapshot reconciliation (PRD §8.1, §8.4), with mocked routes.
const snapshot = (run: string, step = 0, version = 0, lastSeq = 2) => ({
  schema_version: "1",
  run_id: run,
  mode: "live",
  last_seq: lastSeq,
  negotiation_status: "idle",
  label: "Synthetic simulation",
  evidence_holders: {},
  dp_id: null,
  committed_plan: null,
  escalation: null,
  world: {
    scenario_id: "normal",
    step,
    state_version: version,
    resources: {},
    shelters: {
      SS: { id: "SS", name: "Shelter South", cell: "c6_5", capacity: 350, background: 320, arrivals: 0 },
    },
    zones: {},
  },
});

async function mockBackend(page: Page, opts: { stepStatus?: number } = {}) {
  const calls = { reset: 0, step: [] as unknown[], state: 0 };
  let run = "run-a";
  await page.route("**/api/health", (route) =>
    route.fulfill({ json: { ok: true, model_available: false, provider: null, mode: "live" } }),
  );
  await page.route("**/api/state", (route) => {
    calls.state++;
    return route.fulfill({ json: snapshot(run, 7, 3, 9) });
  });
  await page.route("**/api/scenarios/*/reset", (route) => {
    calls.reset++;
    run = "run-b";
    return route.fulfill({ json: { run_id: run, state_version: 0, snapshot: snapshot(run) } });
  });
  await page.route("**/api/simulation/step", (route) => {
    calls.step.push(route.request().postDataJSON());
    if (opts.stepStatus === 409)
      return route.fulfill({
        status: 409,
        json: { error: { code: "STATE_VERSION_MISMATCH", message: "expected 0 but current is 3", retryable: true } },
      });
    return route.fulfill({ json: { step: 1, state_version: 0, paused: true } });
  });
  await page.route("**/api/events/stream", (route) =>
    route.fulfill({ contentType: "text/event-stream", body: ": idle\n\n" }),
  );
  return calls;
}

test("D3: Reset starts a new run and continues from its snapshot", async ({ page }) => {
  const calls = await mockBackend(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Connect simulator" }).click();
  await expect(page.locator(".stage-caption")).toHaveText("run-a");
  await page.getByRole("button", { name: "Reset scenario" }).click();
  await expect(page.locator(".stage-caption")).toHaveText("run-b");
  await expect(page.getByRole("status")).toContainText("New run started");
  expect(calls.reset).toBe(1);
  await page.getByRole("button", { name: "Resources", exact: true }).click();
  await expect(page.locator(".resource-grid")).toContainText("Shelter South");
  await expect(page.getByRole("button", { name: "Start negotiation" })).toBeEnabled();
});

test("PRD §8.1: Step sends the run id and expected state version", async ({ page }) => {
  const calls = await mockBackend(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Connect simulator" }).click();
  await page.getByRole("button", { name: "Reset scenario" }).click();
  await expect(page.locator(".stage-caption")).toHaveText("run-b");
  await page.getByRole("button", { name: "Step", exact: true }).click();
  await expect(page.locator(".incident-summary")).toContainText("1");
  expect(calls.step[0]).toMatchObject({ run_id: "run-b", expected_state_version: 0, steps: 1 });
});

test("PRD §8.1: a 409 state-version mismatch refreshes instead of failing", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const calls = await mockBackend(page, { stepStatus: 409 });
  await page.goto("/");
  await page.getByRole("button", { name: "Connect simulator" }).click();
  await expect(page.locator(".stage-caption")).toHaveText("run-a");
  const before = calls.state;
  await page.getByRole("button", { name: "Step", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("changed elsewhere");
  expect(calls.state).toBe(before + 1);
  await expect(page.locator(".incident-summary")).toContainText("v3");
  expect(errors).toEqual([]);
});
