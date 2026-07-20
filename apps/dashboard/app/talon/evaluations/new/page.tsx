"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { History, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { percent } from "@/lib/format";
import type { TalonRecord } from "@/lib/types";
import { MotionButton } from "@/components/motion";
import { DataTable, EmptyState, ErrorState, InlineLoading, LoadingState, PageHeader, RunStatusBadge } from "@/components/ui";
import { TalonBoundaryNotice, TalonSubnav } from "@/components/talon";

function algorithmLabel(algorithm: string | undefined) {
  return algorithm === "discrete_cql" ? "Discrete CQL" : algorithm === "behaviour_cloning" ? "Behaviour cloning" : "—";
}

function formatWhen(value: string | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function NewTalonEvaluationPage() {
  const router = useRouter();
  const [models, setModels] = useState<TalonRecord[]>([]);
  const [evaluations, setEvaluations] = useState<TalonRecord[]>([]);
  const [modelId, setModelId] = useState("");
  const [seedCount, setSeedCount] = useState(1);
  const [timeoutSeconds, setTimeoutSeconds] = useState(120);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    const [modelPage, evaluationPage] = await Promise.all([
      api<{ items: TalonRecord[] }>("/api/drone/models"),
      api<{ items: TalonRecord[] }>("/api/drone/evaluations?limit=100"),
    ]);
    setModels(modelPage.items);
    setModelId(current => current || modelPage.items[0]?.record_id || "");
    setEvaluations(evaluationPage.items);
  }, []);

  useEffect(() => {
    load()
      .catch(reason => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setLoaded(true));
  }, [load]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<{ evaluation_id: string }>("/api/drone/evaluations", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          training_run_id: modelId,
          seed_count: seedCount,
          timeout_seconds: timeoutSeconds,
        }),
      });
      router.push(`/talon/evaluations/${result.evaluation_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Strict held-out simulation"
        title="Evaluate a Talon policy"
        description="Freeze a checkpoint and evaluate the complete private scenario suite. Active episodes expose no family label or intended outcome."
      />
      <TalonBoundaryNotice />
      <TalonSubnav />
      {error && <ErrorState message={error} retry={() => { setError(""); setLoaded(false); void load().finally(() => setLoaded(true)); }} />}
      {!loaded && !error ? (
        <LoadingState rows={3} label="Loading Talon models and previous evaluations" />
      ) : (
        <>
          {loaded && !models.length && !error ? (
            <EmptyState
              title="No models yet"
              detail="Train a frozen checkpoint first. Completed models from the Train page will appear here for held-out evaluation."
              action={<Link className="button" href="/talon/training/new">Open Train page</Link>}
            />
          ) : models.length ? (
            <form className="surface-section" onSubmit={submit}>
              <div className="section-head">
                <div>
                  <span className="eyebrow">Evaluation request</span>
                  <h2>Frozen checkpoint</h2>
                </div>
                <ShieldCheck size={19} />
              </div>
              <div className="field-grid">
                <label>
                  Frozen model
                  <select value={modelId} onChange={event => setModelId(event.target.value)}>
                    {models.map(model => (
                      <option key={model.record_id} value={model.record_id}>{model.record_id}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Held-out seed-domain size
                  <input type="number" min={1} max={20} value={seedCount} onChange={event => setSeedCount(Number(event.target.value))} />
                </label>
                <label>
                  Run timeout (seconds)
                  <input type="number" min={1} max={1800} value={timeoutSeconds} onChange={event => setTimeoutSeconds(Number(event.target.value))} />
                </label>
              </div>
              <div className="start-confirmation">
                <div>
                  <strong>Strict verifier remains authoritative</strong>
                  <p>Public step reward is non-probing, and ordinary utility cannot compensate for a safety violation.</p>
                </div>
                <MotionButton className="button" type="submit" disabled={busy || !modelId}>
                  {busy ? <InlineLoading label="Queuing" /> : "Start evaluation"}
                </MotionButton>
              </div>
            </form>
          ) : null}

          {!evaluations.length ? (
            <EmptyState
              title="No previous evaluations yet"
              detail="Start an evaluation on this page. Completed and in-progress held-out results will appear here for review."
            />
          ) : (
            <section className="surface-section">
              <div className="section-head">
                <div>
                  <span className="eyebrow">History</span>
                  <h2>Previous evaluation results</h2>
                </div>
                <History size={18} aria-hidden="true" />
              </div>
              <DataTable
                caption="Previous Talon evaluation results"
                headers={["Evaluation", "Status", "Model", "Objective", "Strict success", "Safety violations", "Average score", "Started"]}
                rows={evaluations.map(item => [
                  <Link key="id" className="text-link" href={`/talon/evaluations/${item.record_id}`}>
                    <code>{item.record_id}</code>
                  </Link>,
                  <RunStatusBadge key="status" status={item.status} />,
                  <code key="model">{item.model_id ?? "—"}</code>,
                  algorithmLabel(item.algorithm),
                  item.aggregate ? percent(item.aggregate.strict_success_rate) : "—",
                  item.aggregate?.safety_violation_count ?? "—",
                  item.aggregate?.average_score != null ? item.aggregate.average_score.toFixed(3) : "—",
                  formatWhen(item.created_at),
                ])}
              />
            </section>
          )}
        </>
      )}
    </>
  );
}
