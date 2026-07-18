"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { GitCompare } from "lucide-react";
import { api } from "@/lib/api";
import type { TalonRecord } from "@/lib/types";
import { DataTable, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { TalonBoundaryNotice, TalonSubnav } from "@/components/talon";

export default function TalonComparePage() {
  const [items, setItems] = useState<TalonRecord[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { api<{ items: TalonRecord[] }>("/api/drone/evaluations").then(value => setItems(value.items)).catch(reason => setError(reason instanceof Error ? reason.message : String(reason))); }, []);
  return <><PageHeader eyebrow="Safety comparison" title="Talon evaluation history" description="Compare strict success and worst-case safety outcomes without exposing private scenario membership." /><TalonBoundaryNotice /><TalonSubnav />{error ? <ErrorState message={error} /> : !items.length ? <LoadingState rows={4} /> : <section className="surface-section"><div className="section-head"><h2>Evaluation records</h2><GitCompare size={18} /></div><DataTable caption="Talon evaluation comparison" headers={["Evaluation", "Model", "Status", "Episodes", "Strict success", "Safety violations", "Average score"]} rows={items.map(item => [<Link className="text-link" key="id" href={`/talon/evaluations/${item.record_id}`}><code>{item.record_id}</code></Link>, <code key="model">{item.model_id ?? "—"}</code>, item.status, item.aggregate?.episode_count ?? "—", item.aggregate ? `${(item.aggregate.strict_success_rate * 100).toFixed(1)}%` : "—", item.aggregate?.safety_violation_count ?? "—", item.aggregate?.average_score?.toFixed(3) ?? "—"])} /></section>}</>;
}
