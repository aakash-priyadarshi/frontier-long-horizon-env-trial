"use client";

import { BookOpen, ChevronDown, FlaskConical, ShieldCheck } from "lucide-react";
import { FormEvent, useState } from "react";
import { api } from "@/lib/api";
import type { OllamaToolSupportCatalog, ProviderModel, ToolProbeOptions } from "@/lib/types";
import { MotionButton } from "@/components/motion";
import { InlineLoading } from "@/components/ui";

const DEFAULT_OPTIONS: ToolProbeOptions = {
  context_window: 16_384,
  max_output_tokens: 512,
  retry_output_tokens: 2_048,
  timeout_seconds: 120,
  temperature: 0,
  thinking: "off",
  prompt_style: "strict",
};

type Props = {
  models: ProviderModel[];
  busy: boolean;
  onProbe: (model: string, options: ToolProbeOptions) => Promise<void>;
};

export function OllamaToolCompatibility({ models, busy, onProbe }: Props) {
  const [showCustom, setShowCustom] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const [catalog, setCatalog] = useState<OllamaToolSupportCatalog | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [model, setModel] = useState(models[0]?.id ?? "");
  const [options, setOptions] = useState<ToolProbeOptions>(DEFAULT_OPTIONS);
  const selectedName = model || models[0]?.id || "";
  const selectedModel = models.find(item => item.id === selectedName);

  function updateNumber(name: keyof ToolProbeOptions, value: string) {
    setOptions(current => ({
      ...current,
      [name]: name === "retry_output_tokens" && value === "" ? null : Number(value),
    }));
  }

  async function toggleGuide() {
    const next = !showGuide;
    setShowGuide(next);
    if (!next || catalog || catalogBusy) return;
    setCatalogBusy(true);
    setCatalogError("");
    try {
      setCatalog(await api<OllamaToolSupportCatalog>("/api/providers/ollama/tool-support"));
    } catch (reason) {
      setCatalogError(reason instanceof Error ? reason.message : "The support guide could not be loaded.");
    } finally {
      setCatalogBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const selected = selectedName.trim();
    if (!selected) return;
    await onProbe(selected, options);
  }

  return <section className="ollama-compatibility-tools" aria-label="Open-source model tool compatibility">
    <div className="compatibility-actions">
      <MotionButton className="button secondary" type="button" aria-expanded={showCustom} onClick={() => setShowCustom(current => !current)}>
        <FlaskConical size={15} aria-hidden="true" />Test unsupported model
      </MotionButton>
      <MotionButton className="button secondary" type="button" aria-expanded={showGuide} onClick={toggleGuide}>
        <BookOpen size={15} aria-hidden="true" />Supported models &amp; guide<ChevronDown size={14} aria-hidden="true" />
      </MotionButton>
    </div>

    {showCustom && <form className="custom-tool-probe" onSubmit={submit}>
      <div className="custom-probe-heading">
        <div><span className="eyebrow">Advanced compatibility</span><h3>Test a bounded custom profile</h3></div>
        <span><ShieldCheck size={14} aria-hidden="true" />Fake tool only</span>
      </div>
      <p>This sends one isolated <code>frontier_probe</code> schema. It never exposes or executes environment tools, and model text is not stored.</p>
      <label className="wide-field">Installed model
        <input list="ollama-installed-models" value={selectedName} onChange={event => setModel(event.target.value)} placeholder="namespace/model:tag" pattern="[A-Za-z0-9._:/-]+" required />
        <datalist id="ollama-installed-models">{models.map(item => <option value={item.id} key={item.id} />)}</datalist>
      </label>
      {selectedModel?.tool_limitation && <div className="probe-limitation" role="note"><strong>{selectedModel.tool_limitation.name}</strong><p>{selectedModel.tool_limitation.detail}</p><code>{selectedModel.tool_limitation.recommendation}</code></div>}
      <div className="custom-probe-grid">
        <label>Context window <small>tokens</small><input type="number" min="4096" max="262144" step="1024" value={options.context_window} onChange={event => updateNumber("context_window", event.target.value)} /></label>
        <label>Output budget <small>tokens</small><input type="number" min="128" max="8192" step="128" value={options.max_output_tokens} onChange={event => updateNumber("max_output_tokens", event.target.value)} /></label>
        <label>Truncation retry <small>blank disables</small><input type="number" min="128" max="8192" step="128" value={options.retry_output_tokens ?? ""} onChange={event => updateNumber("retry_output_tokens", event.target.value)} /></label>
        <label>Timeout <small>seconds</small><input type="number" min="10" max="300" step="10" value={options.timeout_seconds} onChange={event => updateNumber("timeout_seconds", event.target.value)} /></label>
        <label>Temperature<input type="number" min="0" max="2" step="0.1" value={options.temperature} onChange={event => updateNumber("temperature", event.target.value)} /></label>
        <label>Thinking mode<select value={options.thinking} onChange={event => setOptions(current => ({ ...current, thinking: event.target.value as ToolProbeOptions["thinking"] }))}><option value="off">Off</option><option value="default">Model default</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label>
        <label>Probe instruction<select value={options.prompt_style} onChange={event => setOptions(current => ({ ...current, prompt_style: event.target.value as ToolProbeOptions["prompt_style"] }))}><option value="strict">Strict native call</option><option value="schema_guided">Schema guided</option><option value="minimal">Minimal</option></select></label>
      </div>
      <div className="custom-probe-footer"><small>A pass applies only to this model&apos;s current digest and this profile.</small><MotionButton className="button primary" type="submit" disabled={busy || !selectedName.trim()}>{busy ? <InlineLoading label="Testing custom profile" /> : "Run custom tool test"}</MotionButton></div>
    </form>}

    {showGuide && <section className="tool-support-guide" aria-label="Supported open-source models and compatibility guide">
      <div><span className="eyebrow">Reference</span><h3>Supported native-tool families</h3><p>Catalog support means a safe profile is available. Every installed tag still has to pass against its exact digest.</p></div>
      {catalogBusy && <InlineLoading label="Loading compatibility guide" />}
      {catalogError && <p className="danger" role="alert">{catalogError}</p>}
      {catalog && <>
        <div className="support-model-list">{catalog.items.map(item => <article key={item.id}><div><strong>{item.name}</strong><span className={item.support === "locally_verified" ? "success" : "warning"}>{item.support === "locally_verified" ? "Verified locally" : "Profile available"}</span></div><code>{item.examples.join(" · ")}</code><p>{item.notes}</p><small>{item.hardware}</small></article>)}</div>
        <div className="probe-field-guide"><h4>How to fill the custom form</h4><dl><div><dt>Context window</dt><dd>Start at 16K. Lower it first if Ollama reports out-of-memory; a model&apos;s advertised maximum is not a VRAM recommendation.</dd></div><div><dt>Output and retry</dt><dd>512 is enough for one tool call. Use a larger retry only when the first response is explicitly truncated.</dd></div><div><dt>Thinking</dt><dd>Off is best for a format-only check. Use low/default only when a model rejects disabled thinking.</dd></div><div><dt>Instruction</dt><dd>Strict is the default. Schema guided adds stronger server-owned wording; minimal helps templates that resist system instructions.</dd></div><div><dt>Temperature</dt><dd>Keep 0 for a reproducible compatibility result.</dd></div></dl></div>
        <p className="catalog-meaning">{catalog.meaning}</p>
      </>}
    </section>}
  </section>;
}
