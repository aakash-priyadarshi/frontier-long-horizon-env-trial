"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import type { Batch, ComparisonGroup } from "@/lib/types";
import { money, number, percent } from "@/lib/format";
import { ActionsRewardScatter, CostRewardScatter, FailurePredicateChart, LatencyChart, OutcomeChart, RewardBySeedChart, RewardChart, RewardDistributionChart, SuccessRateChart, TokenUsageChart } from "@/components/charts";
import { CompatibilityWarning, DataTable, EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/ui";

type Comparison = { groups: ComparisonGroup[]; compatibility_warnings: string[]; fair_comparison: boolean };

function CompareContent() {
  const search = useSearchParams();
  const initial = search.getAll("batch");
  const [batches, setBatches] = useState<Batch[]>([]);
  const [selected, setSelected] = useState<string[]>(initial);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api<{ items: Batch[] }>("/api/evaluations?limit=100").then(value => { setBatches(value.items); if (!initial.length) setSelected(value.items.slice(0, 2).map(item => item.batch_id)); }).catch(reason => setError(String(reason))); }, []);
  const load = useCallback(async () => {
    if (!selected.length) { setComparison(null); return; }
    try { const query = selected.map(id => `batch=${encodeURIComponent(id)}`).join("&"); setComparison(await api<Comparison>(`/api/comparisons?${query}`)); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to compare evaluations"); }
  }, [selected]);
  useEffect(() => { void load(); }, [load]);
  function toggle(id: string) { setSelected(values => values.includes(id) ? values.filter(value => value !== id) : [...values, id]); }
  return <>
    <PageHeader eyebrow="Evidence comparison" title="Compare model evaluations" description="Inspect outcome, efficiency, consistency, and configuration compatibility." />
    {error && <ErrorState message={error} retry={() => void load()} />}
    <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Selection</span><h2>Evaluation batches</h2></div><span className="muted">Choose two or more for a useful comparison</span></div>{batches.length ? <div className="batch-selector">{batches.map(batch => <label className={selected.includes(batch.batch_id) ? "batch-option selected" : "batch-option"} key={batch.batch_id}><input type="checkbox" checked={selected.includes(batch.batch_id)} onChange={() => toggle(batch.batch_id)} /><span><strong>{batch.model}</strong><small>{batch.provider} · {batch.split} · {batch.completed_runs}/{batch.total_runs} complete</small></span><code>{batch.batch_id.slice(-8)}</code></label>)}</div> : <EmptyState title="No completed evaluations" detail="Run the scripted demonstration twice to populate comparison evidence." />}</section>
    {!comparison && selected.length ? <LoadingState rows={4} /> : comparison && <>
      <CompatibilityWarning warnings={comparison.compatibility_warnings} />
      <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Summary</span><h2>Operating metrics</h2></div></div><DataTable caption="Model comparison summary" headers={["Model", "Success", "Avg / median reward", "Avg / median actions", "Tokens", "Latency", "Total cost", "Cost / success", "Truncation", "Provider errors", "Attempt consistency"]} rows={comparison.groups.map(group => [<strong key="model">{group.model}</strong>, percent(group.strict_success_rate), `${number(group.average_reward)} / ${number(group.median_reward)}`, `${number(group.average_actions, 1)} / ${number(group.median_actions, 1)}`, number(group.average_token_usage, 0), `${number((group.average_latency_ms ?? 0) / 1000, 1)}s`, money(group.estimated_total_cost), money(group.cost_per_success), percent(group.truncation_rate), percent(group.provider_error_rate), percent(group.consistency_across_attempts)])} /></section>
      <div className="chart-grid"><SuccessRateChart groups={comparison.groups} /><RewardChart groups={comparison.groups} /><RewardDistributionChart groups={comparison.groups} /><RewardBySeedChart groups={comparison.groups} /><CostRewardScatter groups={comparison.groups} /><ActionsRewardScatter groups={comparison.groups} /><OutcomeChart groups={comparison.groups} /><FailurePredicateChart groups={comparison.groups} /><TokenUsageChart groups={comparison.groups} /><LatencyChart groups={comparison.groups} /></div>
    </>}
  </>;
}

export default function ComparePage() {
  return <Suspense fallback={<LoadingState rows={5} />}><CompareContent /></Suspense>;
}
