# V2 Model Providers

## Support matrix

| Provider | Credential | Model selection | Tools | Status |
|---|---|---|---|---|
| Scripted | none | fixed valid/wrong-control | native deterministic calls | verified |
| OpenAI-compatible | session key, `OPENAI_API_KEY`, or `OPENROUTER_API_KEY` | provider `/models` catalog plus manual entry | Chat Completions functions | implemented, real credentials not verified |
| Anthropic | session key or `ANTHROPIC_API_KEY` | authenticated Models API catalog plus manual entry | Messages tool use | implemented, real credentials not verified |
| Gemini | session key or `GEMINI_API_KEY` | authenticated `models.list` catalog plus manual entry | `functionDeclarations` | implemented, real credentials not verified |
| Ollama | none | locally installed models from `/api/tags` | OpenAI-compatible tools and reasoning control | discovery, probe, and local episode transport verified; strict success remains model-dependent |

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

Provider capabilities determine which dashboard controls are visible. Hosted model
catalogs are read from the configured provider after a credential is available, and
manual model-name entry remains available for custom endpoints and new models. Gemini
discovery keeps only models that advertise `generateContent`. Ollama model discovery
records names, sizes, safe model details, and digests. The dashboard shows an explicit
`ollama pull <model>` command but does not initiate downloads.

The tool-compatibility probe exposes one harmless fake tool and never loads or
executes the twelve real environment tools. Results are bound to the discovered
model digest, so updating a local model invalidates its earlier result. A passing
format probe is not an evaluation score or a claim of long-horizon capability.
The probe uses a conservative cross-provider JSON schema, a 512-token output
allowance, and a 16,384-token Ollama context cap. The context cap is important on
consumer GPUs: a model's advertised maximum context is not a promise that its model
weights and full KV cache fit together in VRAM. For Ollama only, the default profile
disables model thinking with the native `think: false` option and allows 120 seconds
for a cold local model load;
if the local response is truncated before a tool call, one isolated 2,048-token
retry distinguishes a verbose thinking model from a genuinely invalid tool call.
Episode evaluation does not silently disable thinking. Ollama exposes the same
low/medium/high reasoning-effort control as other compatible providers, with `low`
as the dashboard's local smoke-run default. Evaluations use Ollama's native
`/api/chat` endpoint so the recorded `context_window` can be applied per request;
the local presets use 16,384 tokens as a practical starting point for an 8 GB GPU.
Increasing context consumes additional memory. When Ollama returns private reasoning
state alongside an assistant tool call, the adapter replays that state on the next
Ollama turn as required for a coherent multi-turn tool loop. The reasoning content
is never persisted, exported, emitted over SSE, or rendered; only aggregate token
and character counts appear in diagnostics. Hosted providers do not receive the
Ollama reasoning-message extension. Hosted probes require exactly
the isolated fake tool using each provider's native tool-choice control, avoiding
false failures caused by a model choosing prose even though it supports tools.
A truncated probe is reported separately from a structurally invalid tool call.
Transport timeouts are reported as `provider_timeout`; they do not overwrite a
previously reachable endpoint with a false offline status.
The evaluation builder and API reject a discovered model while its current
digest-bound compatibility result is `failed`; untested custom hosted model IDs
remain available. Discovered Ollama models require a current digest-bound `passed`
result because runtime probe state resets with the API process. The public recovery
schema identifies `S0` as the default snapshot ID and distinguishes it from the
snapshot integrity-root digest.

Episode inspection attaches a read-only `tool_use_debug` report derived from the
authenticated timeline. It classifies precondition failures (for example
`intake must be paused`, `resume requires a deployed candidate`, and
`no candidate changes to deploy`), marks missing repair phases, and separates
protocol failures (`malformed_model_response`, empty `tool_calls`) from workflow
misuse where local tool adapters are functioning. New episodes also store
compact `model_turn_debug` rows (`finish_reason`, tool names, token split) without
embedding model prose or private reasoning. Workflow phase coverage requires an
actual candidate edit, all P1/P2/P3 passes, and a successful resume; reads and
status calls do not falsely satisfy those phases. If a model repeats the same
successful read-only cycle, the runner issues one generic progress reminder and
then stops a continued loop as `model_repetitive_tool_loop`, rather than consuming
the full action budget. This guard never edits files, invokes tools on the model's
behalf, or changes verifier scoring.

Environment tool results sent back to the model retain ephemeral trace handles in
memory so the model can follow with `telemetry.trace` or authorized `state.inspect`.
The persisted action timeline, SSE events, exports, logs, and UI receive only the
sanitized form with those handles removed.

Scripted models do not pretend to support temperature or reasoning effort.
Configured token prices are optional; cost metrics remain absent when price data is
absent.

Keys submitted on the Settings page are sent only in a request body to the loopback
API, retained only in process memory, and never returned, logged, persisted,
exported, sent over SSE, or stored in browser local/session storage. OS credential
vault persistence is deferred until the memory-only workflow has completed
platform-specific validation.

## Ollama compatibility profiles

The Settings page has two explicit advanced controls:

- **Test unsupported model** opens a bounded form for context window, output and
  retry budgets, timeout, temperature, thinking mode, and a server-owned instruction
  style. It does not accept arbitrary prompts. The request still contains only the
  fake `frontier_probe`, never executes that tool, and does not retain model text.
- **Supported models & guide** lists model families for which the platform has a
  native-tool probe profile and explains how to choose each field. A catalog entry
  is not a blanket pass: every installed tag must pass for its current digest.

| Ollama family | Example tags | Frontier status | 8 GB GPU note |
|---|---|---|---|
| Qwen 3 | `qwen3:4b`, `qwen3:8b` | Qwen3 8B locally probe-verified; family profile available | practical at a bounded context |
| DeepSeek R1 0528 Qwen3 | `deepseek-r1:8b`, `deepseek-r1:8b-0528-qwen3-q4_K_M` | profile available; exact digest probe required | Q4 8B is the intended local choice |
| Llama 3.1 | `llama3.1:8b` | profile available; exact digest probe required | quantized 8B with 16K or lower initial context |
| Llama 3.2 | `llama3.2:1b`, `llama3.2:3b` | profile available; exact digest probe required | fits easily; smaller models may struggle with the long-horizon task |
| Qwen 2.5 | `qwen2.5:3b`, `qwen2.5:7b` | profile available; exact digest probe required | practical quantized choices |
| Granite 3.3 | `granite3.3:2b`, `granite3.3:8b` | profile available; exact digest probe required | both quantized sizes fit; 8B is stronger |
| Mistral Small 3/3.1 | `mistral-small:24b`, `mistral-small3.1` | profile available; exact digest probe required | roughly 14–15 GB, so CPU offload is likely on 8 GB VRAM |
| GPT-OSS | `gpt-oss:20b` | low-thinking profile available; exact digest probe required | roughly 14 GB, so not recommended for this GPU |

These profiles follow Ollama's native [tool-calling API](https://docs.ollama.com/capabilities/tool-calling)
and its current [tools-filtered model library](https://ollama.com/library?category=tools).
The catalog deliberately separates "profile available" from "verified locally."

### DeepSeek R1 Llama-distill 8B diagnosis

The installed `deepseek-r1:8b-llama-distill-q4_K_M` digest was tested in two
stages. Without an explicit context cap, Ollama attempted to allocate a roughly
3.5 GiB CUDA KV buffer in addition to the 4.9 GB model and returned an out-of-memory
HTTP 500 on the 8 GB GPU. The adapter now maps that response to the safe
`provider_out_of_memory` code without returning Ollama's raw error body.

With `num_ctx=16384`, the same model loaded successfully but returned prose and no
native `tool_calls` item. Its locally installed template contains tool-call output
markers but does not inject the supplied tool definitions. The compatibility result
is therefore correctly `invalid_tool_call`, not a transport error and not a false
pass. The current official `deepseek-r1:8b` tag is the Qwen3-based 0528 release;
install it explicitly with `ollama pull deepseek-r1:8b`, rediscover models, and probe
its exact digest. The application never pulls or replaces a model automatically.

The Ollama library currently labels [DeepSeek R1](https://ollama.com/library/deepseek-r1),
[Qwen 3](https://ollama.com/library/qwen3), and [Llama 3.1](https://ollama.com/library/llama3.1)
as tool-capable families. Those family labels do not override Frontier's exact-tag,
exact-digest compatibility gate.
