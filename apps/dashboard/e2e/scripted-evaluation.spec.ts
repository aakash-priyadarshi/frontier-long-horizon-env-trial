import { expect, test } from "@playwright/test";

const api = "http://127.0.0.1:8000";

async function startScripted(page: import("@playwright/test").Page, model: "scripted-valid" | "scripted-wrong-control") {
  await page.goto("/evaluations/new");
  await expect(page.getByRole("heading", { name: "New evaluation" })).toBeVisible();
  await page.locator("fieldset").first().locator("select").nth(1).selectOption(model);
  await page.getByLabel(/I understand scores/).check();
  await page.getByRole("button", { name: "Run scripted demonstration" }).click();
  await page.waitForURL(/\/evaluations\/batch_/);
  const batchId = page.url().split("/").pop()!;
  await expect(page.getByText("completed", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
  return batchId;
}

test("valid and wrong scripted evaluations remain verifier-backed end to end", async ({ page, request }) => {
  const browserErrors: string[] = [];
  page.on("pageerror", error => browserErrors.push(error.message));

  await page.goto("/");
  await expect(page.getByText(/Scores are read-only/)).toBeVisible();

  const validBatch = await startScripted(page, "scripted-valid");
  await expect(page.getByText("1", { exact: true }).first()).toBeVisible();
  const validApi = await (await request.get(`${api}/api/evaluations/${validBatch}`)).json();
  expect(validApi.runs[0].authoritative_reward).toBe(1);
  await page.getByRole("link", { name: /Inspect episode/ }).click();
  await expect(page.getByText("Authoritative final score")).toBeVisible();
  await expect(page.locator(".score-hero").getByText("1", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Action timeline" })).toBeVisible();
  await expect(page.locator(".timeline-entry")).toHaveCount(20);
  await expect(page.getByText(/sha256:/)).toBeVisible();

  const wrongBatch = await startScripted(page, "scripted-wrong-control");
  const wrongApi = await (await request.get(`${api}/api/evaluations/${wrongBatch}`)).json();
  expect(wrongApi.runs[0].authoritative_reward).toBe(0.85);
  expect(wrongApi.runs[0].authoritative_verdict).toBe("partial");

  await page.goto(`/compare?batch=${validBatch}&batch=${wrongBatch}`);
  await expect(page.getByRole("heading", { name: "Success rate by model" })).toBeVisible();
  await expect(page.locator("canvas").first()).toBeVisible();
  await expect(page.getByText("scripted-valid").first()).toBeVisible();
  await expect(page.getByText("scripted-wrong-control").first()).toBeVisible();

  const exported = await (await request.get(`${api}/api/exports/${validBatch}.json`)).text();
  expect(exported).not.toContain("auth_tag");
  expect(exported).not.toContain("member_selector");
  expect(exported).not.toMatch(/H-[A-Za-z0-9_-]+/);
  expect(browserErrors).toEqual([]);
});

test("responsive navigation, provider safety, and reduced motion remain usable", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Providers and settings" })).toBeVisible();
  await expect(page.getByText("Keys never reach the browser")).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  await page.getByRole("link", { name: "Overview" }).click();
  await expect(page.getByRole("heading", { name: "Evaluation overview" })).toBeVisible();
});
