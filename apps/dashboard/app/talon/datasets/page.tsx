"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Database, Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { TalonRecord } from "@/lib/types";
import { MotionButton } from "@/components/motion";
import { DataTable, ErrorState, InlineLoading, LoadingState, PageHeader, RunStatusBadge } from "@/components/ui";
import { TalonBoundaryNotice, TalonSubnav } from "@/components/talon";

export default function TalonDatasetsPage() {
  const [records, setRecords] = useState<TalonRecord[]>([]);
  const [seedCount, setSeedCount] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(() => api<{ items: TalonRecord[] }>("/api/drone/datasets").then(value => setRecords(value.items)), []);
  useEffect(() => { load().catch(reason => setError(reason instanceof Error ? reason.message : String(reason))); }, [load]);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { await api("/api/drone/datasets/generate", { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ seed_count: seedCount, timeout_seconds: 120 }) }); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  }
  return <><PageHeader eyebrow="Private expert trajectories" title="Talon training datasets" description="Generate deterministic training artifacts. Labels and private instance metadata stay outside public API records and exports." /><TalonBoundaryNotice /><TalonSubnav /><section className="surface-section"><div className="section-head"><div><span className="eyebrow">Training partition</span><h2>Generate private dataset</h2></div><Database size={18} /></div><form className="field-grid" onSubmit={submit}><label>Seed-domain size<input type="number" min={1} max={100} value={seedCount} onChange={event => setSeedCount(Number(event.target.value))} /></label><div className="form-action"><MotionButton className="button" type="submit" disabled={busy}>{busy ? <InlineLoading label="Queuing" /> : <><Plus size={15} />Generate</>}</MotionButton></div></form>{error && <ErrorState message={error} />}</section>{!records.length && !error ? <LoadingState rows={3} /> : <section className="surface-section"><h2>Dataset jobs</h2><DataTable caption="Safe Talon dataset records" headers={["Dataset", "Status", "Trajectories", "Digest"]} rows={records.map(record => [<code key="id">{record.record_id}</code>, <RunStatusBadge key="status" status={record.status} />, record.trajectory_count ?? "—", record.dataset_digest ? <code key="digest" title={record.dataset_digest}>{record.dataset_digest.slice(0, 19)}…</code> : "Pending"])} /></section>}</>;
}
