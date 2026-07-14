import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import NewEvaluationPage from "@/app/evaluations/new/page";

const providers = {
  items: [
    { provider: "scripted", display_name: "Scripted", configured: true, ready: true, models: [{ id: "scripted-valid", display_name: "Scripted valid repair" }, { id: "scripted-wrong-control", display_name: "Scripted wrong-control repair" }], credential: { state: "not_required", source: "not_required", required: false }, endpoint: { state: "not_tested", tested_at: null }, authentication: { state: "not_required", tested_at: null }, model_discovery: { state: "discovered", count: 2, tested_at: null }, tool_calling: { state: "not_tested", tested_at: null }, base_url: null, capabilities: { temperature: false, reasoning_effort: false, deterministic: false, custom_model: false, custom_base_url: false, connection_test: false, model_discovery: false, tool_probe: false } },
    { provider: "openai-compatible", display_name: "OpenAI compatible", configured: false, ready: false, models: [], credential: { state: "missing", source: "missing", required: true }, endpoint: { state: "not_tested", tested_at: null }, authentication: { state: "not_tested", tested_at: null }, model_discovery: { state: "not_tested", count: 0, tested_at: null }, tool_calling: { state: "not_tested", tested_at: null }, base_url: "https://api.openai.com/v1", capabilities: { temperature: true, reasoning_effort: true, deterministic: true, custom_model: true, custom_base_url: true, connection_test: true, model_discovery: true, tool_probe: true } },
    { provider: "ollama", display_name: "Ollama (local)", configured: true, ready: true, models: [{ id: "qwen3:8b", display_name: "qwen3:8b" }], credential: { state: "not_required", source: "not_required", required: false }, endpoint: { state: "reachable", tested_at: null }, authentication: { state: "not_required", tested_at: null }, model_discovery: { state: "discovered", count: 1, tested_at: null }, tool_calling: { state: "not_tested", tested_at: null }, base_url: "http://127.0.0.1:11434/v1", capabilities: { temperature: true, reasoning_effort: true, deterministic: true, custom_model: true, custom_base_url: true, connection_test: true, model_discovery: true, tool_probe: true } },
  ],
};

function response(body: unknown, ok = true) {
  return Promise.resolve({ ok, status: ok ? 200 : 422, json: () => Promise.resolve(body) } as Response);
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() => response(providers)));
});

test("selects provider and model from capability metadata", async () => {
  render(<NewEvaluationPage />);
  const providersGroup = await screen.findByRole("radiogroup", { name: "Evaluation provider" });
  expect(within(providersGroup).getByRole("radio", { name: /Scripted Ready/ })).toHaveAttribute("aria-checked", "true");
  expect(screen.getByRole("radio", { name: /Scripted valid repair/ })).toHaveAttribute("aria-checked", "true");
  await userEvent.click(within(providersGroup).getByRole("radio", { name: /OpenAI compatible/ }));
  expect(screen.getByPlaceholderText("provider/model-name")).toBeInTheDocument();
  expect(screen.getByLabelText("Temperature")).toBeInTheDocument();
  expect(screen.getByLabelText("Reasoning effort")).toBeInTheDocument();
  expect(screen.getByText("Configuration required")).toBeInTheDocument();
});

test("provider cards support roving keyboard selection", async () => {
  render(<NewEvaluationPage />);
  const scripted = await screen.findByRole("radio", { name: /Scripted Ready/ });
  scripted.focus();
  fireEvent.keyDown(scripted, { key: "ArrowRight" });
  const openAi = screen.getByRole("radio", { name: /OpenAI compatible/ });
  expect(openAi).toHaveFocus();
  expect(openAi).toHaveAttribute("aria-checked", "true");
  expect(scripted).toHaveAttribute("tabindex", "-1");
});

test("hides unsupported scripted controls", async () => {
  render(<NewEvaluationPage />);
  await screen.findByText("Scripted valid repair");
  expect(screen.queryByLabelText("Temperature")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Reasoning effort")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Deterministic mode")).not.toBeInTheDocument();
});

test("requires explicit confirmation before submission", async () => {
  render(<NewEvaluationPage />);
  const button = await screen.findByRole("button", { name: "Run scripted demonstration" });
  expect(button).toBeDisabled();
  expect(fetch).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByLabelText(/I understand scores/));
  expect(button).toBeEnabled();
});

test("evaluation summary recalculates episodes and hard limits", async () => {
  render(<NewEvaluationPage />);
  await screen.findByText("Scripted valid repair");
  fireEvent.change(screen.getByLabelText("Number of seeds"), { target: { value: "3" } });
  fireEvent.change(screen.getByLabelText("Attempts per seed"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("Environment steps"), { target: { value: "80" } });
  const summary = screen.getByText("Review and run").closest("fieldset")!;
  expect(within(summary).getByText("6 episodes")).toBeInTheDocument();
  expect(within(summary).getByText(/80 steps/)).toBeInTheDocument();
  expect(within(summary).getByText(/3 seeds × 2 attempts/)).toBeInTheDocument();
});

test("applies three provider-aware recommended settings", async () => {
  render(<NewEvaluationPage />);
  const providersGroup = await screen.findByRole("radiogroup", { name: "Evaluation provider" });
  expect(screen.getAllByRole("button", { name: /Apply .* preset/ })).toHaveLength(3);

  await userEvent.click(within(providersGroup).getByRole("radio", { name: /Ollama/ }));
  await userEvent.click(screen.getByRole("button", { name: "Apply Quick smoke preset" }));
  expect(screen.getByLabelText("Number of seeds")).toHaveValue(1);
  expect(screen.getByLabelText("Attempts per seed")).toHaveValue(1);
  expect(screen.getByLabelText(/^Concurrency/)).toHaveValue(1);
  expect(screen.getByLabelText("Maximum output tokens")).toHaveValue(2048);
  expect(screen.getByLabelText(/Context window/)).toHaveValue(16384);
  expect(screen.getByLabelText("Reasoning effort")).toHaveValue("low");
  expect(screen.getByLabelText("Provider timeout (s)")).toHaveValue(180);
  expect(screen.getByLabelText("Wall clock (s)")).toHaveValue(1800);
  expect(screen.getByLabelText("Deterministic mode")).toBeChecked();

  await userEvent.click(screen.getByRole("button", { name: "Apply Balanced preset" }));
  expect(screen.getByLabelText("Number of seeds")).toHaveValue(5);
  expect(screen.getByLabelText("Attempts per seed")).toHaveValue(2);
  expect(screen.getByLabelText(/^Concurrency/)).toHaveValue(1);
  expect(screen.getByLabelText("Provider timeout (s)")).toHaveValue(240);
  expect(screen.getByLabelText("Wall clock (s)")).toHaveValue(2400);
});

test("uses modest parallelism for a hosted-provider preset", async () => {
  render(<NewEvaluationPage />);
  const providersGroup = await screen.findByRole("radiogroup", { name: "Evaluation provider" });
  await userEvent.click(within(providersGroup).getByRole("radio", { name: /OpenAI compatible/ }));
  await userEvent.click(screen.getByRole("button", { name: "Apply Confidence run preset" }));
  expect(screen.getByLabelText("Number of seeds")).toHaveValue(10);
  expect(screen.getByLabelText("Attempts per seed")).toHaveValue(3);
  expect(screen.getByLabelText(/^Concurrency/)).toHaveValue(4);
  expect(screen.getByLabelText("Provider timeout (s)")).toHaveValue(120);
  expect(screen.getByLabelText("Wall clock (s)")).toHaveValue(1200);
});

test("detects only locally installed Ollama models and fills the read-only identifier", async () => {
  const originalOllama = providers.items.find(item => item.provider === "ollama")!;
  const initial = {
    items: providers.items.map(item => item.provider === "ollama" ? {
      ...item,
      models: [],
      model_discovery: { ...item.model_discovery, state: "not_tested", count: 0 },
    } : item),
  };
  const detected = {
    ...originalOllama,
    models: [
      { id: "qwen3:8b", display_name: "qwen3:8b" },
      { id: "llama3.1:8b", display_name: "llama3.1:8b" },
    ],
    model_discovery: { ...originalOllama.model_discovery, state: "discovered", count: 2 },
  };
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith("/api/providers/ollama/connection-test") && init?.method === "POST") return response({ provider: detected });
    return response(initial);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<NewEvaluationPage />);
  const providersGroup = await screen.findByRole("radiogroup", { name: "Evaluation provider" });
  await userEvent.click(within(providersGroup).getByRole("radio", { name: /Ollama/ }));
  const identifier = screen.getByLabelText("Model identifier");
  expect(identifier).toHaveAttribute("readonly");
  await userEvent.click(screen.getByRole("button", { name: "Detect installed models" }));
  await userEvent.click(await screen.findByRole("radio", { name: /llama3.1:8b/ }));
  expect(identifier).toHaveValue("llama3.1:8b");
  expect(fetchMock).toHaveBeenCalledWith(
    "http://localhost:8000/api/providers/ollama/connection-test",
    expect.objectContaining({ method: "POST" }),
  );
});

test("blocks a discovered model whose structured tool test failed", async () => {
  const incompatibleProviders = {
    items: providers.items.map(item => item.provider === "ollama" ? {
      ...item,
      models: [
        { id: "qwen3:8b", display_name: "qwen3:8b", tool_compatibility: { state: "passed", tested_at: "2026-07-14T00:00:00Z" } },
        { id: "deepseek-r1:8b-llama-distill-q4_K_M", display_name: "DeepSeek Llama distill", tool_compatibility: { state: "failed", tested_at: "2026-07-14T00:00:00Z", error_code: "invalid_tool_call" } },
      ],
      model_discovery: { ...item.model_discovery, count: 2 },
    } : item),
  };
  vi.stubGlobal("fetch", vi.fn(() => response(incompatibleProviders)));

  render(<NewEvaluationPage />);
  const providersGroup = await screen.findByRole("radiogroup", { name: "Evaluation provider" });
  await userEvent.click(within(providersGroup).getByRole("radio", { name: /Ollama/ }));
  await userEvent.click(screen.getByRole("radio", { name: /DeepSeek Llama distill/ }));
  expect(screen.getByText("Tool test failed")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent(/did not produce a valid structured tool call/i);
  await userEvent.click(screen.getByLabelText(/I understand scores/));
  expect(screen.getByRole("button", { name: "Start evaluation" })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent(/needs a current passing structured tool test/i);
});

test("loads a configured hosted-provider catalog and fills the editable identifier", async () => {
  const anthropic = {
    provider: "anthropic", display_name: "Anthropic", configured: true, ready: true,
    models: [], base_url: null,
    credential: { state: "available", source: "session", required: true },
    endpoint: { state: "not_tested", tested_at: null },
    authentication: { state: "not_tested", tested_at: null },
    model_discovery: { state: "not_tested", count: 0, tested_at: null },
    tool_calling: { state: "not_tested", tested_at: null },
    capabilities: { custom_model: true, temperature: true, reasoning_effort: false, deterministic: true, custom_base_url: false, connection_test: true, model_discovery: true, tool_probe: true },
  };
  const discovered = {
    ...anthropic,
    models: [
      { id: "claude-sonnet-test", display_name: "Claude Sonnet Test" },
      { id: "claude-haiku-test", display_name: "Claude Haiku Test" },
    ],
    endpoint: { state: "reachable", tested_at: "2026-07-14T00:00:00Z" },
    authentication: { state: "valid", tested_at: "2026-07-14T00:00:00Z" },
    model_discovery: { state: "discovered", count: 2, tested_at: "2026-07-14T00:00:00Z" },
  };
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith("/api/providers/anthropic/connection-test") && init?.method === "POST") return response({ provider: discovered });
    return response({ items: [...providers.items, anthropic] });
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<NewEvaluationPage />);
  const providersGroup = await screen.findByRole("radiogroup", { name: "Evaluation provider" });
  await userEvent.click(within(providersGroup).getByRole("radio", { name: /Anthropic/ }));
  const option = await screen.findByRole("radio", { name: /Claude Sonnet Test/ });
  const identifier = screen.getByLabelText("Model identifier");
  expect(identifier).not.toHaveAttribute("readonly");
  await userEvent.click(option);
  expect(identifier).toHaveValue("claude-sonnet-test");
});

test("disables submission for an unconfigured provider with an explanation", async () => {
  render(<NewEvaluationPage />);
  await userEvent.click(await screen.findByRole("radio", { name: /OpenAI compatible/ }));
  expect(screen.getByRole("button", { name: "Start evaluation" })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent(/cannot start yet/i);
});
