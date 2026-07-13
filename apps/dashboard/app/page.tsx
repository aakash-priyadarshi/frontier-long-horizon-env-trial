"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Batch, Run } from "@/lib/types";
import { money, number, percent } from "@/lib/format";
import { AuthorityNotice, CommitBadge, DataTable, EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, RunStatusBadge } from "@/components/ui";

type Health = {
  overview: { total_evaluations: number; total_completed_episodes: number; strict_success_rate: number | null; average_reward: number | null; average_actions: number | null; average_cost_per_success: number | null };
  recent_batches: Batch[];
  recent_failures: Run[];
  environment_commit: string;
  frozen_v1_tag: string;
};

export default function OverviewPage() {
  const [data, setData] = useState<Health | null>(null);
  const [providers, setProviders] = useState(0);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const load = useCallback(async () => {
    try {
      const [health, providerData] = await Promise.all([api<Health>("/api/health"), api<{ items: Array<{ configured: boolean }> }>("/api/providers")]);
      setData(health); setProviders(providerData.items.filter(item => item.configured).length); setError("");
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

  if (error && !data) return <><PageHeader eyebrow="Control plane" title="Evaluation overview" description="Strict, local, reproducible model episodes." /><ErrorState message={error} retry={() => void load()} /></>;
  if (!data) return <LoadingState rows={6} />;
  const overview = data.overview;
  return <>
    <PageHeader eyebrow="Control plane" title="Evaluation overview" description="Operate long-horizon evaluations and inspect verifier-authenticated outcomes." actions={<Link className="button primary" href="/evaluations/new">New evaluation</Link>} />
    <AuthorityNotice />
    <section className="metric-grid six">
      <MetricCard label="Evaluations" value={number(overview.total_evaluations, 0)} detail="all local batches" />
      <MetricCard label="Completed episodes" value={number(overview.total_completed_episodes, 0)} detail="terminal records" />
      <MetricCard label="Strict success" value={percent(overview.strict_success_rate)} detail="score exactly 1.0" tone="success" />
      <MetricCard label="Average reward" value={number(overview.average_reward)} detail="verifier supplied" />
      <MetricCard label="Average actions" value={number(overview.average_actions, 1)} detail="environment steps" />
      <MetricCard label="Cost / success" value={money(overview.average_cost_per_success)} detail={`${providers} providers configured`} />
    </section>
    {!data.recent_batches.length ? <EmptyState title="No evaluations yet" detail="A model receives public incident context and exactly twelve tools, acts through the real environment, and is scored only by the strict verifier." action={<button className="button primary" onClick={demo} disabled={starting}>{starting ? "Starting…" : "Run scripted demonstration"}</button>} /> : <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Recent activity</span><h2>Evaluation batches</h2></div><Link className="text-link" href="/compare">Compare models →</Link></div><DataTable caption="Recent evaluation batches" headers={["Batch", "Model", "Status", "Progress", "Success", "Environment"]} rows={data.recent_batches.map(batch => [<Link key="id" href={`/evaluations/${batch.batch_id}`}><code>{batch.batch_id.slice(0, 18)}</code></Link>, <span key="model">{batch.provider} / <strong>{batch.model}</strong></span>, <RunStatusBadge key="status" status={batch.status} />, `${batch.completed_runs + batch.failed_runs + batch.cancelled_runs}/${batch.total_runs}`, percent(batch.aggregate_results.strict_success_rate), <CommitBadge key="commit" value={batch.environment_commit} />])} /></section>}
    <section className="two-column">
      <article className="surface-section"><div className="section-head"><div><span className="eyebrow">Integrity</span><h2>Source binding</h2></div></div><dl className="detail-list"><div><dt>Environment source</dt><dd><CommitBadge value={data.environment_commit} /></dd></div><div><dt>Frozen V1 tag</dt><dd><CommitBadge label="trial-submission-v1" value={data.frozen_v1_tag} /></dd></div></dl></article>
      <article className="surface-section"><div className="section-head"><div><span className="eyebrow">Attention</span><h2>Recent failures</h2></div></div>{data.recent_failures.length ? data.recent_failures.map(run => <Link className="failure-row" href={`/runs/${run.run_id}`} key={run.run_id}><RunStatusBadge status={run.status} /><span>{run.model}</span><code>{run.error_category ?? "strict failure"}</code></Link>) : <p className="muted">No recent provider or runner failures.</p>}</article>
    </section>
  </>;
}
