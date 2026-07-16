import { expect, test, type Page } from "@playwright/test";

const api = process.env.FRONTIER_API_URL ?? "http://127.0.0.1:8000";
let validBatch = "";
let wrongBatch = "";
let validRun = "";
const browserErrors = new WeakMap<Page, string[]>();

async function launchScripted(page: Page, model: "scripted-valid" | "scripted-wrong-control") {
  await page.goto("/evaluations/new");
  await expect(page.getByRole("heading", { name: "New evaluation" })).toBeVisible();
  const modelName = model === "scripted-valid" ? /Scripted valid repair/ : /Scripted wrong-control repair/;
  await page.getByRole("radio", { name: modelName }).click();
  await page.getByLabel(/I understand scores/).check();
  await page.getByRole("button", { name: "Run scripted demonstration" }).click();
  await page.waitForURL(/\/evaluations\/batch_/);
  const batchId = page.url().split("/").pop()!;
  await expect(page.getByText("completed", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
  return batchId;
}

test.describe.serial("polished dashboard journeys", () => {
  test.beforeEach(async ({ page }) => {
    const errors: string[] = [];
    browserErrors.set(page, errors);
    page.on("pageerror", error => errors.push(error.message));
  });

  test.afterEach(async ({ page }) => {
    expect(browserErrors.get(page) ?? []).toEqual([]);
  });

  test("1. dashboard loads with scoring authority and provider summary", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Measure model behavior against strict evidence." })).toBeVisible();
    await expect(page.getByText(/Scores are read-only/)).toBeVisible();
    await expect(page.getByText(/providers ready/i)).toBeVisible();
  });

  test("2. scripted demonstration launches through the review flow", async ({ page, request }) => {
    validBatch = await launchScripted(page, "scripted-valid");
    const batch = await (await request.get(`${api}/api/evaluations/${validBatch}`)).json();
    expect(batch.runs[0].authoritative_reward).toBe(1);
    validRun = batch.runs[0].run_id;
    await expect(page.getByText("Batch settled")).toBeVisible();
  });

  test("3. live batch status settles progress and counts", async ({ page }) => {
    await page.goto(`/evaluations/${validBatch}`);
    await expect(page.getByText("Batch settled")).toBeVisible();
    await expect(page.getByRole("progressbar", { name: "Overall batch progress" })).toHaveAttribute("aria-valuenow", "1");
    await expect(page.getByText("1 of 1 episodes settled")).toBeVisible();
    await expect(page.getByText("completed", { exact: true }).first()).toBeVisible();
  });

  test("4. completed run details open with verifier-backed evidence", async ({ page }) => {
    await page.goto(`/runs/${validRun}`);
    await expect(page.getByText("Authoritative final score")).toBeVisible();
    await expect(page.locator(".score-hero").getByText("1", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Candidate diff" })).toBeVisible();
    await expect(page.locator(".candidate-diff-files")).toContainText("service/flow.py");
    await expect(page.getByText(/digest-bound/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Action timeline" })).toBeVisible();
    await expect(page.locator(".digest-value code")).toContainText("sha256:");
  });

  test("5. run timeline filters and sanitized expansion work", async ({ page }) => {
    await page.goto(`/runs/${validRun}`);
    const release = page.getByRole("tab", { name: /Release \d+/ });
    await release.click();
    await expect(release).toHaveAttribute("aria-selected", "true");
    const firstAction = page.locator(".timeline-entry .expandable-trigger").first();
    await firstAction.click();
    await expect(page.getByText("Sanitized request and result").first()).toBeVisible();
    await expect(page.getByText("Request arguments").first()).toBeVisible();
  });

  test("5a. runs workspace combines active state and history", async ({ page }) => {
    await page.goto("/runs");
    await expect(page.getByRole("heading", { name: "Live runs" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Run history" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Candidate diffs" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete all retained diffs" })).toBeEnabled();
    await expect(page.getByRole("table", { name: "Historical model evaluation runs" })).toContainText("scripted-valid");
    await expect(page.getByRole("link", { name: "Runs" })).toHaveAttribute("aria-current", "page");
  });

  test("6. comparison charts render strict valid and partial outcomes", async ({ page, request }) => {
    wrongBatch = await launchScripted(page, "scripted-wrong-control");
    const wrong = await (await request.get(`${api}/api/evaluations/${wrongBatch}`)).json();
    expect(wrong.runs[0].authoritative_reward).toBe(0.85);
    expect(wrong.runs[0].authoritative_verdict).toBe("partial");
    await page.goto(`/compare?batch=${validBatch}&batch=${wrongBatch}`);
    await expect(page.getByRole("heading", { name: "Success rate by model" })).toBeVisible();
    await expect(page.locator("canvas").first()).toBeVisible();
    await expect(page.getByText("scripted-valid").first()).toBeVisible();
    await expect(page.getByText("scripted-wrong-control").first()).toBeVisible();
  });

  test("7. comparison chart and table modes remain equivalent", async ({ page }) => {
    await page.goto(`/compare?batch=${validBatch}&batch=${wrongBatch}`);
    await page.getByRole("button", { name: "Tables" }).click();
    await expect(page.getByRole("table", { name: "Success rate by model data" })).toBeVisible();
    await expect(page.getByRole("table", { name: "Average and median reward data" })).toBeVisible();
    await page.getByRole("button", { name: "Charts" }).click();
    await expect(page.locator("canvas").first()).toBeVisible();
  });

  test("8. mobile navigation opens, routes, and closes", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/settings");
    await page.getByRole("button", { name: "Open navigation" }).click();
    await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
    await page.getByRole("link", { name: "Overview" }).click();
    await expect(page.getByRole("heading", { name: "Measure model behavior against strict evidence." })).toBeVisible();
    await expect(page.locator(".sidebar")).not.toHaveClass(/open/);
  });

  test("9. reduced motion and light mode remain fully operable", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto("/evaluations/new");
    await expect(page.getByRole("heading", { name: "New evaluation" })).toBeVisible();
    const settings = page.getByRole("group", { name: "Recommended settings" });
    const balanced = settings.getByRole("button", { name: "Apply Balanced preset" });
    const custom = settings.getByRole("button", { name: "Use Custom settings" });
    await expect(custom).toHaveAttribute("aria-pressed", "true");
    await balanced.click();
    await expect(balanced).toHaveAttribute("aria-pressed", "true");
    await page.getByLabel("Environment steps").fill("80");
    await expect(custom).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("radio", { name: /Scripted wrong-control repair/ }).focus();
    await expect(page.getByRole("radio", { name: /Scripted wrong-control repair/ })).toBeFocused();
    await page.getByLabel(/I understand scores/).check();
    await expect(page.getByRole("button", { name: "Run scripted demonstration" })).toBeEnabled();
  });

  test("10. Ollama exposes bounded custom compatibility controls and support documentation", async ({ page }) => {
    await page.goto("/settings");
    const card = page.getByRole("article", { name: "Ollama (local) provider settings" });
    await card.getByRole("button", { name: /Supported models & guide/ }).click();
    await expect(card.getByRole("heading", { name: "Supported native-tool families" })).toBeVisible();
    await expect(card.getByText("Qwen 3", { exact: true })).toBeVisible();
    await expect(card.getByText(/Every installed tag still has to pass/)).toBeVisible();
    await card.getByRole("button", { name: /Test unsupported model/ }).click();
    await expect(card.getByText("Fake tool only")).toBeVisible();
    await expect(card.getByLabel(/Context window/)).toHaveValue("16384");
    await expect(card.getByLabel(/Probe instruction/)).toHaveValue("strict");
  });

  test("11. provider settings never expose submitted session secrets", async ({ page, request }) => {
    const secret = "playwright-session-secret-never-persist";
    await page.goto("/settings");
    const card = page.getByRole("article", { name: "Anthropic provider settings" });
    await card.getByLabel("Anthropic API key").fill(secret);
    await card.getByRole("button", { name: "Use for session" }).click();
    await expect(card.getByText("Available for this session")).toBeVisible();
    await expect(card.getByLabel("Anthropic API key")).toHaveValue("");
    expect(await page.locator("body").innerText()).not.toContain(secret);
    const browserStorage = await page.evaluate(() => ({
      local: Object.fromEntries(Object.entries(localStorage)),
      session: Object.fromEntries(Object.entries(sessionStorage)),
    }));
    expect(JSON.stringify(browserStorage)).not.toContain(secret);
    expect(await (await request.get(`${api}/api/providers`)).text()).not.toContain(secret);
    await card.getByRole("button", { name: "Clear session key" }).click();
    await expect.poll(async () => {
      const providers = await (await request.get(`${api}/api/providers`)).json();
      return providers.items.find((item: { provider: string }) => item.provider === "anthropic").credential.source;
    }).not.toBe("session");
    const providers = await (await request.get(`${api}/api/providers`)).json();
    const source = providers.items.find((item: { provider: string }) => item.provider === "anthropic").credential.source;
    const fallbackLabel: Record<string, string> = {
      local_env: "Saved in local .env",
      environment: "Available from environment",
      missing: "Missing",
    };
    await expect(card.getByText(fallbackLabel[source])).toBeVisible();
  });
});
