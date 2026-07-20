"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Cpu } from "lucide-react";
import { api } from "@/lib/api";
import type { TalonRecord } from "@/lib/types";
import { DataTable, EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { TalonBoundaryNotice, TalonSubnav } from "@/components/talon";

export default function TalonModelsPage() {
  const [models, setModels] = useState<TalonRecord[]>([]);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    api<{ items: TalonRecord[] }>("/api/drone/models")
      .then(value => setModels(value.items))
      .catch(reason => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setLoaded(true));
  }, []);
  return (
    <>
      <PageHeader
        eyebrow="Frozen checkpoints"
        title="Talon models"
        description="Digest-bound learned policies available for strict held-out simulation evaluation."
      />
      <TalonBoundaryNotice />
      <TalonSubnav />
      {error ? (
        <ErrorState message={error} />
      ) : !loaded ? (
        <LoadingState rows={3} label="Loading Talon models" />
      ) : !models.length ? (
        <EmptyState
          title="No models yet"
          detail="Train a policy first. Completed checkpoints from the Train page will appear here for evaluation."
          action={<Link className="button" href="/talon/training/new">Open Train page</Link>}
        />
      ) : (
        <section className="surface-section">
          <div className="section-head">
            <h2>Completed training runs</h2>
            <Cpu size={18} />
          </div>
          <DataTable
            caption="Talon models"
            headers={["Model", "Objective", "Architecture", "Parameters", "Validation accuracy", "Checkpoint"]}
            rows={models.map(model => [
              <Link key="id" className="text-link" href={`/talon/training/${model.record_id}`}>
                <code>{model.record_id}</code>
              </Link>,
              model.algorithm === "discrete_cql" ? "Discrete CQL" : "Behaviour cloning",
              model.architecture ?? "—",
              model.parameter_count?.toLocaleString() ?? "—",
              model.training_metrics ? `${(model.training_metrics.validation_action_accuracy * 100).toFixed(1)}%` : "—",
              <code key="digest">{model.checkpoint_digest?.slice(0, 18)}…</code>,
            ])}
          />
        </section>
      )}
    </>
  );
}
