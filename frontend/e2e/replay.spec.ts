import { expect, test } from "@playwright/test";

// D5: labeled replay of a saved run (PRD §8.2 POST /replay, §9.4 Replay, §13.3).
test("D5: replay a saved run from the start, labeled, with commands disabled", async ({ page }) => {
  let replayed = false;
  const posts: unknown[] = [];
  const live = { schema_version: "1", run_id: "run-live", mode: "live", last_seq: 2, negotiation_status: "idle", world: { scenario_id: "normal", step: 0, state_version: 0 } };
  const replay = { ...live, run_id: "replay-of-run-old", mode: "replay", last_seq: 9, negotiation_status: "committed", world: { scenario_id: "normal", step: 15, state_version: 3 } };
  await page.route("**/api/health", (route) =>
    route.fulfill({ json: { ok: true, model_available: false, provider: null, mode: "live" } }),
  );
  await page.route("**/api/state", (route) => route.fulfill({ json: replayed ? replay : live }));
  await page.route("**/api/runs", (route) =>
    route.fulfill({
      json: [
        { run_id: "replay-of-x", preset: "normal", created_ts: "2026-10-10T09:00:00Z" },
        { run_id: "run-old", preset: "compound_failure", seed: 1, method: "rescuemesh", mode: "live", created_ts: "2026-10-10T08:00:00Z", final_state_hash: null },
      ],
    }),
  );
  await page.route("**/api/replay/*", (route) => {
    posts.push({ url: route.request().url(), body: route.request().postDataJSON() });
    replayed = true;
    return route.fulfill({ json: { run_id: "replay-of-run-old", mode: "replay" } });
  });
  const recorded = {
    schema_version: "1",
    run_id: "replay-of-run-old",
    dp_id: "dp-1",
    trace_id: "replay-of-run-old/dp-1",
    seq: 1,
    step: 0,
    state_version: 1,
    mode: "replay",
    type: "negotiation.started",
    data: { dp_id: "dp-1" },
  };
  await page.route("**/api/events/stream", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: replayed
        ? `retry: 300\n\nevent: ${recorded.type}\nid: ${recorded.run_id}:1\ndata: ${JSON.stringify(recorded)}\n\n`
        : "retry: 300\n\n",
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Connect simulator" }).click();
  const picker = page.getByLabel("Replay a run");
  await expect(picker.locator("option")).toHaveCount(1); // replay-of-* excluded
  await expect(picker).toContainText("Compound failure");
  await page.getByLabel("Replay speed").selectOption("2");
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect(page.locator(".mode-label")).toHaveText("REPLAY");
  await expect(page.locator(".replay-source")).toContainText("compound_failure");
  await expect(page.locator(".watermark")).toBeVisible();
  await expect(page.getByText("Negotiation dp-1 started")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start negotiation" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Step", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Reset scenario" })).toBeEnabled();
  expect(posts[0]).toMatchObject({ body: { speed: 2 } });
  expect(String((posts[0] as { url: string }).url)).toContain("/replay/run-old");
  await page.screenshot({ path: "test-results/d5-replay.png", fullPage: true });
});
