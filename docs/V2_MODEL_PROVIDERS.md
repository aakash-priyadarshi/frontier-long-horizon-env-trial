# V2 Model Providers

## Support matrix

| Provider | Credential | Model selection | Tools | Status |
|---|---|---|---|---|
| Scripted | none | fixed valid/wrong-control | native deterministic calls | verified |
| OpenAI-compatible | session key, `OPENAI_API_KEY`, or `OPENROUTER_API_KEY` | discovered when supported, otherwise custom | Chat Completions functions | implemented, real credentials not verified |
| Anthropic | session key or `ANTHROPIC_API_KEY` | custom | Messages tool use | implemented, real credentials not verified |
| Gemini | session key or `GEMINI_API_KEY` | custom | `functionDeclarations` | implemented, real credentials not verified |
| Ollama | none | locally installed models from `/api/tags` | OpenAI-compatible preset | discovery and offline state verified; a local model run is not verified |

Optional SDKs are not dependencies. Hosted adapters use their public HTTPS JSON
interfaces through the standard library, so missing packages cannot break the
scripted demo. A missing credential marks a provider unconfigured and prevents a
batch from starting with an actionable API error.

The Settings page can submit a credential for the current API process without
editing `.env` or restarting. Resolution is explicit: session credential, then
environment variable, then missing. Session credentials disappear when the API
stops.

The OpenAI-compatible base URL comes from the session setting or `OPENAI_BASE_URL`;
Ollama similarly falls back to `OLLAMA_BASE_URL`, then
`http://127.0.0.1:11434/v1`. Public endpoints must use HTTPS. HTTP is accepted only
for loopback development. Resolved private, link-local, multicast, reserved, and
cloud-metadata ranges are rejected. Ollama URLs are loopback-only and discovery
requests do not follow redirects.

Provider capabilities determine which dashboard controls are visible. Discovery is
capability-based; unsupported providers retain manual model-name entry. Ollama model
discovery records names, sizes, safe model details, and digests. The dashboard shows
an explicit `ollama pull <model>` command but does not initiate downloads.

The tool-compatibility probe exposes one harmless fake tool and never loads or
executes the twelve real environment tools. Results are bound to the discovered
model digest, so updating a local model invalidates its earlier result. A passing
format probe is not an evaluation score or a claim of long-horizon capability.

Scripted models do not pretend to support temperature or reasoning effort.
Configured token prices are optional; cost metrics remain absent when price data is
absent.

Keys submitted on the Settings page are sent only in a request body to the loopback
API, retained only in process memory, and never returned, logged, persisted,
exported, sent over SSE, or stored in browser local/session storage. OS credential
vault persistence is deferred until the memory-only workflow has completed
platform-specific validation.
