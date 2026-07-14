"use client";

import { FormEvent, type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { Check, Cpu, FlaskConical, RefreshCw, Search, ShieldCheck, Sparkles } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { api } from "@/lib/api";
import { EVALUATION_PRESETS, evaluationPresetValues, type EvaluationPresetId } from "@/lib/evaluation-presets";
import type { Provider } from "@/lib/types";
import { money, number } from "@/lib/format";
import { MotionButton, SharedSelectionIndicator } from "@/components/motion";
import { ErrorState, InlineLoading, LoadingState, PageHeader, ProviderBadge } from "@/components/ui";

const RECENT_MODELS_KEY = "frontier-recent-models";
type ProviderResult = { provider: Provider };

export default function NewEvaluationPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providerName, setProviderName] = useState("scripted");
  const [model, setModel] = useState("scripted-valid");
  const [modelSearch, setModelSearch] = useState("");
  const [recentModels, setRecentModels] = useState<string[]>([]);
  const [modelDiscoveryBusy, setModelDiscoveryBusy] = useState<Record<string, boolean>>({});
  const [modelMessages, setModelMessages] = useState<Record<string, string>>({});
  const [split, setSplit] = useState("eval");
  const [seedStart, setSeedStart] = useState(0);
  const [seedCount, setSeedCount] = useState(1);
  const [attempts, setAttempts] = useState(1);
  const [concurrency, setConcurrency] = useState(1);
  const [temperature, setTemperature] = useState(0);
  const [maxTokens, setMaxTokens] = useState(4096);
  const [contextWindow, setContextWindow] = useState(16384);
  const [reasoning, setReasoning] = useState("low");
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
  const selectedModel = models.find(item => item.id === model);
  const toolCompatibilityFailed = selectedModel?.tool_compatibility?.state === "failed";
  const ollamaToolTestRequired = providerName === "ollama" && Boolean(selectedModel) && selectedModel?.tool_compatibility?.state !== "passed";
  const toolCompatibilityBlocked = toolCompatibilityFailed || ollamaToolTestRequired;
  const filteredModels = useMemo(() => models.filter(item => `${item.display_name} ${item.id}`.toLowerCase().includes(modelSearch.toLowerCase())), [modelSearch, models]);
  const recentForProvider = recentModels.filter(item => item.startsWith(`${providerName}:`)).map(item => item.slice(providerName.length + 1)).filter(id => models.some(item => item.id === id));

  function replaceProvider(next: Provider) {
    setProviders(current => current.map(item => item.provider === next.provider ? next : item));
  }

  async function discoverModels(value: string) {
    setModelDiscoveryBusy(current => ({ ...current, [value]: true }));
    setModelMessages(current => ({ ...current, [value]: "" }));
    try {
      const result = await api<ProviderResult>(`/api/providers/${value}/connection-test`, { method: "POST" });
      replaceProvider(result.provider);
      if (value === "ollama") {
        setModel(current => result.provider.models.some(item => item.id === current) ? current : "");
      }
      const count = result.provider.models.length;
      setModelMessages(current => ({
        ...current,
        [value]: count ? `${count} model${count === 1 ? "" : "s"} available to select.` : value === "ollama" ? "No locally installed Ollama models were detected." : "The provider returned no compatible models; manual entry remains available.",
      }));
    } catch (reason) {
      setModelMessages(current => ({ ...current, [value]: reason instanceof Error ? reason.message : "Model discovery failed." }));
    } finally {
      setModelDiscoveryBusy(current => ({ ...current, [value]: false }));
    }
  }

  function changeProvider(value: string) {
    setProviderName(value);
    const next = providers.find(item => item.provider === value);
    setModel(next?.models[0]?.id ?? "");
    setModelSearch("");
    setConfirmed(false);
    if (
      next
      && value !== "scripted"
      && value !== "ollama"
      && next.configured
      && next.capabilities.model_discovery
      && next.model_discovery.state === "not_tested"
    ) {
      void discoverModels(value);
    }
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

  function applyPreset(id: EvaluationPresetId) {
    const values = evaluationPresetValues(id, providerName);
    setSplit(values.split);
    setSeedStart(values.seedStart);
    setSeedCount(values.seedCount);
    setAttempts(values.attempts);
    setConcurrency(values.concurrency);
    setTemperature(values.temperature);
    setMaxTokens(values.maxTokens);
    setContextWindow(values.contextWindow);
    setReasoning(values.reasoning);
    setTimeoutValue(values.timeout);
    setRetries(values.retries);
    setMaxSteps(values.maxSteps);
    setMaxCalls(values.maxCalls);
    setWallClock(values.wallClock);
    setTokenBudget("");
    setCostBudget("");
    setDeterministic(values.deterministic);
    setConfirmed(false);
    setError("");
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    if (!confirmed) { setError("Confirm the episode count and scoring authority before starting."); return; }
    if (!provider?.ready) { setError("The selected provider is not ready. Check credentials and connectivity in Settings."); return; }
    if (!model) { setError("Choose or enter a model before starting."); return; }
    if (toolCompatibilityBlocked) { setError("The selected model must pass structured tool compatibility. Test it in Settings, then return to start the evaluation."); return; }
    setSubmitting(true);
    try {
      const payload = {
        provider: providerName, model, split, seed_start: seedStart, seed_count: seedCount,
        attempts, concurrency,
        model_configuration: {
          temperature: provider.capabilities.temperature ? temperature : null,
          max_output_tokens: maxTokens,
          context_window: providerName === "ollama" ? contextWindow : null,
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
              <div className="model-picker-head"><div><span className="field-title">Model</span><small>{providerName === "ollama" ? "Detect and select a model installed in your local Ollama library." : "Choose a provider model below or enter a supported model identifier."}</small></div>{models.length > 1 && <label className="search-field"><span className="sr-only">Search models</span><Search size={15} aria-hidden="true" /><input type="search" value={modelSearch} onChange={event => setModelSearch(event.target.value)} placeholder="Search models" /></label>}</div>
              {providerName === "ollama" && <div className="model-discovery-bar"><div><strong>Local model detection</strong><span>Reads Ollama&apos;s local model inventory; no download is started.</span></div><MotionButton type="button" className="button secondary" disabled={modelDiscoveryBusy.ollama} onClick={() => void discoverModels("ollama")}>{modelDiscoveryBusy.ollama ? <InlineLoading label="Detecting models" /> : <><RefreshCw size={15} aria-hidden="true" />{models.length ? "Refresh installed models" : "Detect installed models"}</>}</MotionButton></div>}
              {provider?.capabilities.custom_model && <label>Model identifier<input required readOnly={providerName === "ollama"} value={model} pattern="[A-Za-z0-9._:/-]+" onChange={event => setModel(event.target.value)} placeholder={providerName === "ollama" ? "Detect and select an installed model" : "provider/model-name"} /></label>}
              {modelMessages[providerName] && <p className="model-discovery-message" role="status">{modelMessages[providerName]}</p>}
              {modelDiscoveryBusy[providerName] && providerName !== "ollama" && <InlineLoading label="Loading available models" />}
              {recentForProvider.length > 0 && <div className="recent-models"><span>Recent</span>{recentForProvider.map(id => <MotionButton type="button" className="model-chip" key={id} onClick={() => setModel(id)}>{id}</MotionButton>)}</div>}
              {models.length > 0 && <div className="model-option-label"><span>{providerName === "ollama" ? "Installed locally" : providerName === "scripted" ? "Built-in models" : "Available from provider"}</span><small>Choose an option to fill the model identifier.</small></div>}
              {models.length > 0 && <div className="model-option-grid" role="radiogroup" aria-label="Evaluation model">{filteredModels.map((item, index) => <MotionButton type="button" role="radio" aria-checked={model === item.id} tabIndex={model === item.id || (!model && index === 0) ? 0 : -1} className={model === item.id ? "model-option selected" : "model-option"} key={item.id} onClick={() => setModel(item.id)} onKeyDown={event => moveRadio(event, filteredModels.map(option => option.id), model, setModel)}>{model === item.id && <Check size={15} aria-hidden="true" />}<span><strong>{item.display_name}</strong><code>{item.id}</code></span>{item.tool_compatibility?.state === "passed" && <small className="success">Tool tested</small>}{item.tool_compatibility?.state === "failed" && <small className="danger">Tool test failed</small>}</MotionButton>)}</div>}
              {toolCompatibilityFailed && <p className="model-compatibility-warning" role="alert">This model did not produce a valid structured tool call. Retest it in Settings after a model update, or choose a model marked Tool tested.</p>}
              {ollamaToolTestRequired && !toolCompatibilityFailed && <p className="model-compatibility-warning warning" role="status">Run this installed model&apos;s tool compatibility test in Settings before evaluation.</p>}
              {!models.length && !modelDiscoveryBusy[providerName] && providerName !== "ollama" && provider?.capabilities.custom_model && <p className="muted">{provider.configured ? "The live catalog is not loaded. Use Settings to test the provider, or enter a model identifier manually." : "Add an API key in Settings to load the provider model catalog."}</p>}
              {models.length > 0 && !filteredModels.length && <p className="no-results">No models match “{modelSearch}”.</p>}
              {provider && <div className="capability-list" aria-label="Selected provider capabilities"><span className={provider.capabilities.temperature ? "available" : "unavailable"}>Temperature</span><span className={provider.capabilities.reasoning_effort ? "available" : "unavailable"}>Reasoning effort</span><span className={provider.capabilities.deterministic ? "available" : "unavailable"}>Deterministic mode</span><span className={provider.capabilities.tool_probe ? "available" : "unavailable"}>Tool probe</span></div>}
            </div>
          </fieldset>

          <fieldset><legend><span>02</span> Environment and seeds</legend>
            <section className="evaluation-presets" aria-labelledby="recommended-settings-title">
              <div className="evaluation-presets-head"><div><span className="field-title" id="recommended-settings-title">Recommended settings</span><small>Apply a starting point, then adjust any field before launch.</small></div><span>{providerName === "ollama" ? "Optimized for local inference" : "Matched to the selected provider"}</span></div>
              <div className="evaluation-preset-grid">
                {EVALUATION_PRESETS.map(preset => <MotionButton type="button" className="evaluation-preset" key={preset.id} onClick={() => applyPreset(preset.id)} aria-label={`Apply ${preset.label} preset`}>
                  <span><strong>{preset.label}</strong><small>{preset.episodeSummary}</small></span>
                  <p>{preset.description}</p>
                </MotionButton>)}
              </div>
            </section>
            <div className="field-grid four">
            <label>Split<select value={split} onChange={event => setSplit(event.target.value)}><option>eval</option><option>dev</option><option>train</option></select></label>
            <label>Starting seed<input type="number" min="0" value={seedStart} onChange={event => setSeedStart(event.target.valueAsNumber)} /></label>
            <label>Number of seeds<input type="number" min="1" max="100" value={seedCount} onChange={event => setSeedCount(event.target.valueAsNumber)} /></label>
            <label>Attempts per seed<input type="number" min="1" max="20" value={attempts} onChange={event => setAttempts(event.target.valueAsNumber)} /></label>
          </div><div className="section-helper"><ShieldCheck size={16} aria-hidden="true" /><span>Each episode uses the existing environment and immutable strict verifier. Seeds change public instances, not scoring authority.</span></div></fieldset>

          <fieldset><legend><span>03</span> Limits, concurrency and budgets</legend>
            <div className="form-subsection"><h2>Execution</h2><div className="field-grid four"><label>Concurrency<input type="number" min="1" max="8" value={concurrency} onChange={event => setConcurrency(event.target.valueAsNumber)} /><small>Defaults conservatively to one.</small></label><label>Environment steps<input type="number" min="1" max="256" value={maxSteps} onChange={event => setMaxSteps(event.target.valueAsNumber)} /></label><label>Model calls<input type="number" min="1" max="256" value={maxCalls} onChange={event => setMaxCalls(event.target.valueAsNumber)} /></label><label>Wall clock (s)<input type="number" min="1" value={wallClock} onChange={event => setWallClock(event.target.valueAsNumber)} /></label></div></div>
            <div className="form-subsection"><h2>Provider request</h2><div className="field-grid four">{provider?.capabilities.temperature && <label>Temperature<input type="number" min="0" max="2" step="0.1" value={temperature} onChange={event => setTemperature(event.target.valueAsNumber)} /></label>}<label>Maximum output tokens<input type="number" min="1" value={maxTokens} onChange={event => setMaxTokens(event.target.valueAsNumber)} /></label>{providerName === "ollama" && <label>Context window<input type="number" min="4096" max="262144" step="4096" value={contextWindow} onChange={event => setContextWindow(event.target.valueAsNumber)} /><small>16K is the recommended starting point for an 8 GB GPU.</small></label>}{provider?.capabilities.reasoning_effort && <label>Reasoning effort<select value={reasoning} onChange={event => setReasoning(event.target.value)}><option>low</option><option>medium</option><option>high</option></select></label>}<label>Provider timeout (s)<input type="number" min="1" max="900" value={timeout} onChange={event => setTimeoutValue(event.target.valueAsNumber)} /></label><label>Maximum retries<input type="number" min="0" max="10" value={retries} onChange={event => setRetries(event.target.valueAsNumber)} /></label>{provider?.capabilities.deterministic && <label className="check-field"><input type="checkbox" checked={deterministic} onChange={event => setDeterministic(event.target.checked)} />Deterministic mode</label>}</div></div>
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
          {toolCompatibilityBlocked && <p className="summary-warning" role="status">The selected model needs a current passing structured tool test before evaluation.</p>}
          <MotionButton className="button primary summary-submit" type="submit" disabled={submitting || !provider?.ready || !model || !confirmed || toolCompatibilityBlocked}>{submitting ? <InlineLoading label="Starting evaluation" /> : providerName === "scripted" ? "Run scripted demonstration" : "Start evaluation"}</MotionButton>
        </fieldset>
      </div>
    </form>
  </>;
}
