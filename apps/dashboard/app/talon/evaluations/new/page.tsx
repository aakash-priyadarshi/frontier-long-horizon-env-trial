"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { TalonRecord } from "@/lib/types";
import { MotionButton } from "@/components/motion";
import { ErrorState, InlineLoading, LoadingState, PageHeader } from "@/components/ui";
import { TalonBoundaryNotice, TalonSubnav } from "@/components/talon";

export default function NewTalonEvaluationPage() {
  const router = useRouter();
  const [models, setModels] = useState<TalonRecord[]>([]);
  const [modelId, setModelId] = useState("");
  const [seedCount, setSeedCount] = useState(1);
  const [timeoutSeconds, setTimeoutSeconds] = useState(120);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api<{ items: TalonRecord[] }>("/api/drone/models").then(value => { setModels(value.items); setModelId(value.items[0]?.record_id ?? ""); }).catch(reason => setError(reason instanceof Error ? reason.message : String(reason))); }, []);
  async function submit(event: FormEvent) { event.preventDefault(); setBusy(true); setError(""); try { const result = await api<{ evaluation_id: string }>("/api/drone/evaluations", { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ training_run_id: modelId, seed_count: seedCount, timeout_seconds: timeoutSeconds }) }); router.push(`/talon/evaluations/${result.evaluation_id}`); } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setBusy(false); } }
  return <><PageHeader eyebrow="Strict held-out simulation" title="Evaluate a Talon policy" description="Freeze a checkpoint and evaluate the complete private scenario suite. Active episodes expose no family label or intended outcome." /><TalonBoundaryNotice /><TalonSubnav />{error && <ErrorState message={error} />}{!models.length && !error ? <LoadingState rows={3} label="Loading Talon models" /> : <form className="surface-section" onSubmit={submit}><div className="section-head"><div><span className="eyebrow">Evaluation request</span><h2>Frozen checkpoint</h2></div><ShieldCheck size={19} /></div><div className="field-grid"><label>Frozen model<select value={modelId} onChange={event => setModelId(event.target.value)}>{models.map(model => <option key={model.record_id} value={model.record_id}>{model.record_id}</option>)}</select></label><label>Held-out seed-domain size<input type="number" min={1} max={20} value={seedCount} onChange={event => setSeedCount(Number(event.target.value))} /></label><label>Run timeout (seconds)<input type="number" min={1} max={1800} value={timeoutSeconds} onChange={event => setTimeoutSeconds(Number(event.target.value))} /></label></div><div className="start-confirmation"><div><strong>Strict verifier remains authoritative</strong><p>Public step reward is non-probing, and ordinary utility cannot compensate for a safety violation.</p></div><MotionButton className="button" type="submit" disabled={busy || !modelId}>{busy ? <InlineLoading label="Queuing" /> : "Start evaluation"}</MotionButton></div></form>}</>;
}
