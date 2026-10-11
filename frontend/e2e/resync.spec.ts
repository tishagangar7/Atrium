import { expect, test } from "@playwright/test";

test("PRD §8.4: snapshot.required fetches the new run and clears old activity", async ({
  page,
}) => {
  let states = 0;
  let streams = 0;
  const snapshot = (run: string) => ({
    schema_version: "1",
    run_id: run,
    mode: "live",
    last_seq: 1,
    negotiation_status: "idle",
    world: { scenario_id: "normal", step: 0, state_version: 0 },
  });
  await page.route("**/api/health", (route) =>
    route.fulfill({
      json: { ok: true, model_available: false, provider: null, mode: "live" },
    }),
  );
  await page.route("**/api/state", (route) =>
    route.fulfill({ json: snapshot(++states === 1 ? "old-run" : "new-run") }),
  );
  await page.route("**/api/events/stream", (route) => {
    streams++;
    const event = {
      run_id: "new-run",
      dp_id: null,
      trace_id: "new-run/-/-/-",
      mode: "live",
      seq: streams === 1 ? 0 : 2,
      step: 0,
      state_version: 0,
      type: streams === 1 ? "snapshot.required" : "negotiation.started",
      data: {},
    };
    return route.fulfill({
      contentType: "text/event-stream",
      body: `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`,
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Connect simulator" }).click();
  await expect(page.getByRole("status")).toContainText("Incident refreshed");
  await expect(page.locator(".mode-label")).toHaveText("BACKEND PREVIEW");
  await expect(page.locator(".stage-caption")).toHaveText("new-run");
  await expect(page.locator(".event-list li")).toHaveCount(1);
  expect(states).toBe(2);
});
