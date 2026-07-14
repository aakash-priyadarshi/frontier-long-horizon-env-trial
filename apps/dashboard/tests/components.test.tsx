import { fireEvent, render, screen, within } from "@testing-library/react";
import { vi } from "vitest";
import { ActionTimeline } from "@/components/action-timeline";
import { chartDataToCsv, CostRewardScatter, FailurePredicateChart, RewardBySeedChart, stableModelColor, SuccessRateChart } from "@/components/charts";
import { MotionButton } from "@/components/motion";
import { CompatibilityWarning, EmptyState, EpisodeCard, ErrorState, LoadingState } from "@/components/ui";
import type { ComparisonGroup, TimelineEntry } from "@/lib/types";

const group: ComparisonGroup = {
  batch_id: "batch", provider: "scripted", model: "scripted-valid", environment_commit: "a".repeat(40), run_count: 2,
  strict_success_rate: 0.5, average_reward: 0.75, median_reward: 0.75,
  average_actions: 20, median_actions: 20, average_token_usage: 100, average_latency_ms: 500,
  estimated_total_cost: null, cost_per_success: null, truncation_rate: 0, provider_error_rate: 0,
  consistency_across_attempts: null,
  failed_predicate_frequency: { member_hidden_workloads_pass: 1 }, outcome_distribution: { pass: 1, partial: 1 },
  results_by_seed: [{ seed: 0, attempt: 1, reward: 1, actions: 20, input_tokens: 60, output_tokens: 40, tokens: 100, latency_ms: 500, cost: null }, { seed: 1, attempt: 1, reward: .5, actions: 20, input_tokens: 60, output_tokens: 40, tokens: 100, latency_ms: 500, cost: null }],
};

function timelineEntry(sequence: number, tool = "release.status"): TimelineEntry {
  return { sequence, fake_tick: sequence - 1, tool, arguments: { id: sequence }, result_summary: { ok: true }, request_bytes: 10, response_bytes: 20, duration_ms: 1, success: true, terminated: false, truncated: false };
}

test("renders useful empty and labelled skeleton loading states", () => {
  const { rerender } = render(<EmptyState title="No runs" detail="Start a demo" />);
  expect(screen.getByRole("heading", { name: "No runs" })).toBeInTheDocument();
  rerender(<LoadingState rows={2} />);
  const loading = screen.getByRole("status", { name: "Loading dashboard data" });
  expect(loading.querySelectorAll(".skeleton")).toHaveLength(2);
});

test("renders compatibility warnings visibly", () => {
  render(<CompatibilityWarning warnings={["Compared evaluations differ in split."]} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Not a like-for-like leaderboard");
  expect(screen.getByText(/differ in split/)).toBeInTheDocument();
});

test("error states provide an operable retry action", () => {
  const retry = vi.fn();
  render(<ErrorState message="Connection lost" retry={retry} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Connection lost");
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(retry).toHaveBeenCalledOnce();
});

test("timeline progressively renders, filters, and expands sanitized metadata", () => {
  const entries = Array.from({ length: 42 }, (_, index) => timelineEntry(index + 1));
  entries[0] = timelineEntry(1, "recovery.begin");
  render(<ActionTimeline entries={entries} />);
  expect(screen.getAllByText("release.status")).toHaveLength(39);
  fireEvent.click(screen.getByRole("button", { name: "Show 2 more actions" }));
  expect(screen.getAllByText("release.status")).toHaveLength(41);
  fireEvent.click(screen.getByRole("tab", { name: "Recovery 1" }));
  expect(screen.getByText("recovery.begin")).toBeInTheDocument();
  expect(screen.queryByText("release.status")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /recovery\.begin/ }));
  expect(screen.getByText("Sanitized request and result")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copy request to clipboard" })).toBeInTheDocument();
});

test("episode card expands before linking to run inspection", () => {
  render(<EpisodeCard run={{ run_id: "run_123456789", provider: "scripted", model: "scripted-valid", seed: 0, attempt: 1, status: "completed", authoritative_reward: 1 }} />);
  expect(screen.queryByRole("link", { name: /Inspect episode/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /run_123456789/ }));
  expect(screen.getByRole("link", { name: /Inspect episode/ })).toHaveAttribute("href", "/runs/run_123456789");
  expect(screen.getByText("1", { selector: "dd" })).toBeInTheDocument();
});

test("success chart uses a correct percentage scale and stable model colour", () => {
  render(<SuccessRateChart groups={[group]} />);
  const data = JSON.parse(screen.getByTestId("bar-chart").getAttribute("data-chart") ?? "{}");
  expect(data.datasets[0].data).toEqual([50]);
  expect(data.datasets[0].backgroundColor).toEqual([`${stableModelColor("scripted", "scripted-valid")}dd`]);
  expect(screen.getByText("50", { selector: "td" })).toBeInTheDocument();
  expect(stableModelColor("scripted", "scripted-valid")).toBe(stableModelColor("scripted", "scripted-valid"));
});

test("reward-by-seed chart preserves actual seed rewards", () => {
  render(<RewardBySeedChart groups={[group]} />);
  const data = JSON.parse(screen.getByTestId("line-chart").getAttribute("data-chart") ?? "{}");
  expect(data.labels).toEqual([0, 1]);
  expect(data.datasets[0].data).toEqual([1, 0.5]);
});

test("cost chart does not fabricate absent metrics", () => {
  render(<CostRewardScatter groups={[group]} />);
  expect(screen.getByRole("heading", { name: "Cost data unavailable" })).toBeInTheDocument();
  expect(screen.queryByTestId("scatter-chart")).not.toBeInTheDocument();
});

test("failed predicate chart renders exact exposed names", () => {
  render(<FailurePredicateChart groups={[group]} />);
  const data = JSON.parse(screen.getByTestId("bar-chart").getAttribute("data-chart") ?? "{}");
  expect(data.labels).toEqual(["member_hidden_workloads_pass"]);
});

test("chart table mode and CSV export expose equivalent data", () => {
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  render(<SuccessRateChart groups={[group]} mode="table" />);
  const table = screen.getByRole("table", { name: "Success rate by model data" });
  expect(within(table).getByText("scripted-valid")).toBeInTheDocument();
  expect(within(table).getByText("50")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Export Success rate by model CSV" }));
  expect(URL.createObjectURL).toHaveBeenCalledOnce();
  expect(click).toHaveBeenCalledOnce();
  expect(chartDataToCsv({ labels: ["scripted-valid"], datasets: [{ label: "Score", data: [50] }] })).toContain('"scripted-valid","50"');
});

test("motion buttons retain focus and tap behavior", () => {
  const onClick = vi.fn();
  render(<MotionButton onClick={onClick}>Run evaluation</MotionButton>);
  const button = screen.getByRole("button", { name: "Run evaluation" });
  button.focus();
  fireEvent.pointerDown(button);
  fireEvent.pointerUp(button);
  fireEvent.click(button);
  expect(button).toHaveFocus();
  expect(onClick).toHaveBeenCalledOnce();
});
