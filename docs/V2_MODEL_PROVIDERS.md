# V2 Model Providers

## Support matrix

| Provider | Credential | Model selection | Tools | Status |
|---|---|---|---|---|
| Scripted | none | fixed valid/wrong-control | native deterministic calls | verified |
| OpenAI-compatible | `OPENAI_API_KEY` or `OPENROUTER_API_KEY` | custom | Chat Completions functions | implemented, real credentials not verified |
| Anthropic | `ANTHROPIC_API_KEY` | custom | Messages tool use | implemented, real credentials not verified |
| Gemini | `GEMINI_API_KEY` | custom | `functionDeclarations` | implemented, real credentials not verified |
| Ollama | none | custom | OpenAI-compatible preset | implemented, local server not verified |

Optional SDKs are not dependencies. Hosted adapters use their public HTTPS JSON
interfaces through the standard library, so missing packages cannot break the
scripted demo. A missing credential marks a provider unconfigured and prevents a
batch from starting with an actionable API error.

The OpenAI-compatible base URL comes from `OPENAI_BASE_URL`; Ollama defaults to
`http://127.0.0.1:11434/v1`. Public endpoints must use HTTPS. HTTP is accepted only
for loopback/local development. Resolved private, link-local, multicast, reserved,
and cloud-metadata ranges are rejected. This policy is intentionally conservative
for a local developer service.

Provider capabilities determine which dashboard controls are visible. Scripted
models do not pretend to support temperature or reasoning effort. Configured token
prices are optional; cost metrics remain absent when price data is absent.

Secrets are read from process environment variables only. They are never returned,
logged, persisted, exported, sent over SSE, or stored in browser local storage.
