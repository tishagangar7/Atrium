import { expect, test } from "@playwright/test";

test("AC-013 / AC-034: D1 preview stays labeled and exposes details on demand", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByText("Synthetic simulation", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("FIXTURE", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start negotiation" }),
  ).toBeDisabled();
  await expect(page.locator("details")).toHaveCount(3);
  await page.screenshot({
    path: "test-results/shell-desktop.png",
    fullPage: true,
  });
  await page.getByLabel("Scenario preset").selectOption("road_closure");
  await page
    .getByRole("button", { name: "Load preview", exact: true })
    .first()
    .click();
  await expect(
    page.getByText("Scenario loaded", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".incident-summary")).toContainText("Road closure");
  const viewEvent = page.getByRole("button", { name: "View event" }).last();
  await viewEvent.click();
  await expect(page.getByRole("dialog")).toContainText("run.reset");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(viewEvent).toBeFocused();
  await page.locator("summary").first().click();
  await expect(
    page.getByText("Fixture · not a live agent").first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Proposals", exact: true }).click();
  await expect(page).toHaveURL(/panel=proposals/);
  expect(errors).toEqual([]);
});

test("AC-035: compact and mobile layouts preserve keyboard access without overflow", async ({
  page,
}) => {
  for (const viewport of [
    { width: 1280, height: 720 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("link", { name: "Skip to incident" }),
    ).toBeFocused();
    await page.getByRole("button", { name: "How it works" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("button", { name: "How it works" }),
    ).toBeFocused();
    await page.screenshot({
      path: `test-results/shell-${viewport.width}.png`,
      fullPage: true,
    });
  }
});

test("connection failure retains the labeled preview and provides a retry path", async ({
  page,
}) => {
  await page.route("**/api/health", (route) =>
    route.fulfill({ status: 503, body: "Unavailable" }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Connect simulator" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Start the backend on port 8000, then retry.",
  );
  await expect(page.getByText("FIXTURE", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Connect simulator" }),
  ).toBeEnabled();
});

test("PRD §8.4: named SSE events reject duplicates and wrong-run envelopes", async ({
  page,
}) => {
  const snapshot = {
    schema_version: "1",
    run_id: "test-run",
    mode: "replay",
    last_seq: 1,
    negotiation_status: "idle",
    world: { scenario_id: "normal", step: 0, state_version: 0 },
  };
  await page.route("**/api/health", (route) =>
    route.fulfill({
      json: {
        ok: true,
        model_available: false,
        provider: "test",
        mode: "replay",
      },
    }),
  );
  await page.route("**/api/state", (route) =>
    route.fulfill({ json: snapshot }),
  );
  const envelope = {
    schema_version: "1",
    run_id: "test-run",
    dp_id: null,
    trace_id: "test-run/dp-1/r1/EVAC",
    seq: 2,
    step: 0,
    state_version: 0,
    mode: "replay",
    type: "message.delivered",
    data: { fixture: true },
  };
  const messages = [
    envelope,
    envelope,
    { ...envelope, run_id: "another-run", seq: 3, type: "plan.proposed" },
  ];
  await page.route("**/api/events/stream", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: messages
        .map(
          (item) =>
            `event: ${item.type}\nid: ${item.run_id}:${item.seq}\ndata: ${JSON.stringify(item)}\n\n`,
        )
        .join(""),
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Connect simulator" }).click();
  await expect(page.locator(".mode-label")).toHaveText("REPLAY");
  await expect(page.locator(".event-list li")).toHaveCount(1);
  await expect(page.locator(".event-list")).toContainText("Message received");
  await expect(page.locator(".event-list")).not.toContainText("plan.proposed");
  await expect(
    page.getByRole("button", { name: "Start negotiation" }),
  ).toBeDisabled();
  await expect(page.getByRole("button", { name: "Compound failure" })).toBeDisabled();
});

test("D2: disruption preview shows stale/escalation, proposals, resources and inspector", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByLabel("Scenario preset").selectOption("compound_failure");
  await page.getByRole("button", { name: "Load preview", exact: true }).first().click();
  await expect(page.locator(".escalation")).toContainText(
    "A human decision is needed",
    { timeout: 15000 },
  );
  await expect(page.locator(".escalation")).not.toContainText("agreed");
  await expect(page.getByRole("button", { name: "Use fallback" })).toBeDisabled();
  await expect(page.getByText("Unavailable – not counted")).toBeVisible();
  await page.screenshot({ path: "test-results/d2-escalated.png", fullPage: true });
  await page.getByRole("button", { name: /^Proposals/ }).click();
  await expect(page.locator(".plan-row")).toHaveCount(5);
  await expect(page.locator(".plan-row").filter({ hasText: "Invalid" })).toHaveCount(1);
  await expect(page.locator(".plan-list .fine-print")).toContainText("fixture placeholders");
  await page.screenshot({ path: "test-results/d2-proposals.png", fullPage: true });
  const row = page.locator(".plan-row").first();
  await row.click();
  await expect(page.getByRole("dialog")).toContainText("plan_hash");
  await page.keyboard.press("Escape");
  await expect(row).toBeFocused();
  await page.getByRole("button", { name: "Resources", exact: true }).click();
  await expect(page.locator(".resource-grid")).toContainText("Shelter South");
  await expect(page.locator(".resource-grid")).toContainText("350");
  await page.screenshot({ path: "test-results/d2-resources.png", fullPage: true });
  expect(errors).toEqual([]);
});

test("browser connection errors are not reported as invalid events", async ({ page }) => {
  const run = "run-e";
  await page.route("**/api/health", (route) =>
    route.fulfill({ json: { ok: true, model_available: false, provider: null, mode: "live" } }),
  );
  await page.route("**/api/state", (route) =>
    route.fulfill({
      json: { schema_version: "1", run_id: run, mode: "live", last_seq: 0, negotiation_status: "idle", world: { scenario_id: "normal", step: 0, state_version: 0 } },
    }),
  );
  // The backend closes the stream after each batch; the browser then fires a data-less "error".
  await page.route("**/api/events/stream", (route) =>
    route.fulfill({ contentType: "text/event-stream", body: "retry: 200\n\n" }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Connect simulator" }).click();
  await page.waitForTimeout(1500);
  await expect(page.locator(".connection-button")).not.toContainText("Invalid event");
});

test("D3: Madhav's incident viewer is mounted, labeled FIXTURE, and shows a selected route", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByLabel("Scenario preset").selectOption("normal");
  await page.getByRole("button", { name: "Load preview", exact: true }).first().click();
  const viewer = page.locator(".iv");
  await expect(viewer).toBeVisible();
  await expect(viewer.locator(".iv-mode")).toHaveText("FIXTURE");
  await expect(viewer.locator(".iv-panels")).toBeHidden();
  await page.getByRole("button", { name: "Map details" }).click();
  await expect(viewer.locator(".iv-panels")).toBeVisible();
  await page.getByRole("button", { name: "Hide map details" }).click();
  await page.getByRole("button", { name: /^Proposals/ }).click();
  await expect(page.locator(".plan-row").first()).toBeVisible({ timeout: 15000 });
  await page.locator(".plan-row").first().click();
  await page.keyboard.press("Escape");
  await expect(page.locator(".route-chip")).toContainText("Showing route of");
  await page.screenshot({ path: "test-results/map-1440.png", fullPage: true });
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.screenshot({ path: "test-results/map-1280.png", fullPage: true });
  await page.locator(".route-chip").click();
  await expect(page.locator(".route-chip")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("WS-A's full 3D forest app is the hero view, isolated in its own page", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  const frame = page.frameLocator(".forest-hero iframe");
  await expect(frame.locator("body")).not.toBeEmpty({ timeout: 15000 });
  await expect(frame.locator(".world-canvas, .webgl-error").first()).toBeVisible({ timeout: 15000 });
  // Dashboard styles are unaffected by WS-A's page-wide CSS.
  await expect(page.locator(".app-header")).toBeVisible();
  await page.waitForTimeout(2500);
  await page.screenshot({ path: "test-results/forest-hero.png" });
  expect(errors).toEqual([]);
});
