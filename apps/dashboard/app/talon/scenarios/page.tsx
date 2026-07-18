"use client";

import { useEffect, useState } from "react";
import { ScanSearch } from "lucide-react";
import { api } from "@/lib/api";
import type { TalonCapability } from "@/lib/types";
import { ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { TalonBoundaryNotice, TalonSubnav } from "@/components/talon";

export default function TalonScenariosPage() {
  const [items, setItems] = useState<TalonCapability[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { api<{ items: TalonCapability[] }>("/api/drone/scenarios").then(value => setItems(value.items)).catch(reason => setError(reason instanceof Error ? reason.message : String(reason))); }, []);
  return <><PageHeader eyebrow="Talon catalogue" title="Public decision capabilities" description="This catalogue describes generic skills. Active episodes never disclose their private scenario family, member, seed domain, or intended outcome." /><TalonBoundaryNotice /><TalonSubnav />{error ? <ErrorState message={error} /> : !items.length ? <LoadingState rows={5} /> : <section className="scenario-grid">{items.map(item => <article className="surface-section" key={item.capability_id}><div className="section-head"><ScanSearch size={18} aria-hidden="true" /><code>{item.capability_id}</code></div><h2>{item.title}</h2><p>{item.public_summary}</p><div className="tag-row">{item.safety_focus.map(focus => <code key={focus}>{focus}</code>)}</div></article>)}</section>}<section className="surface-section public-hidden-explainer"><div><span className="eyebrow">Policy-visible</span><h2>Public temporal evidence</h2><p>Bounded track observations, causal evidence requests, public authority state, and prior abstract recommendations.</p></div><div><span className="eyebrow">Privileged runtime</span><h2>Strict verification boundary</h2><p>Private generator state and detailed predicates remain in isolated verifier storage and never enter the dashboard payload.</p></div></section></>;
}
