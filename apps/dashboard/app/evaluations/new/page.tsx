"use client";

import { FormEvent, useEffect, useState } from "react";
import { motion } from "motion/react";
import { api } from "@/lib/api";
import type { Provider } from "@/lib/types";
import { ErrorState, LoadingState, PageHeader, ProviderBadge } from "@/components/ui";

export default function NewEvaluationPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providerName, setProviderName] = useState("scripted");
  const [model, setModel] = useState("scripted-valid");
  const [split, setSplit] = useState("eval");
  const [seedStart, setSeedStart] = useState(0);
  const [seedCount, setSeedCount] = useState(1);
  const [attempts, setAttempts] = useState(1);
  const [concurrency, setConcurrency] = useState(1);
  const [temperature, setTemperature] = useState(0);
  const [maxTokens, setMaxTokens] = useState(4096);
  const [reasoning, setReasoning] = useState("medium");
  const [timeout, setTimeoutValue] = useState(60);
  const [retries, setRetries] = useState(2);
  const [maxSteps, setMaxSteps] = useState(64);
  const [maxCalls, setMaxCalls] = useState(64);
  const [wallClock, setWallClock] = useState(600);
  const [tokenBudget, setTokenBudget] = useState("");
  const [costBudget, setCostBudget] = useState("");
  const [deterministic, setDeterministic] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api<{ items: Provider[] }>("/api/providers").then(value => setProviders(value.items)).catch(reason => setError(String(reason))); }, []);
  const provider = providers.find(item => item.provider === providerName);
  const episodeCount = seedCount * attempts;
  const models = provider?.models ?? [];

  function changeProvider(value: string) {
    setProviderName(value);
    const next = providers.find(item => item.provider === value);
    setModel(next?.models[0]?.id ?? "");
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    if (!confirmed) { setError("Confirm the episode count and scoring authority before starting."); return; }
    if (!provider?.ready) { setError("The selected provider is not ready. Check credentials and connectivity in Settings."); return; }
    setSubmitting(true);
    try {
      const payload = {
        provider: providerName, model, split, seed_start: seedStart, seed_count: seedCount,
        attempts, concurrency,
        model_configuration: {
          temperature: provider.capabilities.temperature ? temperature : null,
          max_output_tokens: maxTokens,
          reasoning_effort: provider.capabilities.reasoning_effort ? reasoning : null,
          timeout_seconds: timeout, max_retries: retries,
          deterministic: provider.capabilities.deterministic ? deterministic : false,
        },
        limits: {
          max_steps: maxSteps, max_model_calls: maxCalls,
          input_token_budget: tokenBudget ? Number(tokenBudget) : null,
          output_token_budget: tokenBudget ? Number(tokenBudget) : null,
          cost_budget: costBudget ? Number(costBudget) : null,
          wall_clock_seconds: wallClock,
        },
      };
      const result = await api<{ batch_id: string }>("/api/evaluations", { method: "POST", body: JSON.stringify(payload) });
      location.href = `/evaluations/${result.batch_id}`;
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Evaluation could not be started"); setSubmitting(false); }
  }

  if (!providers.length && !error) return <LoadingState rows={5} />;
  return <>
    <PageHeader eyebrow="Evaluation builder" title="New evaluation" description="Configure provider transport, episode matrix, and hard execution budgets." />
    {error && <ErrorState message={error} />}
    <form className="evaluation-form" onSubmit={submit}>
      <fieldset><legend><span>01</span> Provider and model</legend><div className="field-grid">
        <label>Provider<select value={providerName} onChange={event => changeProvider(event.target.value)}>{providers.map(item => <option key={item.provider} value={item.provider}>{item.display_name}</option>)}</select></label>
        <label>Model{models.length ? <select value={model} onChange={event => setModel(event.target.value)}>{models.map(item => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select> : <input required value={model} pattern="[A-Za-z0-9._:/-]+" onChange={event => setModel(event.target.value)} placeholder="provider/model-name" />}</label>
      </div>{provider && <motion.div layout className={provider.ready ? "provider-status configured" : "provider-status unconfigured"}><ProviderBadge provider={provider.provider} /><strong>{provider.ready ? "Ready" : "Needs attention"}</strong><span>{provider.credential?.state === "missing" ? "Add a session API key in Settings" : provider.endpoint?.state === "unreachable" ? "Provider endpoint is unavailable" : "Ready on the local API"}</span></motion.div>}</fieldset>
      <fieldset><legend><span>02</span> Episode matrix</legend><div className="field-grid four">
        <label>Split<select value={split} onChange={event => setSplit(event.target.value)}><option>eval</option><option>dev</option><option>train</option></select></label>
        <label>Starting seed<input type="number" min="0" value={seedStart} onChange={event => setSeedStart(event.target.valueAsNumber)} /></label>
        <label>Number of seeds<input type="number" min="1" max="100" value={seedCount} onChange={event => setSeedCount(event.target.valueAsNumber)} /></label>
        <label>Attempts per seed<input type="number" min="1" max="20" value={attempts} onChange={event => setAttempts(event.target.valueAsNumber)} /></label>
        <label>Concurrency<input type="number" min="1" max="8" value={concurrency} onChange={event => setConcurrency(event.target.valueAsNumber)} /><small>Defaults conservatively to one.</small></label>
      </div></fieldset>
      <fieldset><legend><span>03</span> Model parameters</legend><div className="field-grid four">
        {provider?.capabilities.temperature && <label>Temperature<input type="number" min="0" max="2" step="0.1" value={temperature} onChange={event => setTemperature(event.target.valueAsNumber)} /></label>}
        <label>Maximum output tokens<input type="number" min="1" value={maxTokens} onChange={event => setMaxTokens(event.target.valueAsNumber)} /></label>
        {provider?.capabilities.reasoning_effort && <label>Reasoning effort<select value={reasoning} onChange={event => setReasoning(event.target.value)}><option>low</option><option>medium</option><option>high</option></select></label>}
        <label>Provider timeout (s)<input type="number" min="1" max="900" value={timeout} onChange={event => setTimeoutValue(event.target.valueAsNumber)} /></label>
        <label>Maximum retries<input type="number" min="0" max="10" value={retries} onChange={event => setRetries(event.target.valueAsNumber)} /></label>
        {provider?.capabilities.deterministic && <label className="check-field"><input type="checkbox" checked={deterministic} onChange={event => setDeterministic(event.target.checked)} />Deterministic mode</label>}
      </div></fieldset>
      <fieldset><legend><span>04</span> Episode budgets</legend><div className="field-grid four">
        <label>Environment steps<input type="number" min="1" max="256" value={maxSteps} onChange={event => setMaxSteps(event.target.valueAsNumber)} /></label>
        <label>Model calls<input type="number" min="1" max="256" value={maxCalls} onChange={event => setMaxCalls(event.target.valueAsNumber)} /></label>
        <label>Wall clock (s)<input type="number" min="1" value={wallClock} onChange={event => setWallClock(event.target.valueAsNumber)} /></label>
        <label>Token budget <small>optional, per direction</small><input type="number" min="1" value={tokenBudget} onChange={event => setTokenBudget(event.target.value)} placeholder="No limit" /></label>
        <label>Cost budget (USD) <small>optional</small><input type="number" min="0" step="0.01" value={costBudget} onChange={event => setCostBudget(event.target.value)} placeholder="No limit" /></label>
      </div></fieldset>
      <section className="start-confirmation"><div><span className="eyebrow">Execution summary</span><strong>{episodeCount} episode{episodeCount === 1 ? "" : "s"}</strong><p>{seedCount} seed{seedCount === 1 ? "" : "s"} × {attempts} attempt{attempts === 1 ? "" : "s"}, up to {concurrency} at once.</p></div><label className="confirm-check"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I understand scores are produced only by the strict verifier.</label><button className="button primary" disabled={submitting || !provider?.ready}>{submitting ? "Starting evaluation…" : providerName === "scripted" ? "Run scripted demonstration" : "Start evaluation"}</button></section>
    </form>
  </>;
}
