"use client";

import { useParams, useRouter } from "next/navigation";
import { Activity, Download, FileDiff, HardDrive, Radio, ShieldCheck, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, eventUrl } from "@/lib/api";
import type { Run, TimelineEntry } from "@/lib/types";
import { duration, fileSize, money, number } from "@/lib/format";
import { ActionTimeline } from "@/components/action-timeline";
import { EpisodeRewardProgression } from "@/components/charts";
import { ToolUseDebugPanel } from "@/components/tool-use-debug";
import { downloadEpisodeJson } from "@/lib/episode-export";
import { MotionButton } from "@/components/motion";
import { AuthorityNotice, CommitBadge, ConfirmDialog, CopyButton, DataTable, EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, ProviderBadge, RunStatusBadge } from "@/components/ui";

export default function RunPage() {
  const { runId } = useParams<{ runId: string }>();
  const router = useRouter();
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const [mutationError, setMutationError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmAction, setConfirmAction] = useState<"diff" | "episode" | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [connection, setConnection] = useState<"connecting" | "connected" | "reconnecting">("connecting");
  const load = useCallback(async () => { try { setRun(await api<Run>(`/api/runs/${runId}`)); setError(""); } catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to load run"); } }, [runId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!run || ["completed", "failed", "cancelled", "interrupted"].includes(run.status)) return;
    const events = new EventSource(eventUrl(`/api/runs/${runId}/events`));
    events.onopen = () => setConnection("connected");
    events.onerror = () => setConnection("reconnecting");
    events.addEventListener("model_response", event => {
      try {
        const data = JSON.parse((event as MessageEvent<string>).data) as {
          model_calls?: number; input_tokens?: number; output_tokens?: number; estimated_cost?: number | null;
        };
        setRun(current => current ? {
          ...current,
          model_call_count: data.model_calls ?? current.model_call_count,
          input_tokens: data.input_tokens ?? current.input_tokens,
          output_tokens: data.output_tokens ?? current.output_tokens,
          estimated_cost: data.estimated_cost ?? current.estimated_cost,
          current_tool: undefined,
        } : current);
      } catch { void load(); }
    });
    events.addEventListener("tool_completed", event => {
      try {
        const data = JSON.parse((event as MessageEvent<string>).data) as {
          current_step?: number; input_tokens?: number; output_tokens?: number;
          estimated_cost?: number | null; timeline_entry?: TimelineEntry;
        };
        const entry = data.timeline_entry;
        if (!entry || typeof entry.sequence !== "number" || typeof entry.tool !== "string") {
          void load();
          return;
        }
        setRun(current => {
          if (!current) return current;
          const existing = current.authenticated_timeline ?? [];
          const timeline = existing.some(item => item.sequence === entry.sequence)
            ? existing.map(item => item.sequence === entry.sequence ? entry : item)
            : [...existing, entry].sort((left, right) => left.sequence - right.sequence);
          return {
            ...current,
            authenticated_timeline: timeline,
            action_count: Math.max(current.action_count ?? 0, entry.sequence),
            current_step: data.current_step ?? entry.sequence,
            current_tool: undefined,
            input_tokens: data.input_tokens ?? current.input_tokens,
            output_tokens: data.output_tokens ?? current.output_tokens,
            estimated_cost: data.estimated_cost ?? current.estimated_cost,
          };
        });
      } catch { void load(); }
    });
    events.addEventListener("run_scored", event => {
      try {
        const data = JSON.parse((event as MessageEvent<string>).data) as {
          authoritative_reward?: number; authoritative_verdict?: string;
        };
        setRun(current => current ? {
          ...current,
          authoritative_reward: data.authoritative_reward ?? current.authoritative_reward,
          authoritative_verdict: data.authoritative_verdict ?? current.authoritative_verdict,
        } : current);
      } catch { void load(); }
    });
    events.addEventListener("run_finished", () => void load());
    return () => events.close();
  }, [run?.status, runId, load]);

  const deleteCandidateDiff = useCallback(async () => {
    setDeleting(true);
    try {
      await api(`/api/runs/${runId}/candidate-diff`, { method: "DELETE" });
      await load();
      setNotice("Retained candidate diff deleted. The immutable score record and artifact digest remain available for audit.");
      setMutationError("");
    } catch (reason) {
      setMutationError(reason instanceof Error ? reason.message : "Unable to delete candidate diff");
    } finally {
      setDeleting(false);
    }
  }, [load, runId]);

  const deleteEpisode = useCallback(async () => {
    setDeleting(true);
    try {
      await api(`/api/runs/${runId}`, { method: "DELETE" });
      router.push("/runs");
      router.refresh();
    } catch (reason) {
      setMutationError(reason instanceof Error ? reason.message : "Unable to delete episode");
      setDeleting(false);
    }
  }, [router, runId]);

  if (error && !run) return <ErrorState message={error} retry={() => void load()} />;
  if (!run) return <LoadingState rows={7} />;
  const terminal = ["completed", "failed", "cancelled", "interrupted"].includes(run.status);
  const rewards = (run.authenticated_timeline ?? []).filter(entry => entry.reward != null).map(entry => ({ step: entry.sequence, reward: entry.reward as number }));
  const legacyCandidateDiff = Boolean(
    run.candidate_diff_summary?.changed_paths.length
    && !run.candidate_diff_summary.retention
    && (!run.candidate_diff_storage || run.candidate_diff_storage.state === "not_captured"),
  );
  return <>
    <PageHeader eyebrow="Episode inspection" title={`${run.model} · seed ${run.seed}`} description={`${run.provider} · attempt ${run.attempt} · ${run.instance_id ?? run.run_id}`} actions={<><button type="button" className="button secondary" onClick={() => downloadEpisodeJson(run)} title="Download the complete sanitized episode record"><Download size={16} aria-hidden="true" />Download JSON</button><RunStatusBadge status={run.status} /></>} />
    <AuthorityNotice />
    {notice && <aside className="artifact-notice success" role="status"><ShieldCheck size={16} aria-hidden="true" />{notice}</aside>}
    {mutationError && <aside className="artifact-notice danger" role="alert">{mutationError}</aside>}
    {!terminal && <section className="run-live-strip" aria-live="polite"><Activity size={17} aria-hidden="true" /><div><span>Episode in progress</span><strong>{run.current_tool ? <code>{run.current_tool}</code> : "Waiting for model response"}</strong></div><span>Step {run.current_step ?? 0}</span></section>}
    <section className={`score-hero verdict-${run.authoritative_verdict ?? "pending"}`}><div><span>Authoritative final score</span><strong>{run.authoritative_reward ?? "—"}</strong><small>{run.authoritative_verdict ?? "pending verifier result"}</small></div><dl><div><dt>Provider / model</dt><dd><ProviderBadge provider={run.provider} /> {run.model}</dd></div><div><dt>Termination</dt><dd>{run.termination_reason ?? "—"}</dd></div><div><dt>Environment</dt><dd><CommitBadge value={run.environment_commit} /></dd></div><div><dt>Record digest</dt><dd className="digest-value"><code title={run.record_digest}>{run.record_digest ?? "pending"}</code>{run.record_digest && <CopyButton value={run.record_digest} label="Copy digest" />}</dd></div></dl></section>
    <section className="metric-grid six"><MetricCard label="Actions" value={number(run.action_count, 0)} /><MetricCard label="Model calls" value={number(run.model_call_count, 0)} /><MetricCard label="Tokens" value={number((run.input_tokens ?? 0) + (run.output_tokens ?? 0), 0)} detail={`${run.cached_tokens ?? 0} cached · ${run.reasoning_tokens ?? 0} reasoning`} /><MetricCard label="Provider latency" value={duration(run.provider_latency_ms)} /><MetricCard label="Elapsed" value={duration(run.elapsed_ms)} /><MetricCard label="Estimated cost" value={money(run.estimated_cost)} /></section>
    <section className="two-column align-start">
      <article className="surface-section"><div className="section-head"><div><span className="eyebrow">Strict result</span><h2>Failed predicates</h2></div></div>{run.failed_predicates?.length ? <ul className="predicate-list">{run.failed_predicates.map(name => <li key={name}><code>{name}</code></li>)}</ul> : <p className="success">No failed predicates in the exposed verifier result.</p>}</article>
      <article className="surface-section"><div className="section-head"><div><span className="eyebrow">Candidate</span><h2>Code-change retention</h2></div><FileDiff size={18} aria-hidden="true" /></div>{run.candidate_diff_summary?.changed_paths.length ? <ul className="file-list">{run.candidate_diff_summary.changed_paths.map(path => <li key={path}><code>{path}</code></li>)}</ul> : <p className="muted">No effective candidate file changes were retained.</p>}{legacyCandidateDiff ? <p className="artifact-legacy-note">This episode predates secure candidate-diff retention. Its changed paths and content hashes remain in the timeline and JSON export, but the exact candidate source cannot be reconstructed.</p> : null}<div className="artifact-actions"><span><HardDrive size={14} aria-hidden="true" />{run.candidate_diff_storage?.state === "available" ? `${fileSize(run.candidate_diff_storage.stored_bytes)} retained` : run.candidate_diff_storage?.state === "deleted" ? "Diff deleted; digest preserved" : run.candidate_diff_storage?.state === "corrupt" ? "Artifact integrity check failed" : legacyCandidateDiff ? "Legacy run · diff unavailable" : "No effective diff captured"}</span>{terminal && run.candidate_diff_storage?.state === "available" && <div className="artifact-action-buttons"><a className="button secondary" href="#candidate-diff-heading"><FileDiff size={14} aria-hidden="true" />View diff</a><MotionButton className="button secondary" onClick={() => setConfirmAction("diff")} disabled={deleting}><Trash2 size={14} aria-hidden="true" />Delete diff</MotionButton></div>}</div></article>
    </section>
    {run.candidate_diff?.files.length ? <section className="surface-section" aria-labelledby="candidate-diff-heading"><div className="section-head"><div><span className="eyebrow">Sanitized artifact</span><h2 id="candidate-diff-heading">Candidate diff</h2></div><span className="muted">{run.candidate_diff.redaction_count} redactions · digest-bound</span></div>{run.candidate_diff.truncated && <p className="warning">The retained diff reached its bounded storage limit and was truncated.</p>}<div className="candidate-diff-files">{run.candidate_diff.files.map(file => <details key={file.path} open><summary><code>{file.path}</code><span>{fileSize(file.after_bytes)} candidate file</span></summary><pre className="candidate-diff-code" tabIndex={0}><code>{file.diff}</code></pre></details>)}</div><div className="artifact-digest"><span>Artifact digest</span><code>{run.candidate_diff.artifact_digest}</code><CopyButton value={run.candidate_diff.artifact_digest} label="Copy artifact digest" /></div></section> : run.candidate_diff_storage?.state === "deleted" ? <section className="surface-section artifact-empty"><FileDiff size={20} aria-hidden="true" /><div><h2>Candidate diff was deleted</h2><p>The score, changed paths, file hashes and digest binding remain in the immutable episode record.</p></div></section> : null}
    <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Public checks</span><h2>Workload outcomes</h2></div></div>{run.public_workload_outcomes && Object.keys(run.public_workload_outcomes).length ? <DataTable caption="Public workload outcomes" headers={["Workload", "Outcome"]} rows={Object.entries(run.public_workload_outcomes).map(([name, value]) => [<code key="name">{name}</code>, value.outcome ?? "unknown"])} /> : <EmptyState title="No public workload outcomes" detail="The episode ended before public workload results were available." />}</section>
    <EpisodeRewardProgression rewards={rewards} />
    <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Debug</span><h2>Tool-use root cause</h2></div><span className="muted">Read-only analysis of protocol health and recovery workflow preconditions</span></div><ToolUseDebugPanel debug={run.tool_use_debug} modelTurns={run.model_turn_debug} /></section>
    <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Authenticated record</span><h2>Action timeline</h2></div>{terminal ? <span className="muted">Sanitized environment tools only · capability material removed</span> : <span className={`live-indicator ${connection}`}><Radio size={13} aria-hidden="true" />{connection === "connected" ? "Live actions connected" : connection === "reconnecting" ? "Live actions reconnecting" : "Connecting live actions"}</span>}</div><ActionTimeline entries={run.authenticated_timeline ?? []} live={!terminal} /></section>
    {terminal && <section className="surface-section danger-zone"><div><span className="eyebrow">Local data control</span><h2>Delete episode</h2><p>Remove this episode record, its events, JSON result and retained candidate diff from this machine.</p></div><MotionButton className="button danger-button" onClick={() => setConfirmAction("episode")} disabled={deleting}><Trash2 size={15} aria-hidden="true" />Delete episode</MotionButton></section>}
    <ConfirmDialog open={confirmAction === "diff"} title="Delete retained candidate diff?" detail="This reclaims the artifact storage while preserving the immutable score record, changed-file summary and artifact digest." confirmLabel="Delete diff" cancelLabel="Cancel" onConfirm={() => void deleteCandidateDiff()} onClose={() => setConfirmAction(null)} />
    <ConfirmDialog open={confirmAction === "episode"} title="Delete this episode permanently?" detail="This removes the run record, action events, result artifact and candidate diff. If it is the final episode in its evaluation, the empty parent evaluation is also removed." confirmLabel="Delete episode" cancelLabel="Cancel" onConfirm={() => void deleteEpisode()} onClose={() => setConfirmAction(null)} />
  </>;
}
