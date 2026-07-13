import { fireEvent, render, screen } from "@testing-library/react";
import { ActionTimeline } from "@/components/action-timeline";
import { CompatibilityWarning, EmptyState, EpisodeCard, LoadingState } from "@/components/ui";
import { CostRewardScatter, FailurePredicateChart, RewardBySeedChart, SuccessRateChart } from "@/components/charts";
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

test("renders useful empty and loading states", () => {
  const { rerender } = render(<EmptyState title="No runs" detail="Start a demo" />);
  expect(screen.getByRole("heading", { name: "No runs" })).toBeInTheDocument();
  rerender(<LoadingState rows={2} />);
  expect(screen.getByLabelText("Loading").children).toHaveLength(2);
});

test("renders compatibility warnings visibly", () => {
  render(<CompatibilityWarning warnings={["Compared evaluations differ in split."]} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Not a like-for-like leaderboard");
  expect(screen.getByText(/differ in split/)).toBeInTheDocument();
});

test("timeline renders sanitized request metadata and progressive rows", () => {
  const entries: TimelineEntry[] = Array.from({ length: 42 }, (_, index) => ({ sequence: index + 1, fake_tick: index, tool: "release.status", arguments: {}, result_summary: { ok: true }, request_bytes: 10, response_bytes: 20, duration_ms: 1, success: true, terminated: index === 41, truncated: false }));
  render(<ActionTimeline entries={entries} />);
  expect(screen.getAllByText("release.status")).toHaveLength(40);
  fireEvent.click(screen.getByRole("button", { name: "Show more actions" }));
  expect(screen.getAllByText("release.status")).toHaveLength(42);
});

test("episode card links to run inspection", () => {
  render(<EpisodeCard run={{ run_id: "run_123456789", provider: "scripted", model: "scripted-valid", seed: 0, attempt: 1, status: "completed", authoritative_reward: 1 }} />);
  expect(screen.getByRole("link", { name: /Inspect episode/ })).toHaveAttribute("href", "/runs/run_123456789");
  expect(screen.getByText("1")).toBeInTheDocument();
});

test("success chart uses a correct percentage scale transformation", () => {
  render(<SuccessRateChart groups={[group]} />);
  const data = JSON.parse(screen.getByTestId("bar-chart").getAttribute("data-chart") ?? "{}");
  expect(data.datasets[0].data).toEqual([50]);
  expect(screen.getByText("50%", { selector: "td" })).toBeInTheDocument();
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
