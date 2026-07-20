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

type PolicySource = "checkpoint" | "external_llm" | "scripted_external_baseline";

function algorithmLabel(algorithm: string | undefined) {
  if (algorithm === "discrete_cql") return "Discrete CQL";
  if (algorithm === "behaviour_cloning") return "Behaviour cloning";
  if (algorithm === "external_llm") return "External frontier model";
  if (algorithm === "scripted_external_baseline") return "Scripted external baseline";
  return "—";
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
  const [policySource, setPolicySource] = useState<PolicySource>("checkpoint");
  const [modelId, setModelId] = useState("");
  const [externalModel, setExternalModel] = useState("gpt-4.1-mini");
  const [scriptedModel, setScriptedModel] = useState<"scripted-valid" | "scripted-malformed">("scripted-valid");
  const [seedCount, setSeedCount] = useState(1);
  const [timeoutSeconds, setTimeoutSeconds] = useState(120);
  const [externalTimeout, setExternalTimeout] = useState(30);
  const [providerReady, setProviderReady] = useState<{ ready: boolean; configured: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    const [modelPage, evaluationPage, readiness] = await Promise.all([
      api<{ items: TalonRecord[] }>("/api/drone/models"),
      api<{ items: TalonRecord[] }>("/api/drone/evaluations?limit=100"),
      api<{ ready: boolean; configured: boolean }>("/api/drone/external-llm/readiness").catch(() => ({ ready: false, configured: false })),
    ]);
    setModels(modelPage.items);
    setModelId(current => current || modelPage.items[0]?.record_id || "");
    setEvaluations(evaluationPage.items);
    setProviderReady(readiness);
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
      if (policySource === "checkpoint") {
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
        return;
      }
      const isScripted = policySource === "scripted_external_baseline";
      const result = await api<{ evaluation_id: string }>("/api/drone/external-llm/evaluations", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          policy_kind: policySource,
          provider: isScripted ? "scripted_external" : "openai_compatible",
          model: isScripted ? scriptedModel : externalModel,
          prompt_version: "talon-llm-policy/1.0",
          temperature: 0,
          timeout_seconds: isScripted ? Math.min(externalTimeout, 60) : externalTimeout,
          max_output_tokens: 300,
          attempts_per_scenario: 1,
          scenario_partition: "evaluation",
          seed_count: seedCount,
        }),
      });
      router.push(`/talon/evaluations/${result.evaluation_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBusy(false);
    }
  }

  const showCheckpointForm = policySource === "checkpoint";
  const canSubmitCheckpoint = Boolean(modelId);
  const canSubmitExternal =
    policySource === "scripted_external_baseline" ||
    (policySource === "external_llm" && Boolean(externalModel.trim()));

  return (
    <>
      <PageHeader
        eyebrow="Strict held-out simulation"
        title="Evaluate a Talon policy"
        description="Freeze a checkpoint or evaluate an external recommendation policy against the complete private scenario suite. Active episodes expose no family label or intended outcome."
      />
      <TalonBoundaryNotice />
      <TalonSubnav />
      {error && <ErrorState message={error} retry={() => { setError(""); setLoaded(false); void load().finally(() => setLoaded(true)); }} />}
      {!loaded && !error ? (
        <LoadingState rows={3} label="Loading Talon models and previous evaluations" />
      ) : (
        <>
          <form className="surface-section" onSubmit={submit}>
            <div className="section-head">
              <div>
                <span className="eyebrow">Evaluation request</span>
                <h2>Policy source</h2>
              </div>
              <ShieldCheck size={19} />
            </div>
            <div className="field-grid">
              <label>
                Policy source
                <select
                  aria-label="Policy source"
                  value={policySource}
                  onChange={event => setPolicySource(event.target.value as PolicySource)}
                >
                  <option value="checkpoint">Trained checkpoint</option>
                  <option value="external_llm">External frontier model</option>
                  <option value="scripted_external_baseline">Scripted external baseline</option>
                </select>
              </label>
              <label>
                Held-out seed-domain size
                <input type="number" min={1} max={20} value={seedCount} onChange={event => setSeedCount(Number(event.target.value))} />
              </label>
              {showCheckpointForm ? (
                <label>
                  Run timeout (seconds)
                  <input type="number" min={1} max={1800} value={timeoutSeconds} onChange={event => setTimeoutSeconds(Number(event.target.value))} />
                </label>
              ) : (
                <label>
                  Provider timeout (seconds)
                  <input type="number" min={1} max={300} value={externalTimeout} onChange={event => setExternalTimeout(Number(event.target.value))} />
                </label>
              )}
            </div>

            {showCheckpointForm ? (
              models.length ? (
                <div className="field-grid">
                  <label>
                    Frozen model
                    <select aria-label="Frozen model" value={modelId} onChange={event => setModelId(event.target.value)}>
                      {models.map(model => (
                        <option key={model.record_id} value={model.record_id}>{model.record_id}</option>
                      ))}
                    </select>
                  </label>
                </div>
              ) : (
                <EmptyState
                  title="No models yet"
                  detail="Train a frozen checkpoint first, or switch policy source to an external / scripted baseline."
                  action={<Link className="button" href="/talon/training/new">Open Train page</Link>}
                />
              )
            ) : null}

            {policySource === "external_llm" ? (
              <>
                <div className="field-grid">
                  <label>
                    Provider
                    <input aria-label="Provider" value="OpenAI-compatible" disabled readOnly />
                  </label>
                  <label>
                    Model identifier
                    <input
                      aria-label="Model identifier"
                      value={externalModel}
                      onChange={event => setExternalModel(event.target.value)}
                      placeholder="operator-supplied-model-id"
                    />
                  </label>
                  <label>
                    Temperature
                    <input aria-label="Temperature" value="0 (fixed)" disabled readOnly />
                  </label>
                  <label>
                    Attempts per scenario
                    <input aria-label="Attempts per scenario" value="1" disabled readOnly />
                  </label>
                </div>
                <p className="muted">
                  Provider readiness: {providerReady?.ready ? "credentials configured" : providerReady?.configured ? "endpoint not ready" : "not configured (use scripted baseline for offline verification)"}.
                  Secrets are never displayed.
                </p>
                <aside className="talon-boundary" role="note">
                  <ShieldCheck size={20} aria-hidden="true" />
                  <div>
                    <strong>Simulation-only external models</strong>
                    <p>
                      External models are evaluated as simulation-only recommendation policies. They cannot perform
                      external actions. Every recommendation remains subject to the deterministic policy gate and
                      strict verifier.
                    </p>
                  </div>
                </aside>
              </>
            ) : null}

            {policySource === "scripted_external_baseline" ? (
              <div className="field-grid">
                <label>
                  Scripted baseline
                  <select
                    aria-label="Scripted baseline"
                    value={scriptedModel}
                    onChange={event => setScriptedModel(event.target.value as "scripted-valid" | "scripted-malformed")}
                  >
                    <option value="scripted-valid">scripted-valid (pass parser)</option>
                    <option value="scripted-malformed">scripted-malformed (fail-closed abstention)</option>
                  </select>
                </label>
              </div>
            ) : null}

            <div className="start-confirmation">
              <div>
                <strong>Strict verifier remains authoritative</strong>
                <p>Public step reward is non-probing, and ordinary utility cannot compensate for a safety violation.</p>
              </div>
              <MotionButton
                className="button"
                type="submit"
                disabled={busy || (showCheckpointForm ? !canSubmitCheckpoint : !canSubmitExternal)}
              >
                {busy ? <InlineLoading label="Queuing" /> : "Start evaluation"}
              </MotionButton>
            </div>
          </form>

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
