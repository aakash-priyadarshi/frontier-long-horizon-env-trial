"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { BarChart3, Check, Table2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { api } from "@/lib/api";
import type { Batch, ComparisonGroup } from "@/lib/types";
import { money, number, percent } from "@/lib/format";
import { ActionsRewardScatter, CostRewardScatter, FailurePredicateChart, LatencyChart, OutcomeChart, RewardBySeedChart, RewardChart, RewardDistributionChart, SuccessRateChart, TokenUsageChart, stableModelColor, type ChartViewMode } from "@/components/charts";
import { CompatibilityWarning, DataTable, EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { MotionButton } from "@/components/motion";

type Comparison = { groups: ComparisonGroup[]; compatibility_warnings: string[]; fair_comparison: boolean };

function CompareContent() {
  const search = useSearchParams();
  const initial = search.getAll("batch");
  const [batches, setBatches] = useState<Batch[]>([]);
  const [selected, setSelected] = useState<string[]>(initial);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [error, setError] = useState("");
  const [viewMode, setViewMode] = useState<ChartViewMode>("chart");
  const [completedOnly, setCompletedOnly] = useState(true);
  const [hiddenModels, setHiddenModels] = useState<string[]>([]);
  useEffect(() => { api<{ items: Batch[] }>("/api/evaluations?limit=100").then(value => { setBatches(value.items); if (!initial.length) setSelected(value.items.slice(0, 2).map(item => item.batch_id)); }).catch(reason => setError(String(reason))); }, []);
  const load = useCallback(async () => {
    if (!selected.length) { setComparison(null); return; }
    try { const query = selected.map(id => `batch=${encodeURIComponent(id)}`).join("&"); setComparison(await api<Comparison>(`/api/comparisons?${query}`)); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to compare evaluations"); }
  }, [selected]);
  useEffect(() => { void load(); }, [load]);
  function toggle(id: string) { setSelected(values => values.includes(id) ? values.filter(value => value !== id) : [...values, id]); }
  const visibleBatches = completedOnly ? batches.filter(batch => ["completed", "completed_with_errors"].includes(batch.status)) : batches;
  const groupKey = (group: ComparisonGroup) => `${group.provider}/${group.model}`;
  const groups = comparison?.groups.filter(group => !hiddenModels.includes(groupKey(group))) ?? [];
  return <>
    <PageHeader eyebrow="Evidence comparison" title="Compare model evaluations" description="Inspect outcome, efficiency, consistency, and configuration compatibility." />
    {error && <ErrorState message={error} retry={() => void load()} />}
    <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Selection</span><h2>Evaluation batches</h2></div><label className="compact-toggle"><input type="checkbox" checked={completedOnly} onChange={event => setCompletedOnly(event.target.checked)} /><span>Completed only</span></label></div>{visibleBatches.length ? <div className="batch-selector">{visibleBatches.map(batch => <label className={selected.includes(batch.batch_id) ? "batch-option selected" : "batch-option"} key={batch.batch_id}><input type="checkbox" checked={selected.includes(batch.batch_id)} onChange={() => toggle(batch.batch_id)} /><span><strong>{batch.model}</strong><small>{batch.provider} · {batch.split} · {batch.completed_runs}/{batch.total_runs} complete</small></span><code>{batch.batch_id.slice(-8)}</code>{selected.includes(batch.batch_id) && <Check className="batch-selected-check" size={14} aria-hidden="true" />}</label>)}</div> : <EmptyState title="No matching evaluations" detail={completedOnly ? "No completed batches are available. Turn off the completed-only filter or run the scripted demonstration." : "Run the scripted demonstration to populate comparison evidence."} />}</section>
    {!comparison && selected.length ? <LoadingState rows={4} /> : comparison && <>
      <CompatibilityWarning warnings={comparison.compatibility_warnings} />
      <section className="comparison-controls" aria-label="Chart controls"><div><span className="eyebrow">Display</span><div className="segmented-control" role="group" aria-label="Comparison display mode"><MotionButton aria-pressed={viewMode === "chart"} className={viewMode === "chart" ? "active" : ""} onClick={() => setViewMode("chart")}><BarChart3 size={15} aria-hidden="true" />Charts</MotionButton><MotionButton aria-pressed={viewMode === "table"} className={viewMode === "table" ? "active" : ""} onClick={() => setViewMode("table")}><Table2 size={15} aria-hidden="true" />Tables</MotionButton></div></div><div><span className="eyebrow">Visible models</span><div className="model-visibility">{comparison.groups.map(group => { const key = groupKey(group); const visible = !hiddenModels.includes(key); return <MotionButton aria-pressed={visible} className={visible ? "active" : ""} key={key} onClick={() => setHiddenModels(values => visible ? [...values, key] : values.filter(value => value !== key))}><span className="model-color-dot" style={{ backgroundColor: stableModelColor(group.provider, group.model) }} />{group.model}</MotionButton>; })}</div></div></section>
      <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Summary</span><h2>Operating metrics</h2></div></div><DataTable caption="Model comparison summary" headers={["Model", "Success", "Avg / median reward", "Avg / median actions", "Tokens", "Latency", "Total cost", "Cost / success", "Truncation", "Provider errors", "Attempt consistency"]} rows={comparison.groups.map(group => [<strong key="model">{group.model}</strong>, percent(group.strict_success_rate), `${number(group.average_reward)} / ${number(group.median_reward)}`, `${number(group.average_actions, 1)} / ${number(group.median_actions, 1)}`, number(group.average_token_usage, 0), `${number((group.average_latency_ms ?? 0) / 1000, 1)}s`, money(group.estimated_total_cost), money(group.cost_per_success), percent(group.truncation_rate), percent(group.provider_error_rate), percent(group.consistency_across_attempts)])} /></section>
      <AnimatePresence mode="wait"><motion.div className="chart-grid" key={viewMode} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>{groups.length ? <><SuccessRateChart groups={groups} mode={viewMode} /><RewardChart groups={groups} mode={viewMode} /><RewardDistributionChart groups={groups} mode={viewMode} /><RewardBySeedChart groups={groups} mode={viewMode} /><CostRewardScatter groups={groups} mode={viewMode} /><ActionsRewardScatter groups={groups} mode={viewMode} /><OutcomeChart groups={groups} mode={viewMode} /><FailurePredicateChart groups={groups} mode={viewMode} /><TokenUsageChart groups={groups} mode={viewMode} /><LatencyChart groups={groups} mode={viewMode} /></> : <EmptyState title="All models are hidden" detail="Turn on at least one model to render comparison evidence." />}</motion.div></AnimatePresence>
    </>}
  </>;
}

export default function ComparePage() {
  return <Suspense fallback={<LoadingState rows={5} />}><CompareContent /></Suspense>;
}
