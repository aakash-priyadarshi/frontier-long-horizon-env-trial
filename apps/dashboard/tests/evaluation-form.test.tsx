import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import NewEvaluationPage from "@/app/evaluations/new/page";

const providers = {
  items: [
    { provider: "scripted", display_name: "Scripted", configured: true, ready: true, models: [{ id: "scripted-valid", display_name: "Scripted valid repair" }, { id: "scripted-wrong-control", display_name: "Scripted wrong-control repair" }], credential: { state: "not_required", source: "not_required", required: false }, endpoint: { state: "not_tested", tested_at: null }, authentication: { state: "not_required", tested_at: null }, model_discovery: { state: "discovered", count: 2, tested_at: null }, tool_calling: { state: "not_tested", tested_at: null }, base_url: null, capabilities: { temperature: false, reasoning_effort: false, deterministic: false, custom_model: false, custom_base_url: false, connection_test: false, model_discovery: false, tool_probe: false } },
    { provider: "openai-compatible", display_name: "OpenAI compatible", configured: false, ready: false, models: [], credential: { state: "missing", source: "missing", required: true }, endpoint: { state: "not_tested", tested_at: null }, authentication: { state: "not_tested", tested_at: null }, model_discovery: { state: "not_tested", count: 0, tested_at: null }, tool_calling: { state: "not_tested", tested_at: null }, base_url: "https://api.openai.com/v1", capabilities: { temperature: true, reasoning_effort: true, deterministic: true, custom_model: true, custom_base_url: true, connection_test: true, model_discovery: true, tool_probe: true } },
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

test("disables submission for an unconfigured provider with an explanation", async () => {
  render(<NewEvaluationPage />);
  await userEvent.click(await screen.findByRole("radio", { name: /OpenAI compatible/ }));
  expect(screen.getByRole("button", { name: "Start evaluation" })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent(/cannot start yet/i);
});
