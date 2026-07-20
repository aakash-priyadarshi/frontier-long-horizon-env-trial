"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { Download, Maximize2, Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { useReducedMotion } from "motion/react";
import { api, eventUrl } from "@/lib/api";
import type { TalonReplay } from "@/lib/types";
import { MotionButton } from "@/components/motion";
import { DataTable, ErrorState, LoadingState, MetricCard, PageHeader } from "@/components/ui";
import { TalonBoundaryNotice, TalonSubnav } from "@/components/talon";

const speeds = [.5, 1, 2, 4];

export default function TalonEpisodeReplayPage() {
  const { episodeId } = useParams<{ episodeId: string }>();
  const reduce = useReducedMotion();
  const player = useRef<HTMLElement>(null);
  const [replay, setReplay] = useState<TalonReplay | null>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [autoScroll, setAutoScroll] = useState(true);
  const [filter, setFilter] = useState<"all" | "evidence" | "gate" | "safety">("all");
  const [trackId, setTrackId] = useState<string>("all");
  const [error, setError] = useState("");
  const load = useCallback(() => api<TalonReplay>(`/api/drone/episodes/${episodeId}/replay`).then(value => { setReplay(value); setIndex(0); setTrackId("all"); }), [episodeId]);
  useEffect(() => { load().catch(reason => setError(reason instanceof Error ? reason.message : String(reason))); }, [load]);
  useEffect(() => {
    if (!playing || !replay || reduce) return;
    const timer = window.setInterval(() => setIndex(current => {
      if (current >= replay.steps.length - 1) { setPlaying(false); return current; }
      return current + 1;
    }), 1000 / speed);
    return () => window.clearInterval(timer);
  }, [playing, reduce, replay, speed]);
  useEffect(() => {
    function keyboard(event: KeyboardEvent) {
      if (!replay || event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
      if (event.key === " ") { event.preventDefault(); setPlaying(value => !value); }
      if (event.key === "ArrowLeft") setIndex(value => Math.max(0, value - 1));
      if (event.key === "ArrowRight") setIndex(value => Math.min(replay.steps.length - 1, value + 1));
    }
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, [replay]);
  useEffect(() => { if (autoScroll) document.getElementById(`replay-step-${index + 1}`)?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" }); }, [autoScroll, index, reduce]);

  const step = replay?.steps[index];
  const tracks = useMemo(() => Array.from(new Set(replay?.steps.map(item => item.observation.track_id) ?? [])), [replay]);
  const filtered = useMemo(() => (replay?.steps ?? []).filter(item => {
    if (trackId !== "all" && item.observation.track_id !== trackId) return false;
    if (filter === "all") return true;
    if (filter === "evidence") return item.evidence_pending.length > 0 || item.evidence_completed.length > 0;
    if (filter === "gate") return !item.gate.accepted;
    if (filter === "safety") return item.top_action_scores.some(score => !score.below_safety_threshold);
    return true;
  }), [filter, trackId, replay]);
  return <>
    <PageHeader eyebrow="Policy-visible replay" title="Human-readable model behaviour" description={episodeId} actions={replay && <><a className="button secondary" href={eventUrl(`/api/drone/episodes/${episodeId}/replay/export.json`)}><Download size={15} />Safe JSON</a><MotionButton className="button secondary" onClick={() => void player.current?.requestFullscreen()}><Maximize2 size={15} />Fullscreen</MotionButton></>} />
    <TalonBoundaryNotice /><TalonSubnav />
    {error ? <ErrorState message={error} retry={() => void load()} /> : !replay || !step ? <LoadingState rows={6} label="Loading immutable replay" /> : <>
      <section className="metric-grid four"><MetricCard label="Strict score" value={replay.metrics.score.toFixed(3)} tone={replay.metrics.strict_success ? "success" : "neutral"} /><MetricCard label="Safety violations" value={replay.metrics.safety_violation_count} tone={replay.metrics.safety_violation_count ? "danger" : "success"} /><MetricCard label="Gate intervention" value={`${(replay.metrics.gate_intervention_rate * 100).toFixed(1)}%`} /><MetricCard label="Evidence efficiency" value={`${(replay.metrics.evidence_efficiency * 100).toFixed(1)}%`} /></section>
      <section className="surface-section replay-player" ref={player} aria-label="Episode replay player">
        <div className="replay-controls"><MotionButton className="icon-button" aria-label="Previous step" onClick={() => setIndex(value => Math.max(0, value - 1))}><SkipBack size={16} /></MotionButton><MotionButton className="button" aria-label={playing ? "Pause replay" : "Play replay"} onClick={() => setPlaying(value => !value)}>{playing ? <Pause size={16} /> : <Play size={16} />}{playing ? "Pause" : "Play"}</MotionButton><MotionButton className="icon-button" aria-label="Next step" onClick={() => setIndex(value => Math.min(replay.steps.length - 1, value + 1))}><SkipForward size={16} /></MotionButton><label>Step <input aria-label="Replay position" type="range" min={0} max={replay.steps.length - 1} value={index} onChange={event => { setPlaying(false); setIndex(Number(event.target.value)); }} /></label><strong>{index + 1} / {replay.steps.length}</strong><label>Speed<select value={speed} onChange={event => setSpeed(Number(event.target.value))}>{speeds.map(value => <option key={value} value={value}>{value}×</option>)}</select></label><label className="check-row"><input type="checkbox" checked={autoScroll} onChange={event => setAutoScroll(event.target.checked)} />Auto-scroll</label></div>
        <div className="replay-track-grid">
          <article><span className="eyebrow">Public observation</span><h2>{step.observation.track_id}</h2><dl className="detail-grid"><div><dt>Simulated clock</dt><dd>{(step.simulated_time_ms / 1000).toFixed(1)}s</dd></div><div><dt>Distance</dt><dd>{step.observation.distance_m.toFixed(0)}m</dd></div><div><dt>Approach rate</dt><dd>{step.observation.approach_rate_mps.toFixed(1)}m/s</dd></div><div><dt>Classification confidence</dt><dd>{(step.observation.classification_confidence * 100).toFixed(1)}%</dd></div></dl><div className="replay-spark" role="img" aria-label={`Classification confidence ${(step.observation.classification_confidence * 100).toFixed(0)} percent`}><span style={{ width: `${Math.min(100, step.observation.classification_confidence * 100)}%` }} /></div></article>
          <article><span className="eyebrow">Model decision</span><h2><code>{step.raw_action}</code></h2><p>{(step.action_confidence * 100).toFixed(1)}% model confidence{step.abstained ? " · abstained" : ""}</p><div className="tag-row">{step.evidence_pending.map(item => <code key={item}>pending: {item}</code>)}{step.evidence_completed.map(item => <code key={item}>complete: {item}</code>)}</div></article>
          <article><span className="eyebrow">Deterministic policy gate</span><h2 className={step.gate.accepted ? "success" : "danger"}>{step.gate.accepted ? "Accepted" : "Intervened"}</h2><p>Effective: <code>{step.effective_action}</code></p>{step.gate.violation_codes.length > 0 && <div className="tag-row">{step.gate.violation_codes.map(item => <code key={item}>{item}</code>)}</div>}<p>Approval: {step.approval.status}{step.approval.consumed ? " · consumed once" : ""}</p></article>
        </div>
        <DataTable caption="Top operational and safety action values" headers={["Action", "Operational Q", "Safety Q", "Publicly valid", "Below threshold"]} rows={step.top_action_scores.map(item => [<code key="action">{item.action}</code>, item.operational_q.toFixed(4), item.safety_q.toFixed(4), item.publicly_valid ? "yes" : "no", item.below_safety_threshold ? "yes" : "no"])} />
      </section>
      <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Trajectory diagnostics</span><h2>Track, confidence, evidence and safety over time</h2></div></div><div className="replay-series" role="group" aria-label="Classification confidence by replay step">{replay.steps.map(item => <button key={item.sequence} aria-label={`Step ${item.sequence}, confidence ${(item.observation.classification_confidence * 100).toFixed(0)} percent`} className={item.sequence === step.sequence ? "active" : ""} onClick={() => setIndex(item.sequence - 1)}><span style={{ height: `${Math.max(3, item.observation.classification_confidence * 100)}%` }} /></button>)}</div><DataTable caption="Replay trajectory chart data" headers={["Step", "Distance m", "Approach m/s", "Detection", "Classification", "Evidence pending / complete", "Raw / effective action", "Best operational Q", "Lowest safety Q", "Gate", "Approval", "Termination"]} rows={replay.steps.map(item => [item.sequence, item.observation.distance_m.toFixed(1), item.observation.approach_rate_mps.toFixed(1), item.observation.detection_confidence.toFixed(3), item.observation.classification_confidence.toFixed(3), `${item.evidence_pending.length} / ${item.evidence_completed.length}`, `${item.raw_action} / ${item.effective_action}`, item.top_action_scores.length ? Math.max(...item.top_action_scores.map(score => score.operational_q)).toFixed(4) : "—", item.top_action_scores.length ? Math.min(...item.top_action_scores.map(score => score.safety_q)).toFixed(4) : "—", item.gate.accepted ? "accepted" : "intervened", item.approval.status, item.terminated ? "terminated" : item.truncated ? "truncated" : "active"])} /></section>
      <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Accessible timeline</span><h2>Decision events</h2></div><div className="replay-filter"><label>Track<select aria-label="Track selector" value={trackId} onChange={event => setTrackId(event.target.value)}><option value="all">All tracks</option>{tracks.map(id => <option key={id} value={id}>{id}</option>)}</select></label><label>Filter<select value={filter} onChange={event => setFilter(event.target.value as typeof filter)}><option value="all">All events</option><option value="evidence">Evidence</option><option value="gate">Gate interventions</option><option value="safety">Safety flags</option></select></label></div></div><div className="replay-step-list">{filtered.map(item => <button id={`replay-step-${item.sequence}`} key={item.sequence} className={item.sequence === step.sequence ? "active" : ""} onClick={() => { setPlaying(false); setIndex(replay.steps.findIndex(candidate => candidate.sequence === item.sequence)); }}><span>{item.sequence}</span><code>{item.raw_action}</code><small>{item.gate.accepted ? "accepted" : item.gate.violation_codes.join(", ")}</small></button>)}</div></section>
      <section className="surface-section"><h2>Replay integrity and access boundary</h2><dl className="detail-grid"><div><dt>Replay digest</dt><dd><code>{replay.replay_digest}</code></dd></div><div><dt>Checkpoint</dt><dd><code>{replay.checkpoint_digest ?? "none (external policy)"}</code></dd></div>{replay.external_policy ? <><div><dt>Policy kind</dt><dd><code>{replay.external_policy.policy_kind}</code></dd></div><div><dt>Provider / model</dt><dd><code>{replay.external_policy.provider} / {replay.external_policy.model}</code></dd></div><div><dt>Prompt version</dt><dd><code>{replay.external_policy.prompt_version}</code></dd></div></> : null}<div><dt>View</dt><dd>Policy-visible public record</dd></div><div><dt>Chain of thought</dt><dd>Not collected or retained</dd></div></dl></section>
    </>}
  </>;
}
