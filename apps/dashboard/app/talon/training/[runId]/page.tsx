"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, eventUrl } from "@/lib/api";
import type { TalonRecord } from "@/lib/types";
import { CQLTrainingCurveChart, TrainingCurveChart } from "@/components/charts";
import { MotionButton } from "@/components/motion";
import { ErrorState, LoadingState, MetricCard, PageHeader, RunStatusBadge } from "@/components/ui";
import { TalonBoundaryNotice, TalonSubnav } from "@/components/talon";

type Point = { epoch: number; loss: number; action_accuracy: number };
type CQLPoint = { epoch: number; loss: number; reward_td_loss: number; safety_td_loss: number; cql_penalty: number };
const terminal = new Set(["completed", "failed", "cancelled", "interrupted", "timed_out"]);

export default function TalonTrainingRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const [record, setRecord] = useState<TalonRecord | null>(null);
  const [points, setPoints] = useState<Point[]>([]);
  const [cqlPoints, setCqlPoints] = useState<CQLPoint[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(() => api<TalonRecord>(`/api/drone/training-runs/${runId}`).then(next => {
    setRecord(next);
    if (next.training_history && next.architecture === "cql_gru") {
      setCqlPoints(next.training_history.loss.map((loss, index) => ({
        epoch: index + 1, loss,
        reward_td_loss: next.training_history!.reward_td_loss?.[index] ?? 0,
        safety_td_loss: next.training_history!.safety_td_loss?.[index] ?? 0,
        cql_penalty: next.training_history!.cql_penalty?.[index] ?? 0,
      })));
    } else if (next.training_history) {
      setPoints(next.training_history.loss.map((loss, index) => ({ epoch: index + 1, loss, action_accuracy: next.training_history!.training_action_accuracy?.[index] ?? 0 })));
    }
  }), [runId]);

  useEffect(() => { load().catch(reason => setError(reason instanceof Error ? reason.message : String(reason))); }, [load]);
  useEffect(() => {
    if (!record || terminal.has(record.status)) return;
    const source = new EventSource(eventUrl(`/api/drone/training-runs/${runId}/events`));
    const onProgress = (event: MessageEvent) => {
      const data = JSON.parse(event.data) as { progress: { epoch?: number; loss?: number; training_action_accuracy?: number; reward_td_loss?: number; safety_td_loss?: number; cql_penalty?: number } };
      if (data.progress.epoch && data.progress.loss != null && data.progress.training_action_accuracy != null) {
        setPoints(current => [...current.filter(point => point.epoch !== data.progress.epoch), { epoch: data.progress.epoch!, loss: data.progress.loss!, action_accuracy: data.progress.training_action_accuracy! }].sort((a, b) => a.epoch - b.epoch));
      }
      if (data.progress.epoch && data.progress.loss != null && data.progress.reward_td_loss != null && data.progress.safety_td_loss != null && data.progress.cql_penalty != null) {
        setCqlPoints(current => [...current.filter(point => point.epoch !== data.progress.epoch), { epoch: data.progress.epoch!, loss: data.progress.loss!, reward_td_loss: data.progress.reward_td_loss!, safety_td_loss: data.progress.safety_td_loss!, cql_penalty: data.progress.cql_penalty! }].sort((a, b) => a.epoch - b.epoch));
      }
      void load();
    };
    source.addEventListener("progress", onProgress as EventListener);
    source.addEventListener("terminal", () => { source.close(); void load(); });
    source.onerror = () => source.close();
    return () => source.close();
  }, [load, record, runId]);

  async function cancel() {
    try { await api(`/api/drone/training-runs/${runId}/cancel`, { method: "POST", body: "{}" }); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }

  const progress = record?.progress;
  const pointCount = record?.architecture === "cql_gru" ? cqlPoints.length : points.length;
  const ratio = progress?.epochs ? (progress.epoch ?? 0) / progress.epochs : 0;
  const metrics = record?.training_metrics;
  return <>
    <PageHeader eyebrow="Talon training" title={record?.architecture ?? "Learned policy"} description={runId} actions={<>{record && <RunStatusBadge status={record.status} />}{record && !terminal.has(record.status) && <MotionButton className="button secondary" onClick={() => void cancel()}>Cancel</MotionButton>}</>} />
    <TalonBoundaryNotice /><TalonSubnav />
    {error ? <ErrorState message={error} retry={() => void load()} /> : !record ? <LoadingState rows={4} /> : <>
      <section className="metric-grid four">
        <MetricCard label="Epoch" value={`${progress?.epoch ?? pointCount} / ${progress?.epochs ?? (pointCount || "—")}`} />
        <MetricCard label="Latest loss" value={progress?.loss?.toFixed(4) ?? metrics?.loss?.toFixed(4) ?? "—"} />
        <MetricCard label={record.architecture === "cql_gru" ? "CQL penalty" : "Training accuracy"} value={record.architecture === "cql_gru" ? (progress?.cql_penalty?.toFixed(4) ?? metrics?.cql_penalty?.toFixed(4) ?? "—") : progress?.training_action_accuracy != null ? `${(progress.training_action_accuracy * 100).toFixed(1)}%` : metrics?.training_action_accuracy != null ? `${(metrics.training_action_accuracy * 100).toFixed(1)}%` : "—"} detail={record.architecture === "cql_gru" ? "Conservative action-value regularizer" : "In-sample; not held-out safety"} />
        <MetricCard label="Validation accuracy" value={metrics ? `${(metrics.validation_action_accuracy * 100).toFixed(1)}%` : "Pending"} detail="Frozen weights · disjoint partition" />
        <MetricCard label="Checkpoint" value={record.checkpoint_digest ? "Digest-bound" : "Pending"} detail={record.checkpoint_digest?.slice(0, 20)} />
      </section>
      <div className="batch-progress"><div className="progress-label"><span>{record.architecture === "cql_gru" ? "Offline CQL epochs" : "Supervised epochs"}</span><strong>{Math.round(ratio * 100)}%</strong></div><div className="progress-track" role="progressbar" aria-valuenow={ratio * 100} aria-valuemin={0} aria-valuemax={100}><span className="progress-fill" style={{ transform: `scaleX(${ratio})`, transformOrigin: "left" }} /></div></div>
      {record.architecture === "cql_gru" ? <CQLTrainingCurveChart points={cqlPoints} /> : <TrainingCurveChart points={points} />}
      <section className="surface-section"><h2>Public checkpoint metadata</h2><dl className="detail-grid">
        <div><dt>Architecture</dt><dd>{record.architecture ?? "Pending"}</dd></div>
        <div><dt>Parameters</dt><dd>{record.parameter_count?.toLocaleString() ?? "Pending"}</dd></div>
        <div><dt>Record digest</dt><dd><code>{record.record_digest ?? "Pending"}</code></dd></div>
        {record.offline_dataset_digest && <div><dt>Verified offline dataset</dt><dd><code>{record.offline_dataset_digest}</code></dd></div>}
        {record.transition_count != null && <div><dt>Static transitions</dt><dd>{record.transition_count.toLocaleString()}</dd></div>}
        {record.algorithm_version && <div><dt>Algorithm</dt><dd>{record.algorithm_version}</dd></div>}
        {record.architecture === "cql_gru" && <div><dt>Reward TD loss</dt><dd>{metrics?.reward_td_loss?.toFixed(4) ?? progress?.reward_td_loss?.toFixed(4) ?? "Pending"}</dd></div>}
        {record.architecture === "cql_gru" && <div><dt>Safety TD loss</dt><dd>{metrics?.safety_td_loss?.toFixed(4) ?? progress?.safety_td_loss?.toFixed(4) ?? "Pending"}</dd></div>}
        {record.architecture === "cql_gru" && <div><dt>Invalid-cost margin</dt><dd>{metrics?.invalid_cost_margin?.toFixed(4) ?? progress?.invalid_cost_margin?.toFixed(4) ?? "Pending"}</dd></div>}
        {record.architecture === "cql_gru" && <div><dt>Mean reward Q</dt><dd>{metrics?.mean_reward_q?.toFixed(4) ?? "Pending"}</dd></div>}
        {record.architecture === "cql_gru" && <div><dt>Mean safety Q</dt><dd>{metrics?.mean_safety_q?.toFixed(4) ?? "Pending"}</dd></div>}
        {record.hardware && <div><dt>Hardware</dt><dd>{record.hardware}</dd></div>}
      </dl></section>
    </>}
  </>;
}
