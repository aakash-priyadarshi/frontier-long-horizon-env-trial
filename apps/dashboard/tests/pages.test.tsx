import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import OverviewPage from "@/app/page";
import SettingsPage from "@/app/settings/page";
import { AppShell } from "@/components/app-shell";

function response(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response);
}

test("overview renders the scripted empty state and authority disclaimer", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => url.includes("providers") ? response({ items: [{ configured: true }] }) : response({ overview: { total_evaluations: 0, total_completed_episodes: 0, strict_success_rate: null, average_reward: null, average_actions: null, average_cost_per_success: null }, recent_batches: [], recent_failures: [], environment_commit: "a".repeat(40), frozen_v1_tag: "b".repeat(40) })));
  render(<OverviewPage />);
  expect(await screen.findByRole("heading", { name: "No evaluations yet" })).toBeInTheDocument();
  expect(screen.getByText(/Scores are read-only/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run scripted demonstration" })).toBeInTheDocument();
});

test("settings never renders unexpected secret fields", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response({ items: [{ provider: "anthropic", display_name: "Anthropic", configured: true, secret: "do-not-render", models: [], capabilities: { custom_model: true, temperature: true, reasoning_effort: false, deterministic: true } }] })));
  render(<SettingsPage />);
  expect(await screen.findByRole("heading", { name: "Anthropic" })).toBeInTheDocument();
  expect(screen.queryByText("do-not-render")).not.toBeInTheDocument();
  expect(screen.getByText(/Keys never reach the browser/)).toBeInTheDocument();
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
