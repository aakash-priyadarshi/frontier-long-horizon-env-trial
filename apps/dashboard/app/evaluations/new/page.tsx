"use client";

import { FormEvent, type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { Check, Cpu, FlaskConical, Search, ShieldCheck, Sparkles } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { api } from "@/lib/api";
import type { Provider } from "@/lib/types";
import { money, number } from "@/lib/format";
import { MotionButton, SharedSelectionIndicator } from "@/components/motion";
import { ErrorState, InlineLoading, LoadingState, PageHeader, ProviderBadge } from "@/components/ui";

const RECENT_MODELS_KEY = "frontier-recent-models";

export default function NewEvaluationPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providerName, setProviderName] = useState("scripted");
  const [model, setModel] = useState("scripted-valid");
  const [modelSearch, setModelSearch] = useState("");
  const [recentModels, setRecentModels] = useState<string[]>([]);
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
  const reviewRef = useRef<HTMLFieldSetElement>(null);

  useEffect(() => {
    api<{ items: Provider[] }>("/api/providers").then(value => setProviders(value.items)).catch(reason => setError(reason instanceof Error ? reason.message : String(reason)));
    try {
      const stored = JSON.parse(localStorage.getItem(RECENT_MODELS_KEY) ?? "[]");
      if (Array.isArray(stored) && stored.every(item => typeof item === "string")) setRecentModels(stored.slice(0, 5));
    } catch { localStorage.removeItem(RECENT_MODELS_KEY); }
  }, []);

  const provider = providers.find(item => item.provider === providerName);
  const episodeCount = seedCount * attempts;
  const models = provider?.models ?? [];
  const filteredModels = useMemo(() => models.filter(item => `${item.display_name} ${item.id}`.toLowerCase().includes(modelSearch.toLowerCase())), [modelSearch, models]);
  const recentForProvider = recentModels.filter(item => item.startsWith(`${providerName}:`)).map(item => item.slice(providerName.length + 1)).filter(id => models.some(item => item.id === id));

  function changeProvider(value: string) {
    setProviderName(value);
    const next = providers.find(item => item.provider === value);
    setModel(next?.models[0]?.id ?? "");
    setModelSearch("");
    setConfirmed(false);
  }

  function moveRadio(event: KeyboardEvent<HTMLButtonElement>, values: string[], current: string, choose: (value: string) => void) {
    if (!values.length || !["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const currentIndex = Math.max(0, values.indexOf(current));
    const nextIndex = event.key === "Home" ? 0
      : event.key === "End" ? values.length - 1
        : ["ArrowRight", "ArrowDown"].includes(event.key) ? (currentIndex + 1) % values.length
          : (currentIndex - 1 + values.length) % values.length;
    choose(values[nextIndex]);
    const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="radio"]');
    buttons?.[nextIndex]?.focus();
  }

  function scriptedShortcut() {
    changeProvider("scripted");
    setModel("scripted-valid");
    window.requestAnimationFrame(() => reviewRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    if (!confirmed) { setError("Confirm the episode count and scoring authority before starting."); return; }
    if (!provider?.ready) { setError("The selected provider is not ready. Check credentials and connectivity in Settings."); return; }
    if (!model) { setError("Choose or enter a model before starting."); return; }
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
      const key = `${providerName}:${model}`;
      const nextRecent = [key, ...recentModels.filter(item => item !== key)].slice(0, 5);
      localStorage.setItem(RECENT_MODELS_KEY, JSON.stringify(nextRecent));
      const result = await api<{ batch_id: string }>("/api/evaluations", { method: "POST", body: JSON.stringify(payload) });
      location.href = `/evaluations/${result.batch_id}`;
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Evaluation could not be started"); setSubmitting(false); }
  }

  if (!providers.length && !error) return <LoadingState rows={5} label="Loading evaluation builder" />;
  return <>
    <PageHeader eyebrow="Evaluation builder" title="New evaluation" description="Choose a capable provider, define the episode matrix, and review hard execution limits before launch." actions={<MotionButton className="button secondary" onClick={scriptedShortcut}><FlaskConical size={16} aria-hidden="true" />Scripted demo shortcut</MotionButton>} />
    <AnimatePresence>{error && <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}><ErrorState message={error} /></motion.div>}</AnimatePresence>
    <form className="evaluation-form" onSubmit={submit}>
      <div className="evaluation-layout">
        <div className="evaluation-main">
          <fieldset><legend><span>01</span> Provider and model</legend>
            <div className="provider-choice-grid" role="radiogroup" aria-label="Evaluation provider">
              {providers.map(item => {
                const selected = item.provider === providerName;
                const reason = item.credential.state === "missing" ? "API key required" : item.endpoint.state === "unreachable" ? "Endpoint unavailable" : item.ready ? "Ready" : "Needs attention";
                return <MotionButton type="button" role="radio" aria-checked={selected} tabIndex={selected ? 0 : -1} className={`provider-choice${selected ? " selected" : ""}`} key={item.provider} onClick={() => changeProvider(item.provider)} onKeyDown={event => moveRadio(event, providers.map(option => option.provider), providerName, changeProvider)}>
                  {selected && <SharedSelectionIndicator layoutId="evaluation-provider-selection" />}
                  <span><ProviderBadge provider={item.provider} /><strong>{item.display_name}</strong></span>
                  <small className={item.ready ? "success" : "warning"}>{reason}</small>
                </MotionButton>;
              })}
            </div>
            {provider && <div className={provider.ready ? "provider-status configured" : "provider-status unconfigured"}><div><Cpu size={16} aria-hidden="true" /><strong>{provider.ready ? "Ready to evaluate" : "Configuration required"}</strong></div><span>{provider.credential.state === "missing" ? "Add a session API key in Settings" : provider.endpoint.state === "unreachable" ? "Provider endpoint is unavailable" : `${provider.model_discovery.count} discovered model${provider.model_discovery.count === 1 ? "" : "s"}`}</span></div>}
            <div className="model-picker">
              <div className="model-picker-head"><div><span className="field-title">Model</span><small>Select a discovered model or enter a supported custom identifier.</small></div>{models.length > 1 && <label className="search-field"><span className="sr-only">Search models</span><Search size={15} aria-hidden="true" /><input type="search" value={modelSearch} onChange={event => setModelSearch(event.target.value)} placeholder="Search models" /></label>}</div>
              {recentForProvider.length > 0 && <div className="recent-models"><span>Recent</span>{recentForProvider.map(id => <MotionButton type="button" className="model-chip" key={id} onClick={() => setModel(id)}>{id}</MotionButton>)}</div>}
              {models.length ? <div className="model-option-grid" role="radiogroup" aria-label="Evaluation model">{filteredModels.map(item => <MotionButton type="button" role="radio" aria-checked={model === item.id} tabIndex={model === item.id ? 0 : -1} className={model === item.id ? "model-option selected" : "model-option"} key={item.id} onClick={() => setModel(item.id)} onKeyDown={event => moveRadio(event, filteredModels.map(option => option.id), model, setModel)}>{model === item.id && <Check size={15} aria-hidden="true" />}<span><strong>{item.display_name}</strong><code>{item.id}</code></span>{item.tool_compatibility?.state === "passed" && <small className="success">Tool tested</small>}</MotionButton>)}</div> : provider?.capabilities.custom_model ? <label>Model identifier<input required value={model} pattern="[A-Za-z0-9._:/-]+" onChange={event => setModel(event.target.value)} placeholder="provider/model-name" /></label> : <p className="muted">This provider does not expose a manual model option.</p>}
              {models.length > 0 && !filteredModels.length && <p className="no-results">No models match “{modelSearch}”.</p>}
              {provider && <div className="capability-list" aria-label="Selected provider capabilities"><span className={provider.capabilities.temperature ? "available" : "unavailable"}>Temperature</span><span className={provider.capabilities.reasoning_effort ? "available" : "unavailable"}>Reasoning effort</span><span className={provider.capabilities.deterministic ? "available" : "unavailable"}>Deterministic mode</span><span className={provider.capabilities.tool_probe ? "available" : "unavailable"}>Tool probe</span></div>}
            </div>
          </fieldset>

          <fieldset><legend><span>02</span> Environment and seeds</legend><div className="field-grid four">
            <label>Split<select value={split} onChange={event => setSplit(event.target.value)}><option>eval</option><option>dev</option><option>train</option></select></label>
            <label>Starting seed<input type="number" min="0" value={seedStart} onChange={event => setSeedStart(event.target.valueAsNumber)} /></label>
            <label>Number of seeds<input type="number" min="1" max="100" value={seedCount} onChange={event => setSeedCount(event.target.valueAsNumber)} /></label>
            <label>Attempts per seed<input type="number" min="1" max="20" value={attempts} onChange={event => setAttempts(event.target.valueAsNumber)} /></label>
          </div><div className="section-helper"><ShieldCheck size={16} aria-hidden="true" /><span>Each episode uses the existing environment and immutable strict verifier. Seeds change public instances, not scoring authority.</span></div></fieldset>

          <fieldset><legend><span>03</span> Limits, concurrency and budgets</legend>
            <div className="form-subsection"><h2>Execution</h2><div className="field-grid four"><label>Concurrency<input type="number" min="1" max="8" value={concurrency} onChange={event => setConcurrency(event.target.valueAsNumber)} /><small>Defaults conservatively to one.</small></label><label>Environment steps<input type="number" min="1" max="256" value={maxSteps} onChange={event => setMaxSteps(event.target.valueAsNumber)} /></label><label>Model calls<input type="number" min="1" max="256" value={maxCalls} onChange={event => setMaxCalls(event.target.valueAsNumber)} /></label><label>Wall clock (s)<input type="number" min="1" value={wallClock} onChange={event => setWallClock(event.target.valueAsNumber)} /></label></div></div>
            <div className="form-subsection"><h2>Provider request</h2><div className="field-grid four">{provider?.capabilities.temperature && <label>Temperature<input type="number" min="0" max="2" step="0.1" value={temperature} onChange={event => setTemperature(event.target.valueAsNumber)} /></label>}<label>Maximum output tokens<input type="number" min="1" value={maxTokens} onChange={event => setMaxTokens(event.target.valueAsNumber)} /></label>{provider?.capabilities.reasoning_effort && <label>Reasoning effort<select value={reasoning} onChange={event => setReasoning(event.target.value)}><option>low</option><option>medium</option><option>high</option></select></label>}<label>Provider timeout (s)<input type="number" min="1" max="900" value={timeout} onChange={event => setTimeoutValue(event.target.valueAsNumber)} /></label><label>Maximum retries<input type="number" min="0" max="10" value={retries} onChange={event => setRetries(event.target.valueAsNumber)} /></label>{provider?.capabilities.deterministic && <label className="check-field"><input type="checkbox" checked={deterministic} onChange={event => setDeterministic(event.target.checked)} />Deterministic mode</label>}</div></div>
            <div className="form-subsection"><h2>Optional ceilings</h2><div className="field-grid"><label>Token budget <small>per direction</small><input type="number" min="1" value={tokenBudget} onChange={event => setTokenBudget(event.target.value)} placeholder="No limit" /></label><label>Cost budget (USD)<input type="number" min="0" step="0.01" value={costBudget} onChange={event => setCostBudget(event.target.value)} placeholder="No limit" /></label></div></div>
          </fieldset>
        </div>

        <fieldset className="evaluation-summary" ref={reviewRef}><legend><span>04</span> Review and run</legend>
          <div className="summary-emblem"><Sparkles size={18} aria-hidden="true" /><span>Ready for review</span></div>
          <strong className="episode-total">{episodeCount} episode{episodeCount === 1 ? "" : "s"}</strong>
          <p>{seedCount} seed{seedCount === 1 ? "" : "s"} × {attempts} attempt{attempts === 1 ? "" : "s"}, with up to {concurrency} active at once.</p>
          <dl className="summary-list"><div><dt>Provider</dt><dd>{provider?.display_name ?? "—"}</dd></div><div><dt>Model</dt><dd><code>{model || "Not selected"}</code></dd></div><div><dt>Environment</dt><dd>{split} · seeds {seedStart}–{seedStart + seedCount - 1}</dd></div><div><dt>Hard limits</dt><dd>{maxSteps} steps · {maxCalls} calls · {wallClock}s</dd></div><div><dt>Token budget</dt><dd>{tokenBudget ? `${number(Number(tokenBudget), 0)} each direction` : "No limit"}</dd></div><div><dt>Cost budget</dt><dd>{costBudget ? money(Number(costBudget)) : "No limit"}</dd></div></dl>
          <label className="confirm-check"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I understand scores are produced only by the strict verifier.</label>
          {!provider?.ready && <p className="summary-warning" role="status">This provider cannot start yet. Open Settings to resolve its credential or endpoint status.</p>}
          <MotionButton className="button primary summary-submit" type="submit" disabled={submitting || !provider?.ready || !model || !confirmed}>{submitting ? <InlineLoading label="Starting evaluation" /> : providerName === "scripted" ? "Run scripted demonstration" : "Start evaluation"}</MotionButton>
        </fieldset>
      </div>
    </form>
  </>;
}
