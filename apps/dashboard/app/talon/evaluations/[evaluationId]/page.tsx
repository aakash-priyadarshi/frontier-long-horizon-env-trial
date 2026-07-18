"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Download, Trash2 } from "lucide-react";
import { api, eventUrl } from "@/lib/api";
import type { TalonEpisode, TalonRecord } from "@/lib/types";
import { MotionButton } from "@/components/motion";
import { DataTable, ErrorState, LoadingState, MetricCard, PageHeader, RunStatusBadge } from "@/components/ui";
import { TalonBoundaryNotice, TalonSubnav } from "@/components/talon";
import { TalonCalibrationChart } from "@/components/charts";

const terminal = new Set(["completed", "failed", "cancelled", "interrupted", "timed_out"]);
type TimelineStep = TalonEpisode["timeline"][number];
type LiveStep = { episode_id: string; step: TimelineStep };

function Timeline({ steps, caption }: { steps: TimelineStep[]; caption: string }) {
  return <DataTable
    caption={caption}
    headers={["Step", "Model recommendation", "Gate", "Effective action", "Human approval", "Public reward"]}
    rows={steps.map(step => [
      step.sequence,
      <code key="model">{step.recommendation.recommended_action}</code>,
      step.gate.accepted
        ? <span className="success" key="gate">accepted</span>
        : <span className="danger" key="gate">rejected: {step.gate.violation_codes.join(", ")}</span>,
      <code key="effective">{step.gate.effective_action}</code>,
      step.gate.human_approval_required ? "Required" : "Not required",
      step.public_reward,
    ])}
  />;
}

export default function TalonEvaluationPage() {
  const { evaluationId } = useParams<{ evaluationId: string }>();
  const router = useRouter();
  const [record, setRecord] = useState<TalonRecord | null>(null);
  const [live, setLive] = useState<LiveStep[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(
    () => api<TalonRecord>(`/api/drone/evaluations/${evaluationId}`).then(setRecord),
    [evaluationId],
  );

  useEffect(() => {
    load().catch(reason => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [load]);

  useEffect(() => {
    if (!record || terminal.has(record.status)) return;
    const source = new EventSource(eventUrl(`/api/drone/evaluations/${evaluationId}/events`));
    source.addEventListener("timeline_step", ((event: MessageEvent) => {
      const data = JSON.parse(event.data) as LiveStep;
      setLive(current => [
        ...current.filter(item => !(item.episode_id === data.episode_id && item.step.sequence === data.step.sequence)),
        data,
      ]);
    }) as EventListener);
    source.addEventListener("episode_completed", () => void load());
    source.addEventListener("terminal", () => { source.close(); void load(); });
    source.onerror = () => source.close();
    return () => source.close();
  }, [evaluationId, load, record]);

  const rawCalibration = record?.episodes?.flatMap(episode => episode.result.confidence_calibration_bins ?? []) ?? [];
  const calibration = [0, .2, .4, .6, .8].map(lower => {
    const selected = rawCalibration.filter(bin => bin.lower === lower);
    const count = selected.reduce((total, bin) => total + bin.count, 0);
    return {
      lower,
      upper: lower + .2,
      count,
      mean_confidence: count ? selected.reduce((total, bin) => total + bin.mean_confidence * bin.count, 0) / count : 0,
      gate_acceptance_rate: count ? selected.reduce((total, bin) => total + bin.gate_acceptance_rate * bin.count, 0) / count : 0,
    };
  });

  async function cancel() {
    try {
      await api(`/api/drone/evaluations/${evaluationId}/cancel`, { method: "POST", body: "{}" });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function remove() {
    try {
      await api(`/api/drone/records/${evaluationId}`, { method: "DELETE" });
      router.push("/talon/compare");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const activeEpisode = live.at(-1)?.episode_id;
  const activeSteps = live
    .filter(item => item.episode_id === activeEpisode)
    .map(item => item.step)
    .sort((a, b) => a.sequence - b.sequence);
  const aggregate = record?.aggregate;

  return <>
    <PageHeader
      eyebrow="Talon evaluation"
      title="Strict safety result"
      description={evaluationId}
      actions={<>
        {record && <RunStatusBadge status={record.status} />}
        {record?.status === "completed" && <a className="button secondary" href={eventUrl(`/api/drone/exports/${evaluationId}.json`)}><Download size={15} />Safe JSON</a>}
        {record && terminal.has(record.status)
          ? <MotionButton className="button secondary" onClick={() => void remove()}><Trash2 size={15} />Delete</MotionButton>
          : record ? <MotionButton className="button secondary" onClick={() => void cancel()}>Cancel</MotionButton> : null}
      </>}
    />
    <TalonBoundaryNotice />
    <TalonSubnav />
    {error ? <ErrorState message={error} retry={() => void load()} /> : !record ? <LoadingState rows={5} /> : <>
      <section className="metric-grid four">
        <MetricCard label="Episodes" value={aggregate?.episode_count ?? record.progress?.completed_episodes ?? 0} />
        <MetricCard label="Strict success" value={aggregate ? `${(aggregate.strict_success_rate * 100).toFixed(1)}%` : "Pending"} tone={aggregate?.strict_success_rate === 1 ? "success" : "neutral"} />
        <MetricCard label="Safety violation rate" value={aggregate ? `${(aggregate.safety_violation_rate * 100).toFixed(1)}%` : "—"} tone={aggregate?.safety_violation_rate ? "danger" : "success"} />
        <MetricCard label="Held-out action accuracy" value={aggregate ? `${(aggregate.held_out_action_accuracy * 100).toFixed(1)}%` : "—"} detail="Private labels · frozen weights" />
        <MetricCard label="False escalation" value={aggregate ? `${(aggregate.false_escalation_rate * 100).toFixed(1)}%` : "—"} />
        <MetricCard label="Missed threat" value={aggregate ? `${(aggregate.missed_threat_rate * 100).toFixed(1)}%` : "—"} />
        <MetricCard label="Abstention" value={aggregate ? `${(aggregate.abstention_rate * 100).toFixed(1)}%` : "—"} />
        <MetricCard label="Average score" value={aggregate?.average_score?.toFixed(3) ?? "—"} />
      </section>
      {activeSteps.length > 0 && !terminal.has(record.status) && <section className="surface-section">
        <div className="section-head"><div><span className="eyebrow">Live isolated policy</span><h2>{activeEpisode}</h2></div><span className="status-badge">{activeSteps.length} actions</span></div>
        <Timeline steps={activeSteps} caption="Live public recommendation and policy-gate timeline" />
      </section>}
      <TalonCalibrationChart bins={calibration} />
      {record.episodes?.map(episode => <section className="surface-section" key={episode.result.episode_id}>
        <div className="section-head">
          <div><span className="eyebrow">Opaque episode {episode.result.episode_id}</span><h2>{episode.result.verdict} · {episode.result.score}</h2></div>
          <span className={episode.result.safety_violation_count ? "danger" : "success"}>{episode.result.safety_violation_count} safety violations</span>
        </div>
        {episode.result.failed_categories.length
          ? <div className="tag-row">{episode.result.failed_categories.map(category => <code key={category}>{category}</code>)}</div>
          : <p className="success">All strict safety categories passed.</p>}
        <Timeline steps={episode.timeline} caption="Public recommendation and policy-gate timeline" />
      </section>)}
    </>}
  </>;
}
