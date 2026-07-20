"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { GraduationCap } from "lucide-react";
import { api } from "@/lib/api";
import type { TalonRecord } from "@/lib/types";
import { MotionButton } from "@/components/motion";
import { EmptyState, ErrorState, InlineLoading, LoadingState, PageHeader } from "@/components/ui";
import { TalonBoundaryNotice, TalonSubnav } from "@/components/talon";

export default function NewTalonTrainingPage() {
  const router = useRouter();
  const [datasets, setDatasets] = useState<TalonRecord[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [architecture, setArchitecture] = useState("gru");
  const [algorithm, setAlgorithm] = useState<"behaviour_cloning" | "discrete_cql">("discrete_cql");
  const [epochs, setEpochs] = useState(50);
  const [learningRate, setLearningRate] = useState(0.0003);
  const [batchSize, setBatchSize] = useState(128);
  const [contextLength, setContextLength] = useState(20);
  const [timeoutSeconds, setTimeoutSeconds] = useState(900);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    api<{ items: TalonRecord[] }>("/api/drone/datasets")
      .then(value => {
        const completed = value.items.filter(item => item.status === "completed");
        setDatasets(completed);
        setDatasetId(completed[0]?.record_id ?? "");
      })
      .catch(reason => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setLoaded(true));
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const endpoint = algorithm === "discrete_cql" ? "/api/drone/offline-rl/training-runs" : "/api/drone/training-runs";
      const configuration = algorithm === "discrete_cql"
        ? {
            dataset_id: datasetId,
            epochs,
            learning_rate: learningRate,
            batch_size: batchSize,
            context_length: contextLength,
            hidden_dim: 256,
            layers: 2,
            dropout: 0.1,
            gamma: 0.99,
            cql_alpha: 1,
            safety_threshold: 0.05,
            target_update_interval: 500,
            gradient_clip: 1,
            random_seed: 0,
            timeout_seconds: timeoutSeconds,
          }
        : {
            dataset_id: datasetId,
            architecture,
            epochs,
            learning_rate: learningRate,
            batch_size: batchSize,
            context_length: contextLength,
            random_seed: 0,
            timeout_seconds: timeoutSeconds,
          };
      const result = await api<{ training_run_id: string }>(endpoint, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify(configuration),
      });
      router.push(`/talon/training/${result.training_run_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeader
        eyebrow="Offline policy learning"
        title="Train a Talon policy"
        description="Train conservative discrete CQL or a supervised baseline on authenticated private trajectories. No online exploration occurs."
      />
      <TalonBoundaryNotice />
      <TalonSubnav />
      {error && <ErrorState message={error} />}
      {!loaded && !error ? (
        <LoadingState rows={3} label="Loading completed training datasets" />
      ) : loaded && !datasets.length && !error ? (
        <EmptyState
          title="No completed datasets yet"
          detail="Generate a private training dataset first. Once a dataset job completes, return here to start training."
          action={<Link className="button" href="/talon/datasets">Open Datasets page</Link>}
        />
      ) : datasets.length ? (
        <form className="surface-section" onSubmit={submit}>
          <div className="section-head">
            <div>
              <span className="eyebrow">Configuration</span>
              <h2>{algorithm === "discrete_cql" ? "Conservative offline RL" : "Behaviour cloning"}</h2>
            </div>
            <GraduationCap size={19} />
          </div>
          <div className="field-grid">
            <label>
              Training objective
              <select value={algorithm} onChange={event => setAlgorithm(event.target.value as typeof algorithm)}>
                <option value="discrete_cql">Discrete CQL (recommended)</option>
                <option value="behaviour_cloning">Supervised baseline</option>
              </select>
            </label>
            <label>
              Dataset
              <select required value={datasetId} onChange={event => setDatasetId(event.target.value)}>
                {datasets.map(item => (
                  <option value={item.record_id} key={item.record_id}>{item.record_id}</option>
                ))}
              </select>
            </label>
            {algorithm === "behaviour_cloning" && (
              <label>
                Architecture
                <select value={architecture} onChange={event => setArchitecture(event.target.value)}>
                  <option value="gru">GRU baseline</option>
                  <option value="decision_transformer">Decision Transformer</option>
                </select>
              </label>
            )}
            <label>
              Epochs
              <input type="number" min={1} max={500} value={epochs} onChange={event => setEpochs(Number(event.target.value))} />
            </label>
            <label>
              Learning rate
              <input type="number" min="0.000001" max="1" step="0.0001" value={learningRate} onChange={event => setLearningRate(Number(event.target.value))} />
            </label>
            <label>
              Batch size
              <input type="number" min={1} max={4096} value={batchSize} onChange={event => setBatchSize(Number(event.target.value))} />
            </label>
            <label>
              Context length
              <input type="number" min={1} max={64} value={contextLength} onChange={event => setContextLength(Number(event.target.value))} />
            </label>
            <label>
              Worker timeout (seconds)
              <input type="number" min={1} max={7200} value={timeoutSeconds} onChange={event => setTimeoutSeconds(Number(event.target.value))} />
            </label>
          </div>
          {algorithm === "discrete_cql" && (
            <div className="start-confirmation">
              <div>
                <strong>Conservative defaults</strong>
                <p>gamma 0.99 · CQL alpha 1.0 · safety threshold 0.05 · target update 500 · gradient clip 1.0. Reward and safety costs remain separate.</p>
              </div>
            </div>
          )}
          <div className="start-confirmation">
            <div>
              <strong>Training cannot weaken the policy gate</strong>
              <p>Static private data only. The policy gate and strict verifier remain authoritative.</p>
            </div>
            <MotionButton className="button" type="submit" disabled={busy || !datasetId}>
              {busy ? <InlineLoading label="Queuing" /> : "Start training"}
            </MotionButton>
          </div>
        </form>
      ) : null}
    </>
  );
}
