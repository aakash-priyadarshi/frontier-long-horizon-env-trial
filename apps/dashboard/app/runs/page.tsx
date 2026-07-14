"use client";

import Link from "next/link";
import { Activity, ArrowRight, Clock3, Plus, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Run } from "@/lib/types";
import { number } from "@/lib/format";
import { MotionButton } from "@/components/motion";
import { AuthorityNotice, DataTable, EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, ProviderBadge, RunStatusBadge } from "@/components/ui";

type RunsResponse = { items: Run[]; total: number; limit: number; offset: number };

const terminalStatuses = new Set(["completed", "failed", "cancelled", "interrupted"]);

function timestamp(value?: string): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function LiveRunCard({ run }: { run: Run }) {
  const tokens = (run.input_tokens ?? 0) + (run.output_tokens ?? 0);
  return <article className="live-run-card" aria-label={`${run.model} live run`}>
    <div className="live-run-card-head">
      <span className="live-run-icon"><Activity size={17} aria-hidden="true" /></span>
      <RunStatusBadge status={run.status} />
    </div>
    <div className="live-run-model"><ProviderBadge provider={run.provider} /><h3>{run.model}</h3></div>
    <p>Seed {run.seed} · attempt {run.attempt} · <code>{run.run_id.slice(0, 18)}</code></p>
    <dl className="live-run-stats">
      <div><dt>Step</dt><dd>{run.current_step ?? 0}</dd></div>
      <div><dt>Current tool</dt><dd><code>{run.current_tool ?? "Waiting for model"}</code></dd></div>
      <div><dt>Tokens</dt><dd>{number(tokens, 0)}</dd></div>
    </dl>
    <div className="live-run-links">
      <Link className="text-link" href={`/runs/${run.run_id}`}>Inspect live episode <ArrowRight size={13} aria-hidden="true" /></Link>
      <Link className="muted-link" href={`/evaluations/${run.batch_id}`}>Open batch</Link>
    </div>
  </article>;
}

export default function RunsPage() {
  const [data, setData] = useState<RunsResponse | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    try {
      setData(await api<RunsResponse>("/api/runs?limit=200"));
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load runs");
    } finally {
      if (manual) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(interval);
  }, [load]);

  const active = useMemo(() => data?.items.filter(run => !terminalStatuses.has(run.status)) ?? [], [data]);
  const history = useMemo(() => data?.items.filter(run => terminalStatuses.has(run.status)) ?? [], [data]);
  const completed = history.filter(run => run.status === "completed").length;
  const failed = history.filter(run => run.status === "failed" || run.status === "interrupted").length;

  if (!data && !error) return <LoadingState rows={6} label="Loading live runs and history" />;

  return <>
    <PageHeader
      eyebrow="Episode operations"
      title="Runs"
      description="Follow active model episodes and inspect immutable historical results from one workspace."
      actions={<>
        <MotionButton className="button secondary" onClick={() => void load(true)} disabled={refreshing}><RefreshCw size={15} className={refreshing ? "spin" : ""} aria-hidden="true" />Refresh</MotionButton>
        <Link className="button primary" href="/evaluations/new"><Plus size={15} aria-hidden="true" />New evaluation</Link>
      </>}
    />
    <AuthorityNotice />
    {error && <ErrorState message={error} retry={() => void load(true)} />}
    {data && <>
      <section className="metric-grid four compact" aria-label="Run summary">
        <MetricCard label="Active" numericValue={active.length} detail="queued or running" tone={active.length ? "accent" : "neutral"} />
        <MetricCard label="Completed" numericValue={completed} detail="in the visible history" tone="success" />
        <MetricCard label="Failures" numericValue={failed} detail="failed or interrupted" tone={failed ? "danger" : "neutral"} />
        <MetricCard label="Total records" numericValue={data.total} detail={data.total > data.items.length ? `showing newest ${data.items.length}` : "all local runs"} />
      </section>

      <section className="surface-section" aria-labelledby="live-runs-heading">
        <div className="section-head"><div><span className="eyebrow">Now</span><h2 id="live-runs-heading">Live runs</h2></div><span className="run-section-count"><span className={active.length ? "status-dot ok" : "status-dot"} />{active.length} active</span></div>
        {active.length ? <div className="live-run-grid">{active.map(run => <LiveRunCard run={run} key={run.run_id} />)}</div> : <div className="runs-empty-inline"><Clock3 size={18} aria-hidden="true" /><div><strong>No episodes are running</strong><p>New queued and running episodes appear here automatically.</p></div></div>}
      </section>

      <section className="surface-section" aria-labelledby="run-history-heading">
        <div className="section-head"><div><span className="eyebrow">Immutable records</span><h2 id="run-history-heading">Run history</h2></div><span className="run-section-count">{history.length} shown</span></div>
        {history.length ? <DataTable caption="Historical model evaluation runs" headers={["Run", "Provider / model", "Status", "Seed", "Actions / calls", "Score", "Result", "Updated"]} rows={history.map(run => [
          <Link className="text-link" href={`/runs/${run.run_id}`} key="run"><code>{run.run_id.slice(0, 18)}</code></Link>,
          <span className="run-model-cell" key="model"><ProviderBadge provider={run.provider} /><strong>{run.model}</strong></span>,
          <RunStatusBadge status={run.status} key="status" />,
          <span key="seed">{run.seed} / {run.attempt}</span>,
          <span key="activity">{run.action_count ?? 0} / {run.model_call_count ?? 0}</span>,
          <span key="score">{run.authoritative_reward ?? "—"} <small>{run.authoritative_verdict ?? ""}</small></span>,
          <code className={run.error_category ? "danger" : "muted"} key="result">{run.error_category ?? run.termination_reason ?? "—"}</code>,
          <span key="updated">{timestamp(run.updated_at ?? run.ended_at)}</span>,
        ])} /> : <EmptyState title="No historical runs" detail="Completed, failed, cancelled, and interrupted episodes will appear here." />}
      </section>
    </>}
  </>;
}
