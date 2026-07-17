"use client";

import Link from "next/link";
import { Activity, ArrowRight, FlaskConical, Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Batch, Provider, Run } from "@/lib/types";
import { money, number, percent } from "@/lib/format";
import { MotionButton } from "@/components/motion";
import { AuthorityNotice, CommitBadge, DataTable, EmptyState, ErrorState, InlineLoading, LoadingState, MetricCard, RunStatusBadge } from "@/components/ui";

type Health = {
  overview: { total_evaluations: number; total_completed_episodes: number; strict_success_rate: number | null; average_reward: number | null; average_actions: number | null; average_cost_per_success: number | null };
  recent_batches: Batch[];
  recent_failures: Run[];
  environment_commit: string;
  frozen_v1_tag: string;
};

const terminalStatuses = new Set(["completed", "completed_with_errors", "cancelled", "interrupted"]);

export default function OverviewPage() {
  const [data, setData] = useState<Health | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const load = useCallback(async () => {
    try {
      const [health, providerData] = await Promise.all([api<Health>("/api/health"), api<{ items: Provider[] }>("/api/providers")]);
      setData(health); setProviders(providerData.items); setError("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Unknown error"); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function demo() {
    setStarting(true);
    try {
      const result = await api<{ batch_id: string }>("/api/evaluations", { method: "POST", body: JSON.stringify({ provider: "scripted", model: "scripted-valid", split: "eval", seed_start: 0, seed_count: 1, attempts: 1, concurrency: 1 }) });
      location.href = `/evaluations/${result.batch_id}`;
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not start demo"); setStarting(false); }
  }

  if (error && !data) return <><header className="page-header"><div><span className="eyebrow">Control plane</span><h1>Evaluation overview</h1><p>Strict, local, reproducible model episodes.</p></div></header><ErrorState message={error} retry={() => void load()} /></>;
  if (!data) return <LoadingState rows={6} label="Loading evaluation overview" />;
  const overview = data.overview;
  const configured = providers.filter(provider => provider.configured).length;
  const reachable = providers.filter(provider => provider.ready).length;
  const activeBatches = data.recent_batches.filter(batch => !terminalStatuses.has(batch.status));
  const activeRuns = activeBatches.reduce((sum, batch) => sum + batch.running_runs + batch.queued_runs, 0);

  return <>
    <section className="overview-hero">
      <div>
        <span className="eyebrow">Evaluation control plane</span>
        <h1>Measure model behavior against strict evidence.</h1>
        <p>Launch bounded long-horizon episodes, follow authenticated actions live, and compare only verifier-produced outcomes.</p>
        <div className="hero-actions">
          <Link className="button primary" href="/evaluations/new"><Plus size={16} aria-hidden="true" />New evaluation</Link>
          <MotionButton className="button secondary" onClick={demo} disabled={starting}>{starting ? <InlineLoading label="Starting demo" /> : <><FlaskConical size={16} aria-hidden="true" />Run scripted demo</>}</MotionButton>
        </div>
      </div>
      <aside className="hero-status-card" aria-label="Current evaluation context">
        <div><span className="status-dot ok" /><strong>Environment ready</strong></div>
        <dl>
          <div><dt>Environment</dt><dd><CommitBadge value={data.environment_commit} /></dd></div>
          <div><dt>Providers</dt><dd>{reachable} ready / {configured} configured</dd></div>
          <div><dt>Active work</dt><dd>{activeRuns} run{activeRuns === 1 ? "" : "s"}</dd></div>
        </dl>
      </aside>
    </section>
    <AuthorityNotice />
    {error && <ErrorState message={error} retry={() => void load()} />}
    <section className="metric-grid six overview-metrics" aria-label="Evaluation metrics">
      <MetricCard label="Strict success" numericValue={(overview.strict_success_rate ?? 0) * 100} format={value => `${number(value, 1)}%`} detail="score exactly 1.0" tone="success" emphasis />
      <MetricCard label="Average reward" numericValue={overview.average_reward} format={value => number(value)} detail="verifier supplied" />
      <MetricCard label="Completed episodes" numericValue={overview.total_completed_episodes} format={value => number(value, 0)} detail={`${overview.total_evaluations} local batches`} />
      <MetricCard label="Active runs" numericValue={activeRuns} format={value => number(value, 0)} detail={activeBatches.length ? `${activeBatches.length} active batches` : "nothing queued"} tone={activeRuns ? "accent" : "neutral"} />
      <MetricCard label="Providers ready" numericValue={reachable} format={value => number(value, 0)} detail={`${configured} configured`} />
      <MetricCard label="Cost / success" value={money(overview.average_cost_per_success)} detail={`${number(overview.average_actions, 1)} average actions`} />
    </section>
    {!data.recent_batches.length ? <EmptyState title="No evaluations yet" detail="Start the credential-free scripted demonstration to produce a real strict-verifier record and populate this workspace." action={<MotionButton className="button primary" onClick={demo} disabled={starting}>{starting ? <InlineLoading label="Starting demo" /> : "Run scripted demonstration"}</MotionButton>} /> : <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Recent activity</span><h2>Evaluation batches</h2></div><Link className="text-link link-with-icon" href="/compare">Compare models <ArrowRight size={14} aria-hidden="true" /></Link></div><DataTable caption="Recent evaluation batches" headers={["Batch", "Model", "Status", "Progress", "Success", "Environment"]} rows={data.recent_batches.map(batch => [<Link key="id" href={`/evaluations/${batch.batch_id}`}><code>{batch.batch_id.slice(0, 18)}</code></Link>, <span key="model">{batch.provider} / <strong>{batch.model}</strong></span>, <RunStatusBadge key="status" status={batch.status} />, `${batch.completed_runs + batch.failed_runs + batch.cancelled_runs}/${batch.total_runs}`, percent(batch.aggregate_results.strict_success_rate), <CommitBadge key="commit" value={batch.environment_commit} />])} /></section>}
    <section className="two-column">
      <article className="surface-section"><div className="section-head"><div><span className="eyebrow">Integrity</span><h2>Source binding</h2></div></div><dl className="detail-list"><div><dt>Environment source</dt><dd><CommitBadge value={data.environment_commit} /></dd></div><div><dt>Frozen V1 tag</dt><dd><CommitBadge label="trial-submission-v1" value={data.frozen_v1_tag} /></dd></div></dl></article>
      <article className="surface-section"><div className="section-head"><div><span className="eyebrow">Attention</span><h2>Recent failures</h2></div>{data.recent_failures.length > 0 && <Activity size={18} className="danger" aria-hidden="true" />}</div>{data.recent_failures.length ? data.recent_failures.map(run => <Link className="failure-row" href={`/runs/${run.run_id}`} key={run.run_id}><RunStatusBadge status={run.status} /><span>{run.model}</span><code>{run.error_category ?? "strict failure"}</code></Link>) : <p className="muted">No recent provider or runner failures.</p>}</article>
    </section>
  </>;
}
