"use client";

import { useEffect, useMemo, useState } from "react";
import { Bar, Doughnut, Line, Scatter } from "react-chartjs-2";
import {
  BarElement, CategoryScale, Chart as ChartJS, Filler, Legend, LineElement,
  LinearScale, PointElement, Tooltip, ArcElement, type ChartData, type ChartOptions,
} from "chart.js";
import { motion, useReducedMotion } from "motion/react";
import type { ComparisonGroup } from "@/lib/types";
import { DataTable, EmptyState } from "./ui";
import { number, percent } from "@/lib/format";

ChartJS.register(CategoryScale, LinearScale, BarElement, LineElement, PointElement, ArcElement, Filler, Tooltip, Legend);

const palette = ["#4f8cff", "#8b78ff", "#1eb980", "#f2a93b", "#ed5c72", "#65c7df"];

function useChartTheme() {
  const [light, setLight] = useState(false);
  useEffect(() => {
    const read = () => setLight(document.documentElement.dataset.theme === "light");
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return { text: light ? "#3d4656" : "#aeb7c8", grid: light ? "#dfe3ea" : "#263044" };
}

function baseOptions(max?: number): ChartOptions<"bar" | "line" | "scatter"> {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 220 },
    plugins: { legend: { position: "bottom" }, tooltip: { intersect: false } },
    scales: {
      x: { beginAtZero: true },
      y: { beginAtZero: true, ...(max == null ? {} : { max }) },
    },
  };
}

export function ChartCard({ title, description, children, table, exportData }: { title: string; description: string; children: React.ReactNode; table?: React.ReactNode; exportData?: unknown }) {
  const reduce = useReducedMotion();
  function download() {
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
    const href = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = href;
    link.download = `${title.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}.json`;
    link.click();
    URL.revokeObjectURL(href);
  }
  return <motion.section className="chart-card" initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }}><div className="chart-head"><div><h2>{title}</h2><p>{description}</p></div>{exportData != null && <button className="icon-button" aria-label={`Export ${title} data`} onClick={download}>⇩</button>}</div><div className="chart-area">{children}</div>{table && <details className="chart-table"><summary>Accessible data table</summary>{table}</details>}</motion.section>;
}

function names(groups: ComparisonGroup[]) { return groups.map(group => group.model); }

export function SuccessRateChart({ groups }: { groups: ComparisonGroup[] }) {
  const theme = useChartTheme();
  const data = useMemo<ChartData<"bar">>(() => ({ labels: names(groups), datasets: [{ label: "Strict success rate", data: groups.map(g => (g.strict_success_rate ?? 0) * 100), backgroundColor: palette[0] }] }), [groups]);
  if (!groups.length) return <EmptyState title="No comparison data" detail="Select completed evaluations to render success rates." />;
  const options = baseOptions(100) as ChartOptions<"bar">; options.scales!.x!.grid = { color: theme.grid }; options.scales!.y!.grid = { color: theme.grid }; options.scales!.y!.ticks = { color: theme.text, callback: value => `${value}%` }; options.scales!.x!.ticks = { color: theme.text };
  return <ChartCard title="Success rate by model" description="Share of episodes receiving strict verifier score 1.0." exportData={data} table={<DataTable caption="Success rate by model" headers={["Model", "Success rate"]} rows={groups.map(g => [g.model, percent(g.strict_success_rate)])} />}><Bar data={data} options={options} /></ChartCard>;
}

export function RewardChart({ groups }: { groups: ComparisonGroup[] }) {
  const data = useMemo<ChartData<"bar">>(() => ({ labels: names(groups), datasets: [{ label: "Average", data: groups.map(g => g.average_reward ?? 0), backgroundColor: palette[0] }, { label: "Median", data: groups.map(g => g.median_reward ?? 0), backgroundColor: palette[1] }] }), [groups]);
  return <ChartCard title="Average and median reward" description="Authoritative reward copied from immutable records." exportData={data} table={<DataTable caption="Reward by model" headers={["Model", "Average", "Median"]} rows={groups.map(g => [g.model, number(g.average_reward), number(g.median_reward)])} />}><Bar data={data} options={baseOptions(1) as ChartOptions<"bar">} /></ChartCard>;
}

export function RewardDistributionChart({ groups }: { groups: ComparisonGroup[] }) {
  const labels = ["0", "(0, .25]", "(.25, .5]", "(.5, .75]", "(.75, <1)", "1"];
  function bucket(value: number) {
    if (value === 0) return 0;
    if (value <= .25) return 1;
    if (value <= .5) return 2;
    if (value <= .75) return 3;
    if (value < 1) return 4;
    return 5;
  }
  const data: ChartData<"bar"> = {
    labels,
    datasets: groups.map((group, index) => {
      const counts = labels.map(() => 0);
      group.results_by_seed.forEach(run => { counts[bucket(run.reward)] += 1; });
      return { label: group.model, data: counts, backgroundColor: palette[index % palette.length] };
    }),
  };
  return <ChartCard title="Reward distribution" description="Episode counts in fixed authoritative reward bands." exportData={data}><Bar data={data} options={baseOptions() as ChartOptions<"bar">} /></ChartCard>;
}

export function RewardBySeedChart({ groups }: { groups: ComparisonGroup[] }) {
  const seeds = Array.from(new Set(groups.flatMap(g => g.results_by_seed.map(r => r.seed)))).sort((a, b) => a - b);
  const data = useMemo<ChartData<"line">>(() => ({ labels: seeds, datasets: groups.map((group, index) => ({ label: group.model, data: seeds.map(seed => { const values = group.results_by_seed.filter(r => r.seed === seed).map(r => r.reward); return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null; }), borderColor: palette[index % palette.length], backgroundColor: palette[index % palette.length], tension: 0.2, spanGaps: false })) }), [groups, seeds]);
  return <ChartCard title="Reward by seed" description="Mean authoritative reward for each seed across attempts." exportData={data}><Line data={data} options={baseOptions(1) as ChartOptions<"line">} /></ChartCard>;
}

function scatterData(groups: ComparisonGroup[], x: "cost" | "actions"): ChartData<"scatter"> {
  return { datasets: groups.map((group, index) => ({ label: group.model, data: group.results_by_seed.filter(run => x === "actions" || run.cost != null).map(run => ({ x: x === "cost" ? run.cost ?? 0 : run.actions, y: run.reward })), backgroundColor: palette[index % palette.length] })) };
}

export function CostRewardScatter({ groups }: { groups: ComparisonGroup[] }) {
  const data = useMemo(() => scatterData(groups, "cost"), [groups]);
  const hasCost = groups.some(group => group.results_by_seed.some(run => run.cost != null));
  return <ChartCard title="Cost versus reward" description="Configured provider cost against verifier reward." exportData={data}>{hasCost ? <Scatter data={data} options={baseOptions() as ChartOptions<"scatter">} /> : <EmptyState title="Cost data unavailable" detail="No compared run has configured price information." />}</ChartCard>;
}

export function ActionsRewardScatter({ groups }: { groups: ComparisonGroup[] }) {
  const data = useMemo(() => scatterData(groups, "actions"), [groups]);
  return <ChartCard title="Actions versus reward" description="Environment action count against authoritative reward." exportData={data}><Scatter data={data} options={baseOptions() as ChartOptions<"scatter">} /></ChartCard>;
}

export function OutcomeChart({ groups }: { groups: ComparisonGroup[] }) {
  const aggregate = groups.reduce<Record<string, number>>((all, group) => { Object.entries(group.outcome_distribution).forEach(([key, value]) => { all[key] = (all[key] ?? 0) + value; }); return all; }, {});
  const data: ChartData<"doughnut"> = { labels: Object.keys(aggregate), datasets: [{ data: Object.values(aggregate), backgroundColor: palette }] };
  return <ChartCard title="Outcome distribution" description="Strict verifier verdicts across selected batches." exportData={data}><Doughnut data={data} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } }} /></ChartCard>;
}

export function FailurePredicateChart({ groups }: { groups: ComparisonGroup[] }) {
  const predicates = Array.from(new Set(groups.flatMap(group => Object.keys(group.failed_predicate_frequency))));
  const data: ChartData<"bar"> = { labels: predicates, datasets: groups.map((group, index) => ({ label: group.model, data: predicates.map(name => group.failed_predicate_frequency[name] ?? 0), backgroundColor: palette[index % palette.length] })) };
  return <ChartCard title="Failed predicate frequency" description="Exact failed verifier predicate names exposed by the evaluation service." exportData={data}>{predicates.length ? <Bar data={data} options={{ ...(baseOptions() as ChartOptions<"bar">), indexAxis: "y" }} /> : <EmptyState title="No failed predicates" detail="All selected completed episodes satisfied strict verification." />}</ChartCard>;
}

export function TokenUsageChart({ groups }: { groups: ComparisonGroup[] }) {
  const data: ChartData<"bar"> = { labels: names(groups), datasets: [
    { label: "Average input tokens", data: groups.map(g => g.results_by_seed.length ? g.results_by_seed.reduce((sum, run) => sum + run.input_tokens, 0) / g.results_by_seed.length : 0), backgroundColor: palette[0] },
    { label: "Average output tokens", data: groups.map(g => g.results_by_seed.length ? g.results_by_seed.reduce((sum, run) => sum + run.output_tokens, 0) / g.results_by_seed.length : 0), backgroundColor: palette[2] },
  ] };
  return <ChartCard title="Token usage by model" description="Average input plus output tokens per completed episode." exportData={data}><Bar data={data} options={{ ...(baseOptions() as ChartOptions<"bar">), scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } } }} /></ChartCard>;
}

export function LatencyChart({ groups }: { groups: ComparisonGroup[] }) {
  const max = Math.max(1, ...groups.flatMap(group => group.results_by_seed.map(run => run.latency_ms || 0)));
  const size = max / 5;
  const labels = Array.from({ length: 5 }, (_, index) => `${number(index * size / 1000, 1)}–${number((index + 1) * size / 1000, 1)}s`);
  const data: ChartData<"bar"> = { labels, datasets: groups.map((group, index) => {
    const counts = labels.map(() => 0);
    group.results_by_seed.forEach(run => { counts[Math.min(4, Math.floor((run.latency_ms || 0) / size))] += 1; });
    return { label: group.model, data: counts, backgroundColor: palette[index % palette.length] };
  }) };
  return <ChartCard title="Latency distribution" description="End-to-end episode counts in shared latency buckets." exportData={data}><Bar data={data} options={baseOptions() as ChartOptions<"bar">} /></ChartCard>;
}

export function EpisodeRewardProgression({ rewards }: { rewards: Array<{ step: number; reward: number }> }) {
  const data: ChartData<"line"> = { labels: rewards.map(item => item.step), datasets: [{ label: "Authoritative step reward", data: rewards.map(item => item.reward), borderColor: palette[0], backgroundColor: palette[0] }] };
  return <ChartCard title="Episode reward progression" description="Shown only where the environment emitted valid step rewards." exportData={data}>{rewards.length ? <Line data={data} options={baseOptions(1) as ChartOptions<"line">} /> : <EmptyState title="No step rewards" detail="This episode emitted reward only at terminal strict grading." />}</ChartCard>;
}
