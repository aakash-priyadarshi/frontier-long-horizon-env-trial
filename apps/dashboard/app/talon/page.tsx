"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Activity, Database, ListChecks, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { TalonRecord } from "@/lib/types";
import { ErrorState, LoadingState, MetricCard, PageHeader, RunStatusBadge } from "@/components/ui";
import { TalonBoundaryNotice, TalonSubnav } from "@/components/talon";

type Health = { total_records: number; completed_evaluations: number; active_records: number; torch_available: boolean };

export default function TalonOverviewPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [capabilityCount, setCapabilityCount] = useState(0);
  const [training, setTraining] = useState<TalonRecord[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([
      api<Health>("/api/drone/health"),
      api<{ total: number }>("/api/drone/scenarios"),
      api<{ items: TalonRecord[] }>("/api/drone/training-runs?limit=4"),
    ]).then(([nextHealth, capabilities, runs]) => {
      setHealth(nextHealth); setCapabilityCount(capabilities.total); setTraining(runs.items);
    }).catch(reason => setError(reason instanceof Error ? reason.message : String(reason)));
  }, []);
  return <>
    <PageHeader eyebrow="Octrayn · Talon" title="Policy-aware decision training" description="A separate deterministic lab for sequential, simulation-only aerial-track decision support." actions={<Link className="button" href="/talon/evaluations/new">New Talon evaluation</Link>} />
    <TalonBoundaryNotice /><TalonSubnav />
    {error ? <ErrorState message={error} /> : !health ? <LoadingState rows={4} /> : <>
      <section className="metric-grid four"><MetricCard label="Public capabilities" value={capabilityCount} detail="Generic evidence and safety skills" /><MetricCard label="Local records" value={health.total_records} detail={`${health.active_records} active`} /><MetricCard label="Completed evaluations" value={health.completed_evaluations} detail="Strict safety results" /><MetricCard label="Training runtime" value={health.torch_available ? "Ready" : "Dependency missing"} tone={health.torch_available ? "success" : "warning"} detail="Optional local PyTorch baseline" /></section>
      <section className="talon-route-grid"><Link href="/talon/scenarios"><ListChecks /><strong>Review capability catalogue</strong><span>Generic evidence, authority, and track-integrity skills.</span></Link><Link href="/talon/datasets"><Database /><strong>Generate private trajectories</strong><span>Versioned training artifacts held outside public records.</span></Link><Link href="/talon/policy"><ShieldCheck /><strong>Review the policy gate</strong><span>Scoped approval and no-external-effect constraints.</span></Link></section>
      <section className="surface-section"><div className="section-head"><div><span className="eyebrow">Recent work</span><h2>Training records</h2></div><Activity size={18} aria-hidden="true" /></div>{training.length ? <div className="record-list">{training.map(record => <Link key={record.record_id} href={`/talon/training/${record.record_id}`}><div><code>{record.record_id}</code><span>{record.architecture ?? "policy"}</span></div><RunStatusBadge status={record.status} /></Link>)}</div> : <p className="muted">No Talon training runs yet.</p>}</section>
    </>}
  </>;
}
