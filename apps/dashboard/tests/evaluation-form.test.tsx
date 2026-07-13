import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import NewEvaluationPage from "@/app/evaluations/new/page";

const providers = {
  items: [
    { provider: "scripted", display_name: "Scripted", configured: true, models: [{ id: "scripted-valid", display_name: "Scripted valid repair" }, { id: "scripted-wrong-control", display_name: "Scripted wrong-control repair" }], capabilities: { temperature: false, reasoning_effort: false, deterministic: false, custom_model: false } },
    { provider: "openai-compatible", display_name: "OpenAI compatible", configured: false, models: [], capabilities: { temperature: true, reasoning_effort: true, deterministic: true, custom_model: true } },
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
  const provider = await screen.findByLabelText("Provider");
  expect(screen.getByLabelText("Model")).toHaveValue("scripted-valid");
  await userEvent.selectOptions(provider, "openai-compatible");
  expect(screen.getByPlaceholderText("provider/model-name")).toBeInTheDocument();
  expect(screen.getByLabelText("Temperature")).toBeInTheDocument();
  expect(screen.getByLabelText("Reasoning effort")).toBeInTheDocument();
  expect(screen.getByText("Not configured")).toBeInTheDocument();
});

test("hides unsupported scripted controls", async () => {
  render(<NewEvaluationPage />);
  await screen.findByText("Scripted valid repair");
  expect(screen.queryByLabelText("Temperature")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Reasoning effort")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Deterministic mode")).not.toBeInTheDocument();
});

test("validates explicit confirmation before submission", async () => {
  render(<NewEvaluationPage />);
  const button = await screen.findByRole("button", { name: "Run scripted demonstration" });
  fireEvent.click(button);
  expect(await screen.findByText(/Confirm the episode count/)).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("shows estimated episode count", async () => {
  render(<NewEvaluationPage />);
  await screen.findByText("Scripted valid repair");
  fireEvent.change(screen.getByLabelText("Number of seeds"), { target: { value: "3" } });
  fireEvent.change(screen.getByLabelText("Attempts per seed"), { target: { value: "2" } });
  expect(screen.getByText("6 episodes")).toBeInTheDocument();
});

test("disables submission for unconfigured provider", async () => {
  render(<NewEvaluationPage />);
  await userEvent.selectOptions(await screen.findByLabelText("Provider"), "openai-compatible");
  expect(screen.getByRole("button", { name: "Start evaluation" })).toBeDisabled();
});
