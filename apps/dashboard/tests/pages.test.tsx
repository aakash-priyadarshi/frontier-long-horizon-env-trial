import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import OverviewPage from "@/app/page";
import RunsPage from "@/app/runs/page";
import SettingsPage from "@/app/settings/page";
import { AppShell } from "@/components/app-shell";

function response(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response);
}

const anthropicProvider = {
  provider: "anthropic", display_name: "Anthropic", configured: true, ready: true,
  models: [], base_url: null,
  credential: { state: "available", source: "environment", required: true },
  endpoint: { state: "not_tested", tested_at: null },
  authentication: { state: "not_tested", tested_at: null },
  model_discovery: { state: "unsupported", count: 0, tested_at: null },
  tool_calling: { state: "not_tested", tested_at: null },
  capabilities: { custom_model: true, temperature: true, reasoning_effort: false, deterministic: true, custom_base_url: false, connection_test: false, model_discovery: false, tool_probe: true },
};

test("overview renders the scripted empty state and authority disclaimer", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => url.includes("providers") ? response({ items: [{ configured: true }] }) : response({ overview: { total_evaluations: 0, total_completed_episodes: 0, strict_success_rate: null, average_reward: null, average_actions: null, average_cost_per_success: null }, recent_batches: [], recent_failures: [], environment_commit: "a".repeat(40), frozen_v1_tag: "b".repeat(40) })));
  render(<OverviewPage />);
  expect(await screen.findByRole("heading", { name: "No evaluations yet" })).toBeInTheDocument();
  expect(screen.getByText(/Scores are read-only/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run scripted demonstration" })).toBeInTheDocument();
});

test("settings never renders a secret returned by provider metadata", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response({ items: [{ ...anthropicProvider, secret: "do-not-render" }] })));
  render(<SettingsPage />);
  expect(await screen.findByRole("heading", { name: "Anthropic" })).toBeInTheDocument();
  expect(screen.queryByText("do-not-render")).not.toBeInTheDocument();
  expect(screen.getByText(/Keys stay server-side after submission/)).toBeInTheDocument();
});

test("settings submits a session key and never writes it to browser storage", async () => {
  const missing = { ...anthropicProvider, configured: false, ready: false, credential: { state: "missing", source: "missing", required: true } };
  const session = { ...anthropicProvider, credential: { state: "available", source: "session", required: true } };
  const fetchMock = vi.fn((_url: string, init?: RequestInit) => init?.method === "POST" ? response({ provider: session }) : response({ items: [missing] }));
  vi.stubGlobal("fetch", fetchMock);
  render(<SettingsPage />);
  const input = await screen.findByLabelText("Anthropic API key");
  await userEvent.type(input, "browser-session-secret");
  await userEvent.click(screen.getByRole("button", { name: "Use for session" }));
  expect(await screen.findByText(/Session settings updated/)).toBeInTheDocument();
  const submitted = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")?.[1];
  expect(String(submitted?.body)).toContain("browser-session-secret");
  expect(input).toHaveValue("");
  expect(JSON.stringify({ ...window.localStorage, ...window.sessionStorage })).not.toContain("browser-session-secret");
});

test("unsupported discovery remains neutral and manual model probes stay available", async () => {
  const gemini = { ...anthropicProvider, provider: "gemini", display_name: "Gemini" };
  vi.stubGlobal("fetch", vi.fn(() => response({ items: [anthropicProvider, gemini] })));
  render(<SettingsPage />);
  expect(await screen.findByRole("heading", { name: "Anthropic" })).toBeInTheDocument();
  expect(screen.getAllByText("Discovery unsupported")).toHaveLength(2);
  expect(screen.getAllByLabelText("Model name for tool test")).toHaveLength(2);
});

test("provider connection testing exposes skeletons before independent status transitions", async () => {
  const initial = { ...anthropicProvider, capabilities: { ...anthropicProvider.capabilities, connection_test: true } };
  const tested = {
    ...initial,
    models: [{ id: "model-tested", display_name: "Model tested" }],
    endpoint: { state: "reachable", tested_at: "2026-07-14T00:00:00Z" },
    authentication: { state: "valid", tested_at: "2026-07-14T00:00:00Z" },
    model_discovery: { state: "discovered", count: 1, tested_at: "2026-07-14T00:00:00Z" },
  };
  let resolveTest!: (value: Response) => void;
  const pending = new Promise<Response>(resolve => { resolveTest = resolve; });
  vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => init?.method === "POST" ? pending : response({ items: [initial] })));
  render(<SettingsPage />);
  const card = await screen.findByRole("article", { name: "Anthropic provider settings" });
  await userEvent.click(within(card).getByRole("button", { name: "Test connection" }));
  expect(await within(card).findByLabelText("Endpoint check in progress")).toBeInTheDocument();
  expect(within(card).getByLabelText("Authentication check in progress")).toBeInTheDocument();
  expect(within(card).getByLabelText("Model discovery check in progress")).toBeInTheDocument();
  resolveTest({ ok: true, status: 200, json: () => Promise.resolve({ provider: tested }) } as Response);
  expect(await within(card).findByText("Reachable")).toBeInTheDocument();
  expect(within(card).getByText("Valid")).toBeInTheDocument();
  expect(within(card).getByText("Discovered (1)")).toBeInTheDocument();
});

test("ollama exposes only a copyable pull command and never starts a download", async () => {
  const ollama = {
    provider: "ollama", display_name: "Ollama (local)", configured: true, ready: false,
    models: [], base_url: "http://127.0.0.1:11434/v1",
    credential: { state: "not_required", source: "not_required", required: false },
    endpoint: { state: "unreachable", tested_at: "2026-07-14T00:00:00Z" },
    authentication: { state: "not_required", tested_at: "2026-07-14T00:00:00Z" },
    model_discovery: { state: "failed", count: 0, tested_at: "2026-07-14T00:00:00Z" },
    tool_calling: { state: "not_tested", tested_at: null },
    capabilities: { custom_model: true, temperature: true, reasoning_effort: false, deterministic: true, custom_base_url: true, connection_test: true, model_discovery: true, tool_probe: true },
  };
  const fetchMock = vi.fn(() => response({ items: [ollama] }));
  vi.stubGlobal("fetch", fetchMock);
  render(<SettingsPage />);
  expect(await screen.findByRole("heading", { name: "Install another model" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copy command" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: /download|pull model/i })).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("ollama custom compatibility form stays isolated and documents supported model families", async () => {
  const model = {
    id: "deepseek-r1:8b-llama-distill-q4_K_M",
    display_name: "deepseek-r1:8b-llama-distill-q4_K_M",
    digest: "deepseek-digest",
    tool_compatibility: { state: "failed", tested_at: "2026-07-14T00:00:00Z", error_code: "provider_out_of_memory" },
    tool_support: null,
    tool_limitation: {
      name: "DeepSeek R1 Llama-distill 8B",
      code: "legacy_template_without_tool_definitions",
      detail: "The installed chat template does not inject supplied tool definitions.",
      recommendation: "ollama pull deepseek-r1:8b",
    },
  };
  const ollama = {
    provider: "ollama", display_name: "Ollama (local)", configured: true, ready: true,
    models: [model], base_url: "http://127.0.0.1:11434/v1",
    credential: { state: "not_required", source: "not_required", required: false },
    endpoint: { state: "reachable", tested_at: "2026-07-14T00:00:00Z" },
    authentication: { state: "not_required", tested_at: "2026-07-14T00:00:00Z" },
    model_discovery: { state: "discovered", count: 1, tested_at: "2026-07-14T00:00:00Z" },
    tool_calling: model.tool_compatibility,
    capabilities: { custom_model: true, temperature: true, reasoning_effort: true, deterministic: true, custom_base_url: true, connection_test: true, model_discovery: true, tool_probe: true },
  };
  const catalog = {
    items: [{ id: "qwen3", name: "Qwen 3", patterns: ["qwen3:*"], examples: ["qwen3:8b"], support: "locally_verified", hardware: "8B fits with a bounded context.", notes: "Native tools and thinking.", profile: {} }],
    known_limitations: [],
    custom_probe: { isolated_tool: "frontier_probe", executes_tool: false, stores_model_output: false, fields: [] },
    meaning: "Every installed digest must pass.",
  };
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url.includes("tool-support")) return response(catalog);
    if (url.includes("tool-probe") && init?.method === "POST") {
      return response({ provider: ollama, tool_compatibility: { ...model.tool_compatibility, state: "failed", error_code: "provider_out_of_memory" } });
    }
    return response({ items: [ollama] });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<SettingsPage />);

  await userEvent.click(await screen.findByRole("button", { name: /Test unsupported model/ }));
  expect(screen.getByText("Fake tool only")).toBeInTheDocument();
  expect(screen.getByText(/does not inject supplied tool definitions/)).toBeInTheDocument();
  const context = screen.getByLabelText(/Context window/);
  await userEvent.clear(context);
  await userEvent.type(context, "8192");
  await userEvent.click(screen.getByRole("button", { name: "Run custom tool test" }));
  expect(await screen.findByText(/could not fit in available memory/)).toBeInTheDocument();
  const submitted = fetchMock.mock.calls.find(([url, init]) => String(url).includes("tool-probe") && init?.method === "POST")?.[1];
  expect(JSON.parse(String(submitted?.body))).toMatchObject({
    model: model.id,
    options: { context_window: 8192, prompt_style: "strict", thinking: "off" },
  });

  await userEvent.click(screen.getByRole("button", { name: /Supported models & guide/ }));
  expect(await screen.findByRole("heading", { name: "Supported native-tool families" })).toBeInTheDocument();
  expect(await screen.findByText("Qwen 3")).toBeInTheDocument();
  expect(screen.getByText(/Start at 16K/)).toBeInTheDocument();
});

test("responsive navigation has accessible controls and an active route indicator", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response({ items: [] })));
  render(<AppShell><p>Content</p></AppShell>);
  expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Open navigation" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Switch to light theme/ })).toBeInTheDocument();
  const overview = screen.getByRole("link", { name: "Overview" });
  expect(overview).toHaveAttribute("aria-current", "page");
  expect(overview.querySelector(".shared-selection-indicator")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute("href", "/runs");
  expect(screen.getByText("Content")).toBeInTheDocument();
  expect(await screen.findByText("No active runs")).toBeInTheDocument();
});

test("runs page combines live episodes and immutable history", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response({
    total: 2, limit: 200, offset: 0,
    items: [
      { run_id: "run-live-123456789", batch_id: "batch-live", status: "running", provider: "ollama", model: "qwen3:8b", split: "eval", seed: 0, attempt: 1, current_step: 3, current_tool: "telemetry.logs", input_tokens: 1200, output_tokens: 300 },
      { run_id: "run-history-123456", batch_id: "batch-history", status: "completed", provider: "scripted", model: "scripted-valid", split: "eval", seed: 1, attempt: 1, authoritative_reward: 1, authoritative_verdict: "pass", action_count: 20, model_call_count: 21, termination_reason: "environment_terminated", updated_at: "2026-07-14T08:00:00Z" },
    ],
  })));
  render(<RunsPage />);
  expect(await screen.findByRole("heading", { name: "Live runs" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Run history" })).toBeInTheDocument();
  expect(screen.getByRole("article", { name: "qwen3:8b live run" })).toHaveTextContent("telemetry.logs");
  expect(screen.getByRole("table", { name: "Historical model evaluation runs" })).toHaveTextContent("scripted-valid");
  expect(screen.getByRole("link", { name: "Inspect live episode" })).toHaveAttribute("href", "/runs/run-live-123456789");
});

test("theme choice is persisted without storing provider data", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response({ items: [] })));
  render(<AppShell><p>Content</p></AppShell>);
  await screen.findByText("No active runs");
  fireEvent.click(screen.getByRole("button", { name: /Switch to light theme/ }));
  expect(localStorage.getItem("frontier-theme")).toBe("light");
  expect([...Array(localStorage.length)].map((_, index) => localStorage.key(index))).toEqual(["frontier-theme"]);
});

test("reduced motion preference remains operable", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response({ items: [] })));
  vi.mocked(window.matchMedia).mockImplementation((query: string) => ({ matches: query.includes("prefers-reduced-motion"), media: query, onchange: null, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() }));
  render(<AppShell><button>Immediate control</button></AppShell>);
  await screen.findByText("No active runs");
  expect(screen.getByRole("button", { name: "Immediate control" })).toBeEnabled();
});
