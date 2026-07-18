"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { GraduationCap } from "lucide-react";
import { api } from "@/lib/api";
import type { TalonRecord } from "@/lib/types";
import { MotionButton } from "@/components/motion";
import { ErrorState, InlineLoading, LoadingState, PageHeader } from "@/components/ui";
import { TalonBoundaryNotice, TalonSubnav } from "@/components/talon";

export default function NewTalonTrainingPage() {
  const router = useRouter();
  const [datasets, setDatasets] = useState<TalonRecord[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [architecture, setArchitecture] = useState("gru");
  const [epochs, setEpochs] = useState(20);
  const [learningRate, setLearningRate] = useState(0.001);
  const [batchSize, setBatchSize] = useState(32);
  const [contextLength, setContextLength] = useState(20);
  const [timeoutSeconds, setTimeoutSeconds] = useState(300);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api<{ items: TalonRecord[] }>("/api/drone/datasets").then(value => { const completed = value.items.filter(item => item.status === "completed"); setDatasets(completed); setDatasetId(completed[0]?.record_id ?? ""); }).catch(reason => setError(reason instanceof Error ? reason.message : String(reason))); }, []);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { const result = await api<{ training_run_id: string }>("/api/drone/training-runs", { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ dataset_id: datasetId, architecture, epochs, learning_rate: learningRate, batch_size: batchSize, context_length: contextLength, random_seed: 0, timeout_seconds: timeoutSeconds }) }); router.push(`/talon/training/${result.training_run_id}`); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setBusy(false); }
  }
  return <><PageHeader eyebrow="Supervised baseline" title="Train a Talon policy" description="Train a bounded GRU baseline or causal Decision Transformer on a private training-only dataset." /><TalonBoundaryNotice /><TalonSubnav />{error && <ErrorState message={error} />}{!datasets.length && !error ? <LoadingState rows={3} label="Loading completed training datasets" /> : <form className="surface-section" onSubmit={submit}><div className="section-head"><div><span className="eyebrow">Configuration</span><h2>Behaviour cloning</h2></div><GraduationCap size={19} /></div><div className="field-grid"><label>Dataset<select required value={datasetId} onChange={event => setDatasetId(event.target.value)}>{datasets.map(item => <option value={item.record_id} key={item.record_id}>{item.record_id}</option>)}</select></label><label>Architecture<select value={architecture} onChange={event => setArchitecture(event.target.value)}><option value="gru">GRU baseline</option><option value="decision_transformer">Decision Transformer</option></select></label><label>Epochs<input type="number" min={1} max={500} value={epochs} onChange={event => setEpochs(Number(event.target.value))} /></label><label>Learning rate<input type="number" min="0.000001" max="1" step="0.0001" value={learningRate} onChange={event => setLearningRate(Number(event.target.value))} /></label><label>Batch size<input type="number" min={1} max={4096} value={batchSize} onChange={event => setBatchSize(Number(event.target.value))} /></label><label>Context length<input type="number" min={1} max={64} value={contextLength} onChange={event => setContextLength(Number(event.target.value))} /></label><label>Worker timeout (seconds)<input type="number" min={1} max={3600} value={timeoutSeconds} onChange={event => setTimeoutSeconds(Number(event.target.value))} /></label></div><div className="start-confirmation"><div><strong>Training cannot weaken the policy gate</strong><p>Training accuracy is an in-sample metric, not a generalisation or safety claim.</p></div><MotionButton className="button" type="submit" disabled={busy || !datasetId}>{busy ? <InlineLoading label="Queuing" /> : "Start training"}</MotionButton></div></form>}</>;
}
