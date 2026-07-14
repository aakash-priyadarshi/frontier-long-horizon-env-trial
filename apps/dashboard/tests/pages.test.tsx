import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import OverviewPage from "@/app/page";
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

test("responsive navigation has accessible controls", () => {
  render(<AppShell><p>Content</p></AppShell>);
  expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Open navigation" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Switch to light theme/ })).toBeInTheDocument();
  expect(screen.getByText("Content")).toBeInTheDocument();
});

test("theme choice is persisted without storing provider data", () => {
  render(<AppShell><p>Content</p></AppShell>);
  fireEvent.click(screen.getByRole("button", { name: /Switch to light theme/ }));
  expect(localStorage.getItem("frontier-theme")).toBe("light");
  expect([...Array(localStorage.length)].map((_, index) => localStorage.key(index))).toEqual(["frontier-theme"]);
});

test("reduced motion preference remains operable", () => {
  vi.mocked(window.matchMedia).mockImplementation((query: string) => ({ matches: query.includes("prefers-reduced-motion"), media: query, onchange: null, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() }));
  render(<AppShell><button>Immediate control</button></AppShell>);
  expect(screen.getByRole("button", { name: "Immediate control" })).toBeEnabled();
});
