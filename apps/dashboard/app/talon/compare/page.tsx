"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { GitCompare } from "lucide-react";
import { api, APIRequestError } from "@/lib/api";
import type { TalonRecord } from "@/lib/types";
import { TalonHeldOutComparisonChart, TalonSameInstanceSyncChart } from "@/components/charts";
import { MotionButton } from "@/components/motion";
import { DataTable, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { TalonBoundaryNotice, TalonSubnav } from "@/components/talon";

function algorithmLabel(algorithm: string | undefined) {
  return algorithm === "discrete_cql" ? "Discrete CQL" : "Behaviour cloning";
}

export default function TalonComparePage() {
  const [comparisons, setComparisons] = useState<TalonRecord[] | null>(null);
  const [evaluations, setEvaluations] = useState<TalonRecord[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [comparisonPage, evaluationPage] = await Promise.all([
      api<{ items: TalonRecord[] }>("/api/drone/comparisons"),
      api<{ items: TalonRecord[] }>("/api/drone/evaluations?limit=200"),
    ]);
    setComparisons(comparisonPage.items);
    setEvaluations(evaluationPage.items.filter(item => item.status === "completed"));
  }, []);

  useEffect(() => {
    load().catch(reason => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [load]);

  const selectedSet = useMemo(() => new Set(selected), [selected]);

  function toggle(evaluationId: string) {
    setSelected(current => current.includes(evaluationId)
      ? current.filter(item => item !== evaluationId)
      : current.length >= 8 ? current : [...current, evaluationId]);
  }

  async function createComparison() {
    if (selected.length < 2) {
      setError("Select at least two completed evaluations that share the same simulation domain.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api("/api/drone/comparisons", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ evaluation_ids: selected }),
      });
      setSelected([]);
      await load();
    } catch (reason) {
      const message = reason instanceof APIRequestError
        ? `${reason.code}: ${reason.message}`
        : reason instanceof Error ? reason.message : String(reason);
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  return <>
    <PageHeader
      eyebrow="Safety comparison"
      title="Talon model comparisons"
      description="Create immutable, domain-bound comparison records across frozen scripted, supervised, transformer and CQL policies on deterministic held-out simulation suites."
    />
    <TalonBoundaryNotice />
    <TalonSubnav />
    {error ? <ErrorState message={error} retry={() => { setError(""); void load(); }} /> : null}
    {comparisons === null && !error ? <LoadingState rows={4} /> : <>
      <section className="surface-section">
        <div className="section-head">
          <div>
            <span className="eyebrow">Simulation-only inputs</span>
            <h2>Create domain-compatible comparison</h2>
          </div>
          <GitCompare size={18} />
        </div>
        <p className="muted">Comparisons are valid only when environment, verifier, observation and action schema versions match. Incompatible records must be re-evaluated; the dashboard never coerces them.</p>
        {!evaluations.length ? <p className="muted">No completed evaluations are available yet.</p> : (
          <DataTable
            caption="Completed evaluations available for comparison"
            headers={["Include", "Evaluation", "Model", "Objective", "Strict success", "Safety violations", "Average score"]}
            rows={evaluations.map(item => [
              <input
                key="check"
                type="checkbox"
                aria-label={`Include ${item.record_id}`}
                checked={selectedSet.has(item.record_id)}
                onChange={() => toggle(item.record_id)}
              />,
              <Link className="text-link" key="id" href={`/talon/evaluations/${item.record_id}`}><code>{item.record_id}</code></Link>,
              <code key="model">{item.model_id ?? "—"}</code>,
              algorithmLabel(item.algorithm),
              item.aggregate ? `${(item.aggregate.strict_success_rate * 100).toFixed(1)}%` : "—",
              item.aggregate?.safety_violation_count ?? "—",
              item.aggregate?.average_score?.toFixed(3) ?? "—",
            ])}
          />
        )}
        <div className="form-action">
          <MotionButton className="button" disabled={busy || selected.length < 2} onClick={() => void createComparison()}>
            {busy ? "Creating…" : `Create comparison (${selected.length})`}
          </MotionButton>
        </div>
      </section>

      <section className="surface-section">
        <div className="section-head">
          <div>
            <span className="eyebrow">Immutable records</span>
            <h2>Stored comparisons</h2>
          </div>
        </div>
        {!comparisons?.length ? <p className="muted">No comparison records yet. Create one from completed simulation evaluations above.</p> : comparisons.map(comparison => (
          <div key={comparison.record_id} className="comparison-record">
            <div className="section-head">
              <div>
                <span className="eyebrow">Comparison</span>
                <h3><code>{comparison.record_id}</code></h3>
              </div>
              <p className="muted">Digest {comparison.record_digest ?? "—"}</p>
            </div>
            <dl className="detail-grid">
              <div><dt>Domain compatible</dt><dd>{comparison.compatibility?.domain_compatible ? "yes" : "no"}</dd></div>
              <div><dt>Runtime versions compatible</dt><dd>{comparison.compatibility?.runtime_versions_compatible ? "yes" : "no"}</dd></div>
              <div><dt>Status</dt><dd>{comparison.status}</dd></div>
              <div><dt>Models</dt><dd>{comparison.models?.length ?? 0}</dd></div>
              <div><dt>Synchronized instances</dt><dd>{comparison.aligned_instances?.length ?? 0}</dd></div>
            </dl>
            {(comparison.results?.length ?? 0) > 0 && (
              <div className="comparison-charts">
                <TalonHeldOutComparisonChart results={comparison.results ?? []} models={comparison.models} />
                <TalonSameInstanceSyncChart aligned={comparison.aligned_instances ?? []} models={comparison.models} />
              </div>
            )}
            <DataTable
              caption={`Synchronized comparison results for ${comparison.record_id}`}
              headers={["Evaluation", "Model", "Objective", "Episodes", "Strict success", "Held-out accuracy", "Safety violations", "Gate intervention", "Worst case", "Average score"]}
              rows={(comparison.results ?? []).map(result => {
                const model = comparison.models?.find(item => item.evaluation_id === result.evaluation_id);
                const aggregate = result.aggregate;
                return [
                  <Link className="text-link" key="id" href={`/talon/evaluations/${result.evaluation_id}`}><code>{result.evaluation_id}</code></Link>,
                  <code key="model">{model?.model_id ?? "—"}</code>,
                  algorithmLabel(model?.algorithm),
                  aggregate?.episode_count ?? "—",
                  aggregate ? `${(aggregate.strict_success_rate * 100).toFixed(1)}%` : "—",
                  aggregate?.held_out_action_accuracy != null ? `${(aggregate.held_out_action_accuracy * 100).toFixed(1)}%` : "—",
                  aggregate?.safety_violation_count ?? "—",
                  aggregate?.gate_intervention_rate != null ? `${(aggregate.gate_intervention_rate * 100).toFixed(1)}%` : "—",
                  aggregate?.worst_case_score?.toFixed(3) ?? "—",
                  aggregate?.average_score?.toFixed(3) ?? "—",
                ];
              })}
            />
            {(comparison.aligned_instances?.length ?? 0) > 0 && (
              <DataTable
                caption={`Same-instance synchronized outcomes for ${comparison.record_id}`}
                headers={["Instance", ...((comparison.models ?? []).map(model => model.model_id ?? model.evaluation_id)), "Agreement"]}
                rows={(comparison.aligned_instances ?? []).map(instance => {
                  const successes = instance.outcomes.map(outcome => outcome.strict_success);
                  const agreement = successes.every(value => value === successes[0]) ? "aligned" : "diverged";
                  return [
                    `Instance ${instance.instance_index}`,
                    ...(comparison.models ?? []).map(model => {
                      const outcome = instance.outcomes.find(item => item.evaluation_id === model.evaluation_id);
                      if (!outcome) return "—";
                      return `${outcome.strict_success ? "pass" : "fail"} · ${(outcome.score ?? 0).toFixed(2)} · s${outcome.safety_violation_count}`;
                    }),
                    agreement,
                  ];
                })}
              />
            )}
          </div>
        ))}
      </section>

      <section className="surface-section">
        <h2>Non-compensable safety interpretation</h2>
        <p className="muted">Operational score is shown beside safety outcomes, never combined with them. A high operational average cannot erase a safety violation or produce strict success. All values here are simulation-only decision-support metrics.</p>
      </section>
    </>}
  </>;
}
