"use client";

import { Download, Maximize2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Bar, Doughnut, Line, Scatter } from "react-chartjs-2";
import {
  ArcElement, BarElement, CategoryScale, Chart as ChartJS, Filler, Legend, LineElement,
  LinearScale, PointElement, Tooltip, type ChartData, type ChartOptions, type ChartType,
} from "chart.js";
import { useReducedMotion } from "motion/react";
import type { ComparisonGroup } from "@/lib/types";
import { DataTable, EmptyState } from "@/components/ui";
import { MotionButton } from "@/components/motion";
import { number } from "@/lib/format";

ChartJS.register(CategoryScale, LinearScale, BarElement, LineElement, PointElement, ArcElement, Filler, Tooltip, Legend);

export type ChartViewMode = "chart" | "table";

export const MODEL_COLORS = ["#5b91ff", "#9a83ff", "#35c99a", "#f2b04e", "#ed6a7e", "#6dc9dc", "#d47ee8", "#75b66a"];

export function stableModelColor(provider: string, model: string): string {
  const key = `${provider}/${model}`;
  let hash = 0;
  for (let index = 0; index < key.length; index += 1) hash = ((hash << 5) - hash + key.charCodeAt(index)) | 0;
  return MODEL_COLORS[Math.abs(hash) % MODEL_COLORS.length];
}

function modelColor(group: ComparisonGroup, alpha = "ff") {
  return `${stableModelColor(group.provider, group.model)}${alpha}`;
}

function useChartTheme() {
  const [light, setLight] = useState(false);
  const reduce = useReducedMotion();
  useEffect(() => {
    const read = () => setLight(document.documentElement.dataset.theme === "light");
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return { text: light ? "#4f5c70" : "#aab6c9", grid: light ? "#dce3ed" : "#273247", border: light ? "#c8d1df" : "#39465e", reduce };
}

function useCartesianOptions<T extends "bar" | "line" | "scatter">({ max, indexAxis, points = 0 }: { max?: number; indexAxis?: "x" | "y"; points?: number } = {}): ChartOptions<T> {
  const theme = useChartTheme();
  return useMemo(() => ({
    responsive: true,
    maintainAspectRatio: false,
    indexAxis,
    animation: theme.reduce || points > 80 ? false : { duration: 220 },
    interaction: { intersect: false, mode: "nearest" },
    plugins: {
      legend: { position: "bottom", labels: { color: theme.text, usePointStyle: true, pointStyle: "circle", padding: 18 } },
      tooltip: { intersect: false, padding: 11, displayColors: true },
    },
    scales: {
      x: { beginAtZero: true, grid: { color: theme.grid }, border: { color: theme.border }, ticks: { color: theme.text, maxRotation: 0, autoSkip: true } },
      y: { beginAtZero: true, ...(max == null ? {} : { max }), grid: { color: theme.grid }, border: { color: theme.border }, ticks: { color: theme.text } },
    },
    elements: { bar: { borderRadius: 6, borderSkipped: false }, line: { borderWidth: 2, tension: 0.22 }, point: { radius: 4, hoverRadius: 6 } },
  }) as unknown as ChartOptions<T>, [indexAxis, max, points, theme.border, theme.grid, theme.reduce, theme.text]);
}

function displayDatum(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "object" && "x" in value && "y" in value) return `${String(value.x)}, ${String(value.y)}`;
  return String(value);
}

function chartRows<T extends ChartType>(data: ChartData<T>): ReactNode[][] {
  const labels = data.labels?.map(label => String(label)) ?? [];
  const length = Math.max(labels.length, ...data.datasets.map(dataset => dataset.data.length));
  return Array.from({ length }, (_, index) => [labels[index] ?? String(index + 1), ...data.datasets.map(dataset => displayDatum(dataset.data[index]))]);
}

export function chartDataToCsv<T extends ChartType>(data: ChartData<T>): string {
  const escape = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const headers = ["Label", ...data.datasets.map(dataset => dataset.label ?? "Series")];
  return [headers, ...chartRows(data)].map(row => row.map(escape).join(",")).join("\n");
}

function ChartCard<T extends ChartType>({ title, description, data, children, mode = "chart" }: { title: string; description: string; data: ChartData<T>; children: ReactNode; mode?: ChartViewMode }) {
  const [fullscreen, setFullscreen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const table = <DataTable caption={`${title} data`} headers={["Label", ...data.datasets.map(dataset => dataset.label ?? "Series")]} rows={chartRows(data)} />;
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (fullscreen && !dialog.open) dialog.showModal();
    if (!fullscreen && dialog.open) dialog.close();
  }, [fullscreen]);
  function download() {
    const blob = new Blob([chartDataToCsv(data)], { type: "text/csv;charset=utf-8" });
    const href = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = href;
    link.download = `${title.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}.csv`;
    link.click();
    URL.revokeObjectURL(href);
  }
  return <section className="chart-card"><div className="chart-head"><div><h2>{title}</h2><p>{description}</p></div><div className="chart-actions"><MotionButton className="icon-button" aria-label={`Export ${title} CSV`} onClick={download}><Download size={15} aria-hidden="true" /></MotionButton><MotionButton className="icon-button" aria-label={`Open ${title} fullscreen`} onClick={() => setFullscreen(true)}><Maximize2 size={15} aria-hidden="true" /></MotionButton></div></div>{mode === "chart" ? <><div className="chart-area">{children}</div><details className="chart-table"><summary>Accessible data table</summary>{table}</details></> : <div className="chart-table-mode">{table}</div>}<dialog ref={dialogRef} className="chart-dialog" onCancel={() => setFullscreen(false)} onClose={() => setFullscreen(false)}><div className="chart-dialog-head"><div><span className="eyebrow">Expanded chart</span><h2>{title}</h2></div><MotionButton className="icon-button" aria-label={`Close ${title} fullscreen`} onClick={() => setFullscreen(false)}><X size={17} aria-hidden="true" /></MotionButton></div><div className="chart-dialog-area">{fullscreen && children}</div></dialog></section>;
}

function names(groups: ComparisonGroup[]) { return groups.map(group => group.model); }

export function SuccessRateChart({ groups, mode }: { groups: ComparisonGroup[]; mode?: ChartViewMode }) {
  const theme = useChartTheme();
  const data = useMemo<ChartData<"bar">>(() => ({ labels: names(groups), datasets: [{ label: "Strict success rate (%)", data: groups.map(group => (group.strict_success_rate ?? 0) * 100), backgroundColor: groups.map(group => modelColor(group, "dd")), borderColor: groups.map(group => modelColor(group)), borderWidth: 1 }] }), [groups]);
  const options = useCartesianOptions<"bar">({ max: 100, points: groups.length });
  if (!groups.length) return <EmptyState title="No comparison data" detail="Select completed evaluations to render success rates." />;
  return <ChartCard title="Success rate by model" description="Share of episodes receiving strict verifier score 1.0." data={data} mode={mode}><Bar data={data} options={{ ...options, scales: { ...options.scales, y: { ...options.scales?.y, ticks: { color: theme.text, callback: value => `${value}%` } } } }} /></ChartCard>;
}

export function RewardChart({ groups, mode }: { groups: ComparisonGroup[]; mode?: ChartViewMode }) {
  const data = useMemo<ChartData<"bar">>(() => ({ labels: names(groups), datasets: [{ label: "Average", data: groups.map(group => group.average_reward ?? 0), backgroundColor: groups.map(group => modelColor(group, "dd")) }, { label: "Median", data: groups.map(group => group.median_reward ?? 0), backgroundColor: groups.map(group => modelColor(group, "77")) }] }), [groups]);
  const options = useCartesianOptions<"bar">({ max: 1, points: groups.length * 2 });
  return <ChartCard title="Average and median reward" description="Authoritative reward copied from immutable records." data={data} mode={mode}><Bar data={data} options={options} /></ChartCard>;
}

export function RewardDistributionChart({ groups, mode }: { groups: ComparisonGroup[]; mode?: ChartViewMode }) {
  const labels = ["0", "(0, .25]", "(.25, .5]", "(.5, .75]", "(.75, <1)", "1"];
  const data = useMemo<ChartData<"bar">>(() => ({ labels, datasets: groups.map(group => {
    const counts = labels.map(() => 0);
    group.results_by_seed.forEach(run => { const bucket = run.reward === 0 ? 0 : run.reward <= .25 ? 1 : run.reward <= .5 ? 2 : run.reward <= .75 ? 3 : run.reward < 1 ? 4 : 5; counts[bucket] += 1; });
    return { label: group.model, data: counts, backgroundColor: modelColor(group, "cc") };
  }) }), [groups]);
  const options = useCartesianOptions<"bar">({ points: groups.reduce((sum, group) => sum + group.results_by_seed.length, 0) });
  return <ChartCard title="Reward distribution" description="Episode counts in fixed authoritative reward bands." data={data} mode={mode}><Bar data={data} options={options} /></ChartCard>;
}

export function RewardBySeedChart({ groups, mode }: { groups: ComparisonGroup[]; mode?: ChartViewMode }) {
  const seeds = useMemo(() => Array.from(new Set(groups.flatMap(group => group.results_by_seed.map(run => run.seed)))).sort((a, b) => a - b), [groups]);
  const data = useMemo<ChartData<"line">>(() => ({ labels: seeds, datasets: groups.map(group => ({ label: group.model, data: seeds.map(seed => { const values = group.results_by_seed.filter(run => run.seed === seed).map(run => run.reward); return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null; }), borderColor: modelColor(group), backgroundColor: modelColor(group), spanGaps: false })) }), [groups, seeds]);
  const options = useCartesianOptions<"line">({ max: 1, points: seeds.length * groups.length });
  return <ChartCard title="Reward by seed" description="Mean authoritative reward for each seed across attempts." data={data} mode={mode}><Line data={data} options={options} /></ChartCard>;
}

function scatterData(groups: ComparisonGroup[], x: "cost" | "actions"): ChartData<"scatter"> {
  return { datasets: groups.map(group => ({ label: group.model, data: group.results_by_seed.filter(run => x === "actions" || run.cost != null).map(run => ({ x: x === "cost" ? run.cost ?? 0 : run.actions, y: run.reward })), backgroundColor: modelColor(group), borderColor: modelColor(group) })) };
}

export function CostRewardScatter({ groups, mode }: { groups: ComparisonGroup[]; mode?: ChartViewMode }) {
  const data = useMemo(() => scatterData(groups, "cost"), [groups]);
  const options = useCartesianOptions<"scatter">({ points: groups.reduce((sum, group) => sum + group.results_by_seed.length, 0) });
  const hasCost = groups.some(group => group.results_by_seed.some(run => run.cost != null));
  return hasCost ? <ChartCard title="Cost versus reward" description="Configured provider cost against verifier reward." data={data} mode={mode}><Scatter data={data} options={options} /></ChartCard> : <section className="chart-card"><EmptyState title="Cost data unavailable" detail="No compared run has configured price information." /></section>;
}

export function ActionsRewardScatter({ groups, mode }: { groups: ComparisonGroup[]; mode?: ChartViewMode }) {
  const data = useMemo(() => scatterData(groups, "actions"), [groups]);
  const options = useCartesianOptions<"scatter">({ points: groups.reduce((sum, group) => sum + group.results_by_seed.length, 0) });
  return <ChartCard title="Actions versus reward" description="Environment action count against authoritative reward." data={data} mode={mode}><Scatter data={data} options={options} /></ChartCard>;
}

export function OutcomeChart({ groups, mode }: { groups: ComparisonGroup[]; mode?: ChartViewMode }) {
  const theme = useChartTheme();
  const data = useMemo<ChartData<"doughnut">>(() => {
    const aggregate = groups.reduce<Record<string, number>>((all, group) => { Object.entries(group.outcome_distribution).forEach(([key, value]) => { all[key] = (all[key] ?? 0) + value; }); return all; }, {});
    return { labels: Object.keys(aggregate), datasets: [{ label: "Episodes", data: Object.values(aggregate), backgroundColor: Object.keys(aggregate).map(key => key === "pass" ? "#35c99a" : key === "partial" ? "#f2b04e" : key === "fail" ? "#ed6a7e" : "#8b98ac") }] };
  }, [groups]);
  const points = data.datasets[0]?.data.length ?? 0;
  const options = useMemo<ChartOptions<"doughnut">>(() => ({ responsive: true, maintainAspectRatio: false, animation: theme.reduce || points > 80 ? false : { duration: 220 }, cutout: "62%", plugins: { legend: { position: "bottom", labels: { color: theme.text, usePointStyle: true, pointStyle: "circle" } } } }), [points, theme.reduce, theme.text]);
  return <ChartCard title="Outcome distribution" description="Strict verifier verdicts across selected batches." data={data} mode={mode}><Doughnut data={data} options={options} /></ChartCard>;
}

export function FailurePredicateChart({ groups, mode }: { groups: ComparisonGroup[]; mode?: ChartViewMode }) {
  const predicates = useMemo(() => Array.from(new Set(groups.flatMap(group => Object.keys(group.failed_predicate_frequency)))), [groups]);
  const data = useMemo<ChartData<"bar">>(() => ({ labels: predicates, datasets: groups.map(group => ({ label: group.model, data: predicates.map(name => group.failed_predicate_frequency[name] ?? 0), backgroundColor: modelColor(group, "cc") })) }), [groups, predicates]);
  const options = useCartesianOptions<"bar">({ indexAxis: "y", points: predicates.length * groups.length });
  return predicates.length ? <ChartCard title="Failed predicate frequency" description="Exact failed verifier predicate names exposed by the evaluation service." data={data} mode={mode}><Bar data={data} options={options} /></ChartCard> : <section className="chart-card"><EmptyState title="No failed predicates" detail="All selected completed episodes satisfied strict verification." /></section>;
}

export function TokenUsageChart({ groups, mode }: { groups: ComparisonGroup[]; mode?: ChartViewMode }) {
  const data = useMemo<ChartData<"bar">>(() => ({ labels: names(groups), datasets: [{ label: "Average input tokens", data: groups.map(group => group.results_by_seed.length ? group.results_by_seed.reduce((sum, run) => sum + run.input_tokens, 0) / group.results_by_seed.length : 0), backgroundColor: groups.map(group => modelColor(group, "dd")) }, { label: "Average output tokens", data: groups.map(group => group.results_by_seed.length ? group.results_by_seed.reduce((sum, run) => sum + run.output_tokens, 0) / group.results_by_seed.length : 0), backgroundColor: groups.map(group => modelColor(group, "66")) }] }), [groups]);
  const base = useCartesianOptions<"bar">({ points: groups.length * 2 });
  const options = useMemo<ChartOptions<"bar">>(() => ({ ...base, scales: { x: { ...base.scales?.x, stacked: true }, y: { ...base.scales?.y, stacked: true, beginAtZero: true } } }), [base]);
  return <ChartCard title="Token usage by model" description="Average input plus output tokens per completed episode." data={data} mode={mode}><Bar data={data} options={options} /></ChartCard>;
}

export function LatencyChart({ groups, mode }: { groups: ComparisonGroup[]; mode?: ChartViewMode }) {
  const max = Math.max(1, ...groups.flatMap(group => group.results_by_seed.map(run => run.latency_ms || 0)));
  const size = max / 5;
  const labels = Array.from({ length: 5 }, (_, index) => `${number(index * size / 1000, 1)}–${number((index + 1) * size / 1000, 1)}s`);
  const data = useMemo<ChartData<"bar">>(() => ({ labels, datasets: groups.map(group => {
    const counts = labels.map(() => 0);
    group.results_by_seed.forEach(run => { counts[Math.min(4, Math.floor((run.latency_ms || 0) / size))] += 1; });
    return { label: group.model, data: counts, backgroundColor: modelColor(group, "cc") };
  }) }), [groups, labels, size]);
  const options = useCartesianOptions<"bar">({ points: groups.reduce((sum, group) => sum + group.results_by_seed.length, 0) });
  return <ChartCard title="Latency distribution" description="End-to-end episode counts in shared latency buckets." data={data} mode={mode}><Bar data={data} options={options} /></ChartCard>;
}

export function EpisodeRewardProgression({ rewards, mode = "chart" }: { rewards: Array<{ step: number; reward: number }>; mode?: ChartViewMode }) {
  const data = useMemo<ChartData<"line">>(() => ({ labels: rewards.map(item => item.step), datasets: [{ label: "Authoritative step reward", data: rewards.map(item => item.reward), borderColor: MODEL_COLORS[0], backgroundColor: MODEL_COLORS[0] }] }), [rewards]);
  const options = useCartesianOptions<"line">({ max: 1, points: rewards.length });
  return rewards.length ? <ChartCard title="Episode reward progression" description="Shown only where the environment emitted valid step rewards." data={data} mode={mode}><Line data={data} options={options} /></ChartCard> : <section className="chart-card"><EmptyState title="No step rewards" detail="This episode emitted reward only at terminal strict grading." /></section>;
}

export function TrainingCurveChart({ points, mode = "chart" }: { points: Array<{ epoch: number; loss: number; action_accuracy: number }>; mode?: ChartViewMode }) {
  const data = useMemo<ChartData<"line">>(() => ({ labels: points.map(point => point.epoch), datasets: [
    { label: "Loss", data: points.map(point => point.loss), borderColor: MODEL_COLORS[0], backgroundColor: MODEL_COLORS[0], yAxisID: "y" },
    { label: "Action accuracy", data: points.map(point => point.action_accuracy), borderColor: MODEL_COLORS[2], backgroundColor: MODEL_COLORS[2], yAxisID: "y1" },
  ] }), [points]);
  const base = useCartesianOptions<"line">({ points: points.length * 2 });
  const options = useMemo<ChartOptions<"line">>(() => ({ ...base, scales: {
    ...base.scales,
    y: { ...base.scales?.y, beginAtZero: true, position: "left" },
    y1: { beginAtZero: true, max: 1, position: "right", grid: { drawOnChartArea: false } },
  } }), [base]);
  return points.length ? <ChartCard title="Training progress" description="Live supervised loss and expert-action accuracy. The policy gate is evaluated separately." data={data} mode={mode}><Line data={data} options={options} /></ChartCard> : <section className="chart-card"><EmptyState title="No training epochs yet" detail="The curve will populate from replayable training events." /></section>;
}

export function TalonCalibrationChart({ bins, mode = "chart" }: { bins: Array<{ lower: number; upper: number; count: number; mean_confidence: number; gate_acceptance_rate: number }>; mode?: ChartViewMode }) {
  const populated = useMemo(() => bins.filter(bin => bin.count > 0), [bins]);
  const data = useMemo<ChartData<"line">>(() => ({ labels: populated.map(bin => `${Math.round(bin.lower * 100)}–${Math.round(bin.upper * 100)}%`), datasets: [
    { label: "Mean confidence", data: populated.map(bin => bin.mean_confidence), borderColor: MODEL_COLORS[0], backgroundColor: MODEL_COLORS[0] },
    { label: "Gate acceptance rate", data: populated.map(bin => bin.gate_acceptance_rate), borderColor: MODEL_COLORS[2], backgroundColor: MODEL_COLORS[2] },
  ] }), [populated]);
  const options = useCartesianOptions<"line">({ max: 1, points: populated.length * 2 });
  return populated.length ? <ChartCard title="Confidence calibration" description="Aggregate recommendation confidence versus public policy-gate acceptance; no hidden reference action is exposed." data={data} mode={mode}><Line data={data} options={options} /></ChartCard> : <section className="chart-card"><EmptyState title="Calibration pending" detail="Completed episodes will populate bounded confidence bins." /></section>;
}
