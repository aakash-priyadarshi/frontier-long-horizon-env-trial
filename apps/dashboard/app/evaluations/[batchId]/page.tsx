"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Activity, ArrowRight, Download, Radio, Square } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, eventUrl, exportUrl } from "@/lib/api";
import type { Batch } from "@/lib/types";
import { money, number, percent } from "@/lib/format";
import { MotionButton } from "@/components/motion";
import { AuthorityNotice, BatchProgress, BudgetProgress, CommitBadge, ConfirmDialog, EmptyState, EpisodeCard, ErrorState, LoadingState, MetricCard, PageHeader, RunStatusBadge } from "@/components/ui";

const terminalStatuses = new Set(["completed", "completed_with_errors", "cancelled", "interrupted"]);

export default function BatchPage() {
  const { batchId } = useParams<{ batchId: string }>();
  const [batch, setBatch] = useState<Batch | null>(null);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState<"connecting" | "connected" | "reconnecting">("connecting");
  const [confirmCancel, setConfirmCancel] = useState(false);
  const load = useCallback(async () => {
    try { setBatch(await api<Batch>(`/api/evaluations/${batchId}`)); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to load batch"); }
  }, [batchId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!batch || terminalStatuses.has(batch.status)) return;
    const events = new EventSource(eventUrl(`/api/evaluations/${batchId}/events`));
    let refreshTimer: number | undefined;
    const scheduleRefresh = () => {
      if (refreshTimer !== undefined) return;
      refreshTimer = window.setTimeout(() => { refreshTimer = undefined; void load(); }, 220);
    };
    events.onopen = () => setConnection("connected");
    events.onmessage = scheduleRefresh;
    ["run_started", "tool_completed", "model_response", "run_finished", "batch_finished", "batch_cancelling"].forEach(type => events.addEventListener(type, scheduleRefresh));
    events.onerror = () => setConnection("reconnecting");
    return () => { events.close(); if (refreshTimer !== undefined) window.clearTimeout(refreshTimer); };
  }, [batch?.status, batchId, load]);

  async function cancel() {
    try { await api(`/api/evaluations/${batchId}/cancel`, { method: "POST" }); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Cancellation failed"); }
  }
  const usage = useMemo(() => {
    const runs = batch?.runs ?? [];
    return {
      tokens: runs.reduce((sum, run) => sum + (run.input_tokens ?? 0) + (run.output_tokens ?? 0), 0),
      tokenLimit: runs.reduce((sum, run) => sum + (run.limits?.input_token_budget ?? 0) + (run.limits?.output_token_budget ?? 0), 0) || null,
      cost: runs.reduce((sum, run) => sum + (run.estimated_cost ?? 0), 0),
      costLimit: runs.reduce((sum, run) => sum + (run.limits?.cost_budget ?? 0), 0) || null,
    };
  }, [batch?.runs]);

  if (error && !batch) return <ErrorState message={error} retry={() => void load()} />;
  if (!batch) return <LoadingState rows={6} label="Loading live batch" />;
  const terminal = terminalStatuses.has(batch.status);
  const activeRuns = batch.runs?.filter(run => run.status === "running") ?? [];
  const latest = [...activeRuns, ...(batch.runs ?? []).filter(run => run.current_tool)].sort((a, b) => (b.current_step ?? 0) - (a.current_step ?? 0))[0];
  return <>
    <PageHeader eyebrow="Live batch" title={`${batch.provider} / ${batch.model}`} description={`${batch.split} split · seeds ${batch.seed_start}–${batch.seed_start + batch.seed_count - 1} · ${batch.attempts} attempt${batch.attempts === 1 ? "" : "s"}`} actions={<><a className="button secondary" href={exportUrl(batch.batch_id)}><Download size={16} aria-hidden="true" />Export JSON</a>{!terminal && <MotionButton className="button danger-button" onClick={() => setConfirmCancel(true)}><Square size={14} aria-hidden="true" />Cancel batch</MotionButton>}</>} />
    <AuthorityNotice />
    {error && <ErrorState message={error} retry={() => void load()} />}
    <section className="batch-identity"><div><code>{batch.batch_id}</code><RunStatusBadge status={batch.status} />{!terminal && <span className={`live-indicator ${connection}`}><Radio size={13} aria-hidden="true" />{connection === "connected" ? "Live stream connected" : connection === "reconnecting" ? "Reconnecting" : "Connecting"}</span>}</div><div><CommitBadge label="environment" value={batch.environment_commit} /><CommitBadge label="application" value={batch.application_commit} /></div></section>
    <section className={`live-batch-console${activeRuns.length ? " active" : ""}`} aria-live="polite"><div className="live-console-icon"><Activity size={20} aria-hidden="true" /></div><div><span className="eyebrow">Current activity</span><strong>{activeRuns.length ? `${activeRuns.length} episode${activeRuns.length === 1 ? "" : "s"} running` : terminal ? "Batch settled" : `${batch.queued_runs} episode${batch.queued_runs === 1 ? "" : "s"} queued`}</strong><p>{latest?.current_tool ? <>Latest environment tool: <code>{latest.current_tool}</code> at step {latest.current_step}</> : terminal ? "All available episode records are finalized." : "Waiting for the next authenticated environment action."}</p></div><RunStatusBadge status={batch.status} /></section>
    <BatchProgress total={batch.total_runs} completed={batch.completed_runs} failed={batch.failed_runs} cancelled={batch.cancelled_runs} />
    <section className="metric-grid six compact"><MetricCard label="Running" numericValue={batch.running_runs} /><MetricCard label="Completed" numericValue={batch.completed_runs} tone="success" /><MetricCard label="Failed" numericValue={batch.failed_runs} tone="danger" /><MetricCard label="Cancelled" numericValue={batch.cancelled_runs} /><MetricCard label="Strict success" value={percent(batch.aggregate_results.strict_success_rate)} emphasis /><MetricCard label="Average reward" value={number(batch.aggregate_results.average_reward)} /></section>
    <section className="batch-operations"><div><span className="eyebrow">Usage and budgets</span><BudgetProgress label="Tokens" value={usage.tokens} limit={usage.tokenLimit} /><BudgetProgress label="Estimated cost" value={usage.cost} limit={usage.costLimit} format={money} /></div><dl><div><dt>Average actions</dt><dd>{number(batch.aggregate_results.average_actions, 1)}</dd></div><div><dt>Cost per success</dt><dd>{money(batch.aggregate_results.average_cost_per_success)}</dd></div><div><dt>Queued</dt><dd>{batch.queued_runs}</dd></div></dl></section>
    <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Episodes</span><h2>Run matrix</h2></div><Link className="text-link link-with-icon" href={`/compare?batch=${batch.batch_id}`}>Open comparison <ArrowRight size={14} aria-hidden="true" /></Link></div>{batch.runs?.length ? <div className="episode-grid">{batch.runs.map(run => <EpisodeCard key={run.run_id} run={run} />)}</div> : <EmptyState title="Episodes are being prepared" detail="Queued runs will appear here as soon as orchestration starts." />}</section>
    <ConfirmDialog open={confirmCancel} title="Cancel this batch?" detail="Running provider requests will be interrupted when possible, and completed verifier records will remain available." confirmLabel="Cancel batch" onConfirm={() => void cancel()} onClose={() => setConfirmCancel(false)} />
  </>;
}
