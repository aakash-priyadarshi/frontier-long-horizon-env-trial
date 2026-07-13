"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Provider } from "@/lib/types";
import { ErrorState, LoadingState, PageHeader, ProviderBadge } from "@/components/ui";

export default function SettingsPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { api<{ items: Provider[] }>("/api/providers").then(value => setProviders(value.items)).catch(reason => setError(String(reason))); }, []);
  return <>
    <PageHeader eyebrow="Local runtime" title="Providers and settings" description="Credential status and transport capabilities exposed without secret values." />
    {error && <ErrorState message={error} />}
    {!providers.length && !error ? <LoadingState rows={5} /> : <div className="provider-grid">{providers.map(provider => <article className="provider-card" key={provider.provider}><div><ProviderBadge provider={provider.provider} /><span className={provider.configured ? "configured-label" : "unconfigured-label"}>{provider.configured ? "Configured" : "Not configured"}</span></div><h2>{provider.display_name}</h2><p>{provider.provider === "scripted" ? "Credential-free deterministic baseline over the real environment." : provider.provider === "ollama" ? "Local OpenAI-compatible preset; hosted credentials are not required." : "Credentials are read only from the local API process environment."}</p><dl><div><dt>Custom model</dt><dd>{provider.capabilities.custom_model ? "Supported" : "Fixed catalog"}</dd></div><div><dt>Temperature</dt><dd>{provider.capabilities.temperature ? "Supported" : "Hidden"}</dd></div><div><dt>Reasoning effort</dt><dd>{provider.capabilities.reasoning_effort ? "Supported" : "Hidden"}</dd></div><div><dt>Deterministic mode</dt><dd>{provider.capabilities.deterministic ? "Supported" : "Hidden"}</dd></div></dl></article>)}</div>}
    <section className="surface-section security-copy"><div><span className="eyebrow">Secret boundary</span><h2>Keys never reach the browser</h2></div><p>The API returns only provider identity and configured status. Raw keys are never written to SQLite, local storage, logs, SSE events, run records, or exports. Change provider credentials in the API process environment and restart the service.</p><pre>OPENAI_API_KEY=…{"\n"}ANTHROPIC_API_KEY=…{"\n"}GEMINI_API_KEY=…</pre></section>
  </>;
}
