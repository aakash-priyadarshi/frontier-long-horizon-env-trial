"use client";

import { useParams } from "next/navigation";
import { Activity } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, eventUrl } from "@/lib/api";
import type { Run } from "@/lib/types";
import { duration, money, number } from "@/lib/format";
import { ActionTimeline } from "@/components/action-timeline";
import { EpisodeRewardProgression } from "@/components/charts";
import { AuthorityNotice, CommitBadge, CopyButton, DataTable, EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, ProviderBadge, RunStatusBadge } from "@/components/ui";

export default function RunPage() {
  const { runId } = useParams<{ runId: string }>();
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => { try { setRun(await api<Run>(`/api/runs/${runId}`)); setError(""); } catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to load run"); } }, [runId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!run || ["completed", "failed", "cancelled", "interrupted"].includes(run.status)) return;
    const events = new EventSource(eventUrl(`/api/runs/${runId}/events`));
    events.onmessage = () => void load();
    ["tool_completed", "run_scored", "run_finished"].forEach(type => events.addEventListener(type, () => void load()));
    return () => events.close();
  }, [run?.status, runId, load]);
  if (error && !run) return <ErrorState message={error} retry={() => void load()} />;
  if (!run) return <LoadingState rows={7} />;
  const terminal = ["completed", "failed", "cancelled", "interrupted"].includes(run.status);
  const rewards = (run.authenticated_timeline ?? []).filter(entry => entry.reward != null).map(entry => ({ step: entry.sequence, reward: entry.reward as number }));
  return <>
    <PageHeader eyebrow="Episode inspection" title={`${run.model} · seed ${run.seed}`} description={`${run.provider} · attempt ${run.attempt} · ${run.instance_id ?? run.run_id}`} actions={<RunStatusBadge status={run.status} />} />
    <AuthorityNotice />
    {!terminal && <section className="run-live-strip" aria-live="polite"><Activity size={17} aria-hidden="true" /><div><span>Episode in progress</span><strong>{run.current_tool ? <code>{run.current_tool}</code> : "Waiting for model response"}</strong></div><span>Step {run.current_step ?? 0}</span></section>}
    <section className={`score-hero verdict-${run.authoritative_verdict ?? "pending"}`}><div><span>Authoritative final score</span><strong>{run.authoritative_reward ?? "—"}</strong><small>{run.authoritative_verdict ?? "pending verifier result"}</small></div><dl><div><dt>Provider / model</dt><dd><ProviderBadge provider={run.provider} /> {run.model}</dd></div><div><dt>Termination</dt><dd>{run.termination_reason ?? "—"}</dd></div><div><dt>Environment</dt><dd><CommitBadge value={run.environment_commit} /></dd></div><div><dt>Record digest</dt><dd className="digest-value"><code title={run.record_digest}>{run.record_digest ?? "pending"}</code>{run.record_digest && <CopyButton value={run.record_digest} label="Copy digest" />}</dd></div></dl></section>
    <section className="metric-grid six"><MetricCard label="Actions" value={number(run.action_count, 0)} /><MetricCard label="Model calls" value={number(run.model_call_count, 0)} /><MetricCard label="Tokens" value={number((run.input_tokens ?? 0) + (run.output_tokens ?? 0), 0)} detail={`${run.cached_tokens ?? 0} cached · ${run.reasoning_tokens ?? 0} reasoning`} /><MetricCard label="Provider latency" value={duration(run.provider_latency_ms)} /><MetricCard label="Elapsed" value={duration(run.elapsed_ms)} /><MetricCard label="Estimated cost" value={money(run.estimated_cost)} /></section>
    <section className="two-column align-start">
      <article className="surface-section"><div className="section-head"><div><span className="eyebrow">Strict result</span><h2>Failed predicates</h2></div></div>{run.failed_predicates?.length ? <ul className="predicate-list">{run.failed_predicates.map(name => <li key={name}><code>{name}</code></li>)}</ul> : <p className="success">No failed predicates in the exposed verifier result.</p>}</article>
      <article className="surface-section"><div className="section-head"><div><span className="eyebrow">Candidate</span><h2>Code-change summary</h2></div></div>{run.candidate_diff_summary?.changed_paths.length ? <ul className="file-list">{run.candidate_diff_summary.changed_paths.map(path => <li key={path}><code>{path}</code></li>)}</ul> : <p className="muted">No candidate file changes recorded.</p>}</article>
    </section>
    <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Public checks</span><h2>Workload outcomes</h2></div></div>{run.public_workload_outcomes && Object.keys(run.public_workload_outcomes).length ? <DataTable caption="Public workload outcomes" headers={["Workload", "Outcome"]} rows={Object.entries(run.public_workload_outcomes).map(([name, value]) => [<code key="name">{name}</code>, value.outcome ?? "unknown"])} /> : <EmptyState title="No public workload outcomes" detail="The episode ended before public workload results were available." />}</section>
    <EpisodeRewardProgression rewards={rewards} />
    <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Authenticated record</span><h2>Action timeline</h2></div><span className="muted">Sanitized environment tools only · capability material removed</span></div><ActionTimeline entries={run.authenticated_timeline ?? []} live={!terminal} /></section>
  </>;
}
