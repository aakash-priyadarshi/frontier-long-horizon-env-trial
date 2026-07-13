"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, eventUrl, exportUrl } from "@/lib/api";
import type { Batch } from "@/lib/types";
import { money, number, percent } from "@/lib/format";
import { AuthorityNotice, BatchProgress, CommitBadge, EmptyState, EpisodeCard, ErrorState, LoadingState, MetricCard, PageHeader, RunStatusBadge } from "@/components/ui";

export default function BatchPage() {
  const { batchId } = useParams<{ batchId: string }>();
  const [batch, setBatch] = useState<Batch | null>(null);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const load = useCallback(async () => {
    try { setBatch(await api<Batch>(`/api/evaluations/${batchId}`)); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to load batch"); }
  }, [batchId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!batch || ["completed", "completed_with_errors", "cancelled", "interrupted"].includes(batch.status)) return;
    const events = new EventSource(eventUrl(`/api/evaluations/${batchId}/events`));
    events.onopen = () => setConnected(true);
    events.onmessage = () => void load();
    ["run_started", "tool_completed", "model_response", "run_finished", "batch_finished", "batch_cancelling"].forEach(type => events.addEventListener(type, () => void load()));
    events.onerror = () => setConnected(false);
    return () => events.close();
  }, [batch?.status, batchId, load]);

  async function cancel() {
    try { await api(`/api/evaluations/${batchId}/cancel`, { method: "POST" }); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Cancellation failed"); }
  }
  if (error && !batch) return <ErrorState message={error} retry={() => void load()} />;
  if (!batch) return <LoadingState rows={6} />;
  const terminal = ["completed", "completed_with_errors", "cancelled", "interrupted"].includes(batch.status);
  return <>
    <PageHeader eyebrow="Live batch" title={`${batch.provider} / ${batch.model}`} description={`${batch.split} split · seeds ${batch.seed_start}–${batch.seed_start + batch.seed_count - 1} · ${batch.attempts} attempt${batch.attempts === 1 ? "" : "s"}`} actions={<><a className="button secondary" href={exportUrl(batch.batch_id)}>Export JSON</a>{!terminal && <button className="button danger-button" onClick={cancel}>Cancel batch</button>}</>} />
    <AuthorityNotice />
    <section className="batch-identity"><div><code>{batch.batch_id}</code><RunStatusBadge status={batch.status} />{!terminal && <span className={connected ? "live-indicator connected" : "live-indicator"}><span />{connected ? "Live stream connected" : "Reconnecting"}</span>}</div><div><CommitBadge label="environment" value={batch.environment_commit} /><CommitBadge label="application" value={batch.application_commit} /></div></section>
    <BatchProgress total={batch.total_runs} completed={batch.completed_runs} failed={batch.failed_runs} cancelled={batch.cancelled_runs} />
    <section className="metric-grid six compact"><MetricCard label="Running" value={batch.running_runs} /><MetricCard label="Completed" value={batch.completed_runs} tone="success" /><MetricCard label="Failed" value={batch.failed_runs} tone="danger" /><MetricCard label="Cancelled" value={batch.cancelled_runs} /><MetricCard label="Strict success" value={percent(batch.aggregate_results.strict_success_rate)} /><MetricCard label="Average reward" value={number(batch.aggregate_results.average_reward)} /></section>
    <section className="metric-grid four compact"><MetricCard label="Average actions" value={number(batch.aggregate_results.average_actions, 1)} /><MetricCard label="Estimated cost" value={money(batch.aggregate_results.estimated_total_cost)} /><MetricCard label="Cost per success" value={money(batch.aggregate_results.average_cost_per_success)} /><MetricCard label="Queued" value={batch.queued_runs} /></section>
    <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Episodes</span><h2>Run matrix</h2></div><Link className="text-link" href={`/compare?batch=${batch.batch_id}`}>Open comparison →</Link></div>{batch.runs?.length ? <div className="episode-grid">{batch.runs.map(run => <EpisodeCard key={run.run_id} run={run} />)}</div> : <EmptyState title="Episodes are being prepared" detail="Queued runs will appear here as soon as orchestration starts." />}</section>
  </>;
}
