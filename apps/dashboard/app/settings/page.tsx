"use client";

import { CheckCircle2, Cpu, Database, KeyRound, RadioTower, Server, ShieldCheck, Wrench } from "lucide-react";
import { motion } from "motion/react";
import { FormEvent, type ReactNode, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Provider, ProviderModel } from "@/lib/types";
import { AnimatedStatus, MotionButton, SharedSelectionIndicator } from "@/components/motion";
import { ErrorState, InlineLoading, LoadingState, PageHeader, ProviderBadge } from "@/components/ui";

type ProviderResult = { provider: Provider };

const credentialLabels: Record<string, string> = {
  not_required: "Not required",
  missing: "Missing",
  environment: "Available from environment",
  session: "Available for this session",
  os_vault: "Stored in OS vault",
};

const stateLabels: Record<string, string> = {
  not_required: "Not required",
  not_tested: "Not tested",
  reachable: "Reachable",
  unreachable: "Unreachable",
  valid: "Valid",
  invalid: "Invalid",
  invalid_configuration: "Invalid configuration",
  discovered: "Discovered",
  unsupported: "Discovery unsupported",
  failed: "Failed",
  passed: "Passed",
};

function stateTone(state: string): string {
  if (["reachable", "valid", "discovered", "passed", "not_required", "available"].includes(state)) return "success";
  if (["unreachable", "invalid", "invalid_configuration", "failed"].includes(state)) return "danger";
  if (state === "unsupported") return "neutral";
  return "warning";
}

function StatusRow({ label, state, children, busy = false, icon }: { label: string; state: string; children: ReactNode; busy?: boolean; icon: ReactNode }) {
  return <div><dt>{icon}<span>{label}</span></dt><dd className={stateTone(state)}>{busy ? <span className="status-skeleton" aria-label={`${label} check in progress`} /> : <AnimatedStatus state={state}>{children}</AnimatedStatus>}</dd></div>;
}

function formatBytes(value?: number): string {
  if (value === undefined) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size.toFixed(unit > 2 ? 1 : 0)} ${units[unit]}`;
}

function modelDetail(model: ProviderModel): string {
  return [model.details?.parameter_size, model.details?.quantization_level, formatBytes(model.size)].filter(Boolean).join(" · ");
}

export default function SettingsPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [baseUrls, setBaseUrls] = useState<Record<string, string>>({});
  const [manualModels, setManualModels] = useState<Record<string, string>>({});
  const [pullModels, setPullModels] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<Record<string, string>>({});
  const [messages, setMessages] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [selected, setSelected] = useState("scripted");

  const replaceProvider = useCallback((provider: Provider) => {
    setProviders(current => current.map(item => item.provider === provider.provider ? provider : item));
    setBaseUrls(current => ({ ...current, [provider.provider]: provider.base_url ?? "" }));
  }, []);

  useEffect(() => {
    let active = true;
    api<{ items: Provider[] }>("/api/providers")
      .then(async value => {
        if (!active) return;
        setProviders(value.items);
        setBaseUrls(Object.fromEntries(value.items.map(item => [item.provider, item.base_url ?? ""])));
        const ollama = value.items.find(item => item.provider === "ollama");
        if (ollama?.capabilities.connection_test && ollama.endpoint.state === "not_tested") {
          try {
            const tested = await api<ProviderResult>("/api/providers/ollama/connection-test", { method: "POST" });
            if (active) replaceProvider(tested.provider);
          } catch {
            // The provider card retains a safe not-tested state when the local probe cannot run.
          }
        }
      })
      .catch(reason => active && setError(reason instanceof Error ? reason.message : String(reason)));
    return () => { active = false; };
  }, [replaceProvider]);

  async function configure(event: FormEvent, provider: Provider) {
    event.preventDefault();
    const credential = credentials[provider.provider] ?? "";
    if (provider.credential.required && provider.credential.state === "missing" && !credential) {
      setMessages(current => ({ ...current, [provider.provider]: "Enter an API key for this session." }));
      return;
    }
    const body: Record<string, string> = {};
    if (credential) body.credential = credential;
    if (provider.capabilities.custom_base_url) body.base_url = baseUrls[provider.provider] ?? "";
    setBusy(current => ({ ...current, [provider.provider]: "saving" }));
    setMessages(current => ({ ...current, [provider.provider]: "" }));
    try {
      const result = await api<ProviderResult>(`/api/providers/${provider.provider}/credentials`, {
        method: "POST", body: JSON.stringify(body),
      });
      replaceProvider(result.provider);
      setCredentials(current => ({ ...current, [provider.provider]: "" }));
      setMessages(current => ({ ...current, [provider.provider]: "Session settings updated. Test the connection before evaluation." }));
    } catch (reason) {
      setMessages(current => ({ ...current, [provider.provider]: reason instanceof Error ? reason.message : "Settings could not be updated." }));
    } finally {
      setBusy(current => ({ ...current, [provider.provider]: "" }));
    }
  }

  async function testConnection(provider: Provider) {
    setBusy(current => ({ ...current, [provider.provider]: "testing" }));
    setMessages(current => ({ ...current, [provider.provider]: "" }));
    try {
      const result = await api<ProviderResult>(`/api/providers/${provider.provider}/connection-test`, { method: "POST" });
      replaceProvider(result.provider);
      const state = result.provider.endpoint.state;
      setMessages(current => ({ ...current, [provider.provider]: state === "reachable" ? "Connection test completed." : "The provider endpoint is unavailable." }));
    } catch (reason) {
      setMessages(current => ({ ...current, [provider.provider]: reason instanceof Error ? reason.message : "Connection test failed." }));
    } finally {
      setBusy(current => ({ ...current, [provider.provider]: "" }));
    }
  }

  async function clearCredential(provider: Provider) {
    setBusy(current => ({ ...current, [provider.provider]: "clearing" }));
    try {
      const result = await api<ProviderResult>(`/api/providers/${provider.provider}/credentials`, { method: "DELETE" });
      replaceProvider(result.provider);
      setCredentials(current => ({ ...current, [provider.provider]: "" }));
      setMessages(current => ({ ...current, [provider.provider]: result.provider.credential.source === "environment" ? "Session key cleared; the environment credential is active again." : "Session credential cleared." }));
    } catch (reason) {
      setMessages(current => ({ ...current, [provider.provider]: reason instanceof Error ? reason.message : "Credential could not be cleared." }));
    } finally {
      setBusy(current => ({ ...current, [provider.provider]: "" }));
    }
  }

  async function probeToolCalling(provider: Provider, model: string) {
    if (!model) return;
    setBusy(current => ({ ...current, [provider.provider]: `probe:${model}` }));
    try {
      const result = await api<ProviderResult>(`/api/providers/${provider.provider}/tool-probe`, {
        method: "POST", body: JSON.stringify({ model }),
      });
      replaceProvider(result.provider);
      setMessages(current => ({ ...current, [provider.provider]: `Tool compatibility test completed for ${model}.` }));
    } catch (reason) {
      setMessages(current => ({ ...current, [provider.provider]: reason instanceof Error ? reason.message : "Tool compatibility test failed." }));
    } finally {
      setBusy(current => ({ ...current, [provider.provider]: "" }));
    }
  }

  async function copyPullCommand(provider: string) {
    const model = pullModels[provider]?.trim();
    if (!model) return;
    await navigator.clipboard.writeText(`ollama pull ${model}`);
    setMessages(current => ({ ...current, [provider]: "Pull command copied." }));
  }

  const readyCount = providers.filter(provider => provider.ready).length;

  return <>
    <PageHeader eyebrow="Local runtime" title="Providers and settings" description="Configure memory-only credentials, verify endpoints, discover models, and test isolated tool-call compatibility." />
    {error && <ErrorState message={error} />}
    {providers.length > 0 && <section className="provider-overview" aria-label="Provider summary"><div><span className="status-dot ok" /><strong>{readyCount} of {providers.length} providers ready</strong></div><span><ShieldCheck size={15} aria-hidden="true" />Credentials remain in the API process only</span></section>}
    {!providers.length && !error ? <LoadingState rows={5} /> : <div className="provider-grid settings-provider-grid">{providers.map(provider => {
      const sourceLabel = credentialLabels[provider.credential.source] ?? provider.credential.source;
      const working = Boolean(busy[provider.provider]);
      const manualModel = manualModels[provider.provider] ?? "";
      const selectedCard = selected === provider.provider;
      const checking = busy[provider.provider] === "testing";
      return <motion.article layout className={`provider-card provider-settings-card${selectedCard ? " selected" : ""}${working ? " busy" : ""}`} key={provider.provider} tabIndex={0} onFocusCapture={() => setSelected(provider.provider)} onClick={() => setSelected(provider.provider)} aria-label={`${provider.display_name} provider settings`}>
        {selectedCard && <SharedSelectionIndicator layoutId="settings-provider-selection" />}
        <div className="provider-card-head"><ProviderBadge provider={provider.provider} /><span className={provider.ready ? "configured-label" : "unconfigured-label"}>{provider.ready ? <><CheckCircle2 size={14} aria-hidden="true" />Ready</> : "Needs attention"}</span></div>
        <div className="provider-title"><div><h2>{provider.display_name}</h2><small>{provider.provider === "ollama" ? "Local open-source runtime" : provider.provider === "scripted" ? "Credential-free baseline" : "Hosted provider"}</small></div>{provider.provider === "ollama" && <Cpu size={22} aria-hidden="true" />}</div>
        <p>{provider.provider === "scripted" ? "Credential-free deterministic baseline over the real environment." : provider.provider === "ollama" ? "No per-token API fee. The local Ollama daemon and an installed model are required." : "Use an API key for this server session; keys are never returned or persisted by the platform."}</p>
        {provider.provider === "ollama" && <div className={`ollama-runtime-summary ${provider.endpoint.state === "reachable" ? "online" : "offline"}`}><RadioTower size={17} aria-hidden="true" /><div><strong>Daemon {provider.endpoint.state === "reachable" ? "online" : "offline"}</strong><span>{provider.model_discovery.count} installed model{provider.model_discovery.count === 1 ? "" : "s"} · no credentials required</span></div></div>}
        <dl className="provider-state-list">
          <StatusRow label="Credentials" state={provider.credential.state} icon={<KeyRound size={14} aria-hidden="true" />}>{sourceLabel}</StatusRow>
          <StatusRow label="Endpoint" state={provider.endpoint.state} busy={checking} icon={<Server size={14} aria-hidden="true" />}>{stateLabels[provider.endpoint.state] ?? provider.endpoint.state}</StatusRow>
          <StatusRow label="Authentication" state={provider.authentication.state} busy={checking} icon={<ShieldCheck size={14} aria-hidden="true" />}>{stateLabels[provider.authentication.state] ?? provider.authentication.state}</StatusRow>
          <StatusRow label="Model discovery" state={provider.model_discovery.state} busy={checking} icon={<Database size={14} aria-hidden="true" />}>{stateLabels[provider.model_discovery.state] ?? provider.model_discovery.state}{provider.model_discovery.state === "discovered" ? ` (${provider.model_discovery.count})` : ""}</StatusRow>
          <StatusRow label="Tool compatibility" state={provider.tool_calling.state} icon={<Wrench size={14} aria-hidden="true" />}>{stateLabels[provider.tool_calling.state] ?? provider.tool_calling.state}</StatusRow>
        </dl>

        {provider.provider !== "scripted" && <form className="provider-config-form" onSubmit={event => configure(event, provider)}>
          {provider.credential.required && <label>API key <small>memory-only</small><input aria-label={`${provider.display_name} API key`} type="password" autoComplete="new-password" value={credentials[provider.provider] ?? ""} onChange={event => setCredentials(current => ({ ...current, [provider.provider]: event.target.value }))} placeholder={provider.credential.state === "missing" ? "Required" : "Replace active credential"} /></label>}
          {provider.capabilities.custom_base_url && <label>Base URL<input aria-label={`${provider.display_name} base URL`} type="url" value={baseUrls[provider.provider] ?? provider.base_url ?? ""} onChange={event => setBaseUrls(current => ({ ...current, [provider.provider]: event.target.value }))} /></label>}
          <div className="provider-actions">
            <MotionButton className="button primary" disabled={working} type="submit">{busy[provider.provider] === "saving" ? <InlineLoading label="Saving session" /> : "Use for session"}</MotionButton>
            {provider.capabilities.connection_test && <MotionButton className="button secondary" disabled={working || !provider.configured} type="button" onClick={() => testConnection(provider)}>{busy[provider.provider] === "testing" ? <InlineLoading label="Testing connection" /> : "Test connection"}</MotionButton>}
            {provider.credential.source === "session" && <MotionButton className="button danger-button" disabled={working} type="button" onClick={() => clearCredential(provider)}>{busy[provider.provider] === "clearing" ? <InlineLoading label="Clearing key" /> : "Clear session key"}</MotionButton>}
          </div>
          {provider.credential.source === "environment" && <small className="provider-help">Environment credentials must be removed from the API process environment; this page cannot clear the parent shell.</small>}
        </form>}

        {provider.models.length > 0 && provider.provider !== "scripted" && <section className="discovered-models" aria-label={`${provider.display_name} models`}>
          <h3>Available models</h3>
          <ul>{provider.models.map(model => <li key={model.id}><div><strong>{model.display_name}</strong>{modelDetail(model) && <small>{modelDetail(model)}</small>}<span className={stateTone(model.tool_compatibility?.state ?? "not_tested")}>Tool compatibility: {stateLabels[model.tool_compatibility?.state ?? "not_tested"]}</span></div>{provider.capabilities.tool_probe && <MotionButton className="button secondary" disabled={working} onClick={() => probeToolCalling(provider, model.id)}>{busy[provider.provider] === `probe:${model.id}` ? <InlineLoading label="Testing tools" /> : "Test tools"}</MotionButton>}</li>)}</ul>
        </section>}

        {provider.capabilities.tool_probe && provider.models.length === 0 && <div className="manual-probe"><label>Model name for tool test<input value={manualModel} onChange={event => setManualModels(current => ({ ...current, [provider.provider]: event.target.value }))} placeholder="provider/model-name" pattern="[A-Za-z0-9._:/-]+" /></label><MotionButton className="button secondary" disabled={working || !manualModel || !provider.configured} onClick={() => probeToolCalling(provider, manualModel)}>Test tool calling</MotionButton></div>}

        {provider.provider === "ollama" && <section className="ollama-pull"><h3>Install another model</h3><p>Downloads stay in the Ollama CLI so disk use, progress, and cancellation remain explicit.</p><label>Model name<input value={pullModels[provider.provider] ?? ""} onChange={event => setPullModels(current => ({ ...current, [provider.provider]: event.target.value }))} placeholder="qwen3-coder:latest" /></label><div><code>ollama pull {pullModels[provider.provider]?.trim() || "<model>"}</code><MotionButton className="button secondary" disabled={!pullModels[provider.provider]?.trim()} onClick={() => copyPullCommand(provider.provider)}>Copy command</MotionButton></div></section>}
        {messages[provider.provider] && <p className="provider-message" role="status">{messages[provider.provider]}</p>}
      </motion.article>;
    })}</div>}
    <section className="surface-section security-copy"><div><span className="eyebrow">Secret boundary</span><h2>Keys stay server-side after submission</h2></div><p>Keys are entered only to send them to the loopback API. They remain in process memory for this server session and are never returned, written to SQLite, stored in browser storage, included in events, or exported with evaluations.</p><div><strong>Precedence</strong><pre>Session credential{"\n"}Environment variable{"\n"}Missing</pre><small>OS credential-vault persistence is intentionally deferred until the memory-only workflow is fully validated.</small></div></section>
  </>;
}
