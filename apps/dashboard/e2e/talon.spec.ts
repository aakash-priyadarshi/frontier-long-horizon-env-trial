import { expect, test, type APIRequestContext } from "@playwright/test";

const api = process.env.FRONTIER_API_URL ?? "http://127.0.0.1:8000";
const controlHeaders = { Origin: "http://localhost:3000" };
let datasetId = "";
let trainingId = "";
let evaluationId = "";
let cqlTrainingId = "";
let cqlEvaluationId = "";
let replayEpisodeId = "";

async function waitForRecord(request: APIRequestContext, path: string, timeout = 120_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const response = await request.get(`${api}${path}`);
    const record = await response.json();
    if (["completed", "failed", "cancelled", "interrupted", "timed_out"].includes(record.status)) return record;
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error("Talon record did not settle");
}

test.describe.serial("real Talon simulation journeys", () => {
  test.setTimeout(180_000);

  test("1. landing and capability catalogue disclose no private episode labels", async ({ page }) => {
    await page.goto("/talon");
    await expect(page.getByRole("heading", { name: "Policy-aware decision training" })).toBeVisible();
    await expect(page.getByText("Simulation-only decision support")).toBeVisible();
    await page
      .getByRole("navigation", { name: "Talon simulation navigation" })
      .getByRole("link", { name: "Scenarios" })
      .click();
    await expect(page).toHaveURL(/\/talon\/scenarios$/);
    await expect(page.getByRole("heading", { name: "Public decision capabilities" })).toBeVisible();
    const body = await page.locator("body").innerText();
    expect(body).not.toMatch(/authorised_inspection|perimeter_probing|paired member|expected_action/i);
    expect(body).not.toMatch(/jammer|intercept aircraft|disable aircraft|weapon control/i);
  });

  test("2. dataset generation uses a real private worker", async ({ page, request }) => {
    await page.goto("/talon/datasets");
    await expect(page.getByRole("heading", { name: "Talon training datasets" })).toBeVisible();
    const created = await request.post(`${api}/api/drone/datasets/generate`, {
      headers: { ...controlHeaders, "Idempotency-Key": `pw-dataset-${Date.now()}` },
      data: { seed_count: 1, timeout_seconds: 120 },
    });
    expect(created.status(), await created.text()).toBe(202);
    const records = await (await request.get(`${api}/api/drone/datasets`)).json();
    datasetId = records.items[0].record_id;
    const settled = await waitForRecord(request, `/api/drone/datasets/${datasetId}`);
    expect(settled.status).toBe("completed");
    expect(JSON.stringify(settled)).not.toMatch(/trajectories|expert_action|scenario_family|instance_digest/i);
    await page.reload();
    await expect(page.getByRole("table", { name: "Safe Talon dataset records" })).toBeVisible({ timeout: 30_000 });
  });

  test("3. training cancellation stops its worker and emits one outcome", async ({ request }) => {
    const created = await request.post(`${api}/api/drone/training-runs`, {
      headers: { ...controlHeaders, "Idempotency-Key": `pw-cancel-${Date.now()}` },
      data: { dataset_id: datasetId, architecture: "gru", epochs: 500, batch_size: 32, context_length: 8, timeout_seconds: 120 },
    });
    const id = (await created.json()).training_run_id;
    await request.post(`${api}/api/drone/training-runs/${id}/cancel`, { headers: controlHeaders, data: {} });
    const settled = await waitForRecord(request, `/api/drone/training-runs/${id}`);
    expect(settled.status).toBe("cancelled");
    expect(settled.checkpoint_digest).toBeUndefined();
  });

  test("4. training progress produces a digest-bound model", async ({ page, request }) => {
    const created = await request.post(`${api}/api/drone/training-runs`, {
      headers: { ...controlHeaders, "Idempotency-Key": `pw-train-${Date.now()}` },
      data: { dataset_id: datasetId, architecture: "gru", epochs: 1, batch_size: 64, context_length: 8, timeout_seconds: 90 },
    });
    trainingId = (await created.json()).training_run_id;
    await page.goto(`/talon/training/${trainingId}`);
    await expect(page.getByText("Simulation-only decision support")).toBeVisible();
    const settled = await waitForRecord(request, `/api/drone/training-runs/${trainingId}`);
    expect(settled.status).toBe("completed");
    await page.reload();
    await expect(page.getByText("Digest-bound")).toBeVisible();
    await expect(page.getByText("In-sample; not held-out safety")).toBeVisible();
  });

  test("5. live evaluation timeline streams real public actions", async ({ page, request }) => {
    const created = await request.post(`${api}/api/drone/evaluations`, {
      headers: { ...controlHeaders, "Idempotency-Key": `pw-eval-${Date.now()}` },
      data: { training_run_id: trainingId, seed_count: 1, timeout_seconds: 120 },
    });
    evaluationId = (await created.json()).evaluation_id;
    await page.goto(`/talon/evaluations/${evaluationId}`);
    await expect(page.getByRole("heading", { name: /ep_[a-f0-9]{24}/ })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("table", { name: "Live public recommendation and policy-gate timeline" })).toBeVisible();
    const settled = await waitForRecord(request, `/api/drone/evaluations/${evaluationId}`, 150_000);
    expect(settled.status).toBe("completed");
    expect(settled.aggregate.episode_count).toBe(15);
  });

  test("6. valid approval and replay falsification use the real authority", async ({ page }) => {
    await page.goto("/talon/policy");
    await page.getByRole("button", { name: "Run valid approval demo" }).click();
    await expect(page.getByText("First use accepted")).toBeVisible();
    await expect(page.getByText(/Approval consumed once.*External effect: false/)).toBeVisible();
    await expect(page.getByText(/Gate rejection:.*fresh_sensor_confirmation_required.*External effect: false/)).toBeVisible();
    await page.getByRole("button", { name: "Test replay rejection" }).click();
    await expect(page.getByText(/Replay rejected: approval_already_consumed/)).toBeVisible();
  });

  test("7. safe export contains no private labels or predicate internals", async ({ request }) => {
    const response = await request.get(`${api}/api/drone/exports/${evaluationId}.json`);
    expect(response.ok()).toBeTruthy();
    const text = await response.text();
    expect(text).not.toMatch(/scenario_family|instance_digest|expert_action|failed_predicate|actual_object|true_intent/i);
    expect(text).not.toMatch(/api[_-]?key|bearer\s|capability_token|chain.of.thought/i);
  });

  test("8. calibration chart has an accessible table alternative", async ({ page }) => {
    await page.goto(`/talon/evaluations/${evaluationId}`);
    await expect(page.locator("main").getByRole("heading", { name: "Confidence calibration" }).first()).toBeVisible();
    await page.getByText("Accessible data table").click();
    await expect(page.getByRole("table", { name: "Confidence calibration data" })).toBeVisible();
    expect(await page.locator("body").innerText()).not.toMatch(/failed_predicate|scenario family/i);
  });

  test("9. reduced motion remains operable with no physical-response controls", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/talon/policy");
    await expect(page.getByRole("heading", { name: "Policy gate" })).toBeVisible();
    await expect(page.getByText("REQUEST_COMMAND_LINK_VERIFICATION")).toBeVisible();
    await expect(page.getByText(/Command-link state requires the dedicated verification action/)).toBeVisible();
    await expect(page.getByText("None · recommendation only").first()).toBeVisible();
    expect(await page.getByRole("button").allTextContents()).not.toEqual(expect.arrayContaining([expect.stringMatching(/engage|disable|jam|intercept/i)]));
  });

  test("10. component-unavailable state is bounded and Frontier navigation remains", async ({ page }) => {
    await page.route("**/api/drone/health", route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "talon_service_unavailable", message: "the optional Talon component is temporarily unavailable" } }) }));
    await page.goto("/talon");
    await expect(page.getByText("the optional Talon component is temporarily unavailable")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  });

  test("11. conservative offline CQL trains from the authenticated static dataset", async ({ page, request }) => {
    const created = await request.post(`${api}/api/drone/offline-rl/training-runs`, {
      headers: { ...controlHeaders, "Idempotency-Key": `pw-cql-${Date.now()}` },
      data: { dataset_id: datasetId, epochs: 1, batch_size: 64, context_length: 8, hidden_dim: 16, layers: 1, dropout: 0, target_update_interval: 2, timeout_seconds: 120 },
    });
    const creation = await created.json();
    expect(created.status(), JSON.stringify(creation)).toBe(202);
    cqlTrainingId = creation.training_run_id;
    await page.goto(`/talon/training/${cqlTrainingId}`);
    const settled = await waitForRecord(request, `/api/drone/offline-rl/training-runs/${cqlTrainingId}`, 150_000);
    expect(settled.status).toBe("completed");
    expect(settled.algorithm).toBe("discrete_cql");
    expect(settled.offline_dataset_digest).toMatch(/^sha256:[a-f0-9]{64}$/);
    await page.reload();
    await expect(page.getByRole("heading", { name: "Conservative offline-RL losses" })).toBeVisible();
    await expect(page.getByText("Static transitions")).toBeVisible();
  });

  test("12. frozen CQL evaluation produces an immutable public replay", async ({ page, request }) => {
    const created = await request.post(`${api}/api/drone/offline-rl/evaluations`, {
      headers: { ...controlHeaders, "Idempotency-Key": `pw-cql-eval-${Date.now()}` },
      data: { training_run_id: cqlTrainingId, seed_count: 1, timeout_seconds: 120 },
    });
    const creation = await created.json();
    expect(created.status(), JSON.stringify(creation)).toBe(202);
    cqlEvaluationId = creation.evaluation_id;
    const settled = await waitForRecord(request, `/api/drone/evaluations/${cqlEvaluationId}`, 150_000);
    expect(settled.status).toBe("completed");
    replayEpisodeId = settled.episodes[0].result.episode_id;
    expect(settled.episodes[0].replay.replay_digest).toMatch(/^sha256:[a-f0-9]{64}$/);
    await page.goto(`/talon/episodes/${replayEpisodeId}/replay`);
    await expect(page.getByRole("heading", { name: "Human-readable model behaviour" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Play replay" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByLabel("Replay position")).toBeVisible();
    await page.getByRole("button", { name: "Next step" }).click();
    const body = await page.locator("body").innerText();
    expect(body).toMatch(/deterministic policy gate/i);
    expect(body).toContain("Not collected or retained");
    expect(body).not.toMatch(/scenario_family|true_intent|expert_action|verifier_predicate|chain.of.thought:/i);
    const exported = await request.get(`${api}/api/drone/episodes/${replayEpisodeId}/replay/export.json`);
    expect(exported.ok()).toBeTruthy();
    expect(await exported.text()).not.toMatch(/scenario_family|true_intent|expert_action|verifier_predicate/i);
  });

  test("13. scripted external baseline evaluation, replay, and comparison", async ({ page, request }) => {
    await page.goto("/talon/evaluations/new");
    await expect(page.getByRole("heading", { name: "Evaluate a Talon policy" })).toBeVisible();
    await page.getByLabel("Policy source").selectOption("external_llm");
    await expect(page.getByText(/External models are evaluated as simulation-only recommendation policies/)).toBeVisible();
    await expect(page.getByText(/deterministic policy gate and strict verifier/)).toBeVisible();
    await page.getByLabel("Policy source").selectOption("scripted_external_baseline");
    await expect(page.getByLabel("Scripted baseline")).toBeVisible();

    const created = await request.post(`${api}/api/drone/external-llm/evaluations`, {
      headers: { ...controlHeaders, "Idempotency-Key": `pw-ext-${Date.now()}` },
      data: {
        policy_kind: "scripted_external_baseline",
        provider: "scripted_external",
        model: "scripted-valid",
        prompt_version: "talon-llm-policy/1.0",
        temperature: 0,
        timeout_seconds: 30,
        max_output_tokens: 300,
        attempts_per_scenario: 1,
        scenario_partition: "evaluation",
        seed_count: 1,
      },
    });
    const creation = await created.json();
    expect(created.status(), JSON.stringify(creation)).toBe(202);
    const externalEvalId = creation.evaluation_id as string;
    await page.goto(`/talon/evaluations/${externalEvalId}`);
    const settled = await waitForRecord(request, `/api/drone/evaluations/${externalEvalId}`, 180_000);
    expect(settled.status).toBe("completed");
    expect(settled.algorithm).toBe("scripted_external_baseline");
    expect(settled.checkpoint_digest == null || settled.checkpoint_digest === undefined).toBeTruthy();
    expect(settled.episodes[0].replay.external_policy.policy_kind).toBe("scripted_external_baseline");
    expect(settled.episodes[0].checkpoint_digest).toBeNull();
    const externalEpisodeId = settled.episodes[0].result.episode_id;
    const replayApi = await request.get(`${api}/api/drone/episodes/${externalEpisodeId}/replay`);
    expect(replayApi.ok(), await replayApi.text()).toBeTruthy();
    const replayBody = await replayApi.json();
    expect(replayBody.checkpoint_digest).toBeNull();
    expect(replayBody.external_policy.policy_kind).toBe("scripted_external_baseline");
    await page.goto(`/talon/episodes/${externalEpisodeId}/replay`);
    await expect(page.getByRole("heading", { name: "Human-readable model behaviour" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Play replay" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("scripted_external_baseline").first()).toBeVisible();
    expect(await page.locator("body").innerText()).not.toMatch(/sk-|api[_-]?key|authorization|chain.of.thought:/i);

    const compared = await request.post(`${api}/api/drone/comparisons`, {
      headers: { ...controlHeaders, "Idempotency-Key": `pw-ext-compare-${Date.now()}` },
      data: { evaluation_ids: [evaluationId, externalEvalId] },
    });
    expect(compared.status(), await compared.text()).toBe(201);
    const comparison = await compared.json();
    expect(comparison.compatibility.domain_compatible).toBe(true);
    expect(comparison.models.some((item: { policy_kind?: string }) => item.policy_kind === "scripted_external_baseline")).toBeTruthy();
  });
});
