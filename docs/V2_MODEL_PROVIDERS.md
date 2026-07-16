# V2 Model Providers

## Support matrix

| Provider | Credential | Model selection | Tools | Status |
|---|---|---|---|---|
| Scripted | none | fixed valid/wrong-control | native deterministic calls | verified |
| OpenAI-compatible | session key, local `.env`, `OPENAI_API_KEY`, or `OPENROUTER_API_KEY` | provider `/models` catalog plus manual entry | Responses functions for GPT-5.6; Chat Completions functions otherwise | implemented; isolated live GPT-4.1-mini probe verified |
| Anthropic | session key, local `.env`, or `ANTHROPIC_API_KEY` | authenticated Models API catalog plus manual entry | Messages tool use | implemented; isolated live Fable probe verified |
| Gemini | session key, local `.env`, or `GEMINI_API_KEY` | authenticated `models.list` catalog plus manual entry | `functionDeclarations` | implemented, real credentials not verified |
| Ollama | none | locally installed models from `/api/tags` | OpenAI-compatible tools and reasoning control | discovery, probe, and local episode transport verified; strict success remains model-dependent |

Optional SDKs are not dependencies. Hosted adapters use their public HTTPS JSON
interfaces through the standard library, so missing packages cannot break the
scripted demo. A missing credential marks a provider unconfigured and prevents a
batch from starting with an actionable API error.

The Settings page defaults to a credential for the current API process. An explicit
**Save to local .env** checkbox instead writes the credential to the gitignored
repository `.env` as plaintext on the local device. Resolution is explicit: session
credential, local `.env`, process environment variable, then missing. Session
credentials disappear when the API stops; local `.env` credentials reload at API
startup and can be removed from Settings.

The OpenAI-compatible base URL comes from the session setting, local `.env`, or
process `OPENAI_BASE_URL`;
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
executes the twelve real environment tools. Safe model catalogs and probe verdicts
are cached in `.frontier/provider-state.json`, so they reload with the API. The cache
contains no credential, request header, prompt, model text, or private reasoning.
Results are bound to the provider endpoint and, for Ollama, the discovered model
digest, so changing an endpoint or updating a local model invalidates its earlier result. A passing
format probe is not an evaluation score or a claim of long-horizon capability.
The probe uses a conservative cross-provider JSON schema, a 512-token output
allowance, and a 16,384-token Ollama context cap. The context cap is important on
consumer GPUs: a model's advertised maximum context is not a promise that its model
weights and full KV cache fit together in VRAM. For Ollama only, the default profile
disables model thinking with the native `think: false` option and allows 120 seconds
for a cold local model load;
if the local response is truncated before a tool call, one isolated 2,048-token
retry distinguishes a verbose thinking model from a genuinely invalid tool call.
Episode evaluation exposes low/medium/high reasoning effort only for model profiles
that support Ollama's native `think` option, with `low` as the local smoke-run
default. For non-thinking tool models such as `llama3.1:8b`, the dashboard omits
the control and the API removes a stale or manually supplied reasoning setting
before persisting the run. Evaluations use Ollama's native
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
Full hosted evaluations retain the canonical dotted environment names internally,
but OpenAI-compatible, Anthropic, and Gemini requests receive stable provider-safe
aliases such as `release_status`. Assistant tool calls are translated back to their
canonical names before authorization, execution, diagnostics, or persistence. The
mapping is collision-resistant and applies to tool definitions, forced choices,
replayed assistant calls, tool results, and returned calls; provider naming limits
therefore cannot make a successful isolated probe fail immediately in an episode.
A provider-returned name that was not offered is left unknown and is still rejected
by the normal environment-tool allowlist.

OpenAI GPT-5.6 Sol and Terra use the native Responses API tool protocol with
`max_output_tokens`, `store: false`, serial tool calls, and provider-safe aliases.
Opaque encrypted reasoning items are replayed only in the active in-memory episode
so stateless multi-turn tool calls remain coherent; they are never recorded or shown.
This follows OpenAI's current GPT-5.6 interface while leaving third-party compatible
endpoints on Chat Completions. Other current OpenAI reasoning IDs (`gpt-5*` and the
`o1`/`o3`/`o4` families) receive `max_completion_tokens` instead of deprecated
`max_tokens`; while reasoning is active, the adapter omits `temperature`. Legacy
OpenAI-compatible model IDs retain `max_tokens` for compatibility. Provider HTTP
responses are mapped to bounded error codes without returning raw bodies,
authorization headers, or credentials.

Anthropic evaluations use a separate [Messages-native tool-use
path](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview) rather
than the OpenAI request format. Under Anthropic's [adaptive-thinking
contract](https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking),
Claude Fable 5, Mythos 5/Preview, Opus 4.8/4.7, and Sonnet 5 reject non-default
sampling parameters, so the adapter omits `temperature` for those model families
even when an evaluation preset requests deterministic sampling. Fable's adaptive
thinking is always active: signed thinking blocks are
round-tripped unchanged only inside the active in-memory tool loop and are never
persisted, exported, logged, emitted over SSE, or rendered. Consecutive environment
results are grouped into the Anthropic `tool_result` message shape, and full
evaluations disable parallel tool calls so one environment transition settles before
the next model turn.

A truncated probe is reported separately from a structurally invalid tool call.
Transport timeouts are reported as `provider_timeout`; they do not overwrite a
previously reachable endpoint with a false offline status.
The evaluation builder and API reject a discovered model while its current
digest-bound compatibility result is `failed`; untested custom hosted model IDs
remain available. Discovered Ollama models require a current endpoint- and
digest-bound `passed` result; the safe verdict survives an API restart. The public recovery
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

The public diagnostic contract distinguishes capability scope. A
`telemetry.logs` handle is valid only for `telemetry.trace`. State views
`journal`, `effects`, and `keys` require the state-capable handle returned by a
diagnostic `runtime.run`, plus a selector exposed by its trace. The supported
diagnostic pairs are `diag-s2` with `s2.exit` and `diag-s5` with `s5.exit`;
P1/P2/P3 omit the cutpoint. `source="public"` supports only `progress` and
`recovery`. These descriptions mirror the existing environment behavior and do
not expose hidden workloads or change strict scoring.

Episode inspection can download the exact sanitized run API object as JSON for
sharing. It includes run/model configuration, public verifier results, sanitized
authenticated actions, public workload outcomes, and compact per-turn diagnostics.
It intentionally excludes model prose, private/signed reasoning, credentials,
authorization headers, capability handles, hidden workload details, and verifier
internals.

Environment tool results sent back to the model retain ephemeral trace handles in
memory so the model can follow with `telemetry.trace` or authorized `state.inspect`.
The persisted action timeline, SSE events, exports, logs, and UI receive only the
sanitized form with those handles removed.

Scripted models do not pretend to support temperature or reasoning effort.
Configured token prices are optional; cost metrics remain absent when price data is
absent.

Keys submitted on the Settings page are sent only in a request body to the loopback
API. Session keys remain only in process memory. Explicit local persistence writes
the selected key to the gitignored `.env`; it is plaintext and accessible to anyone
who can read the local files. In both modes keys are never returned, logged, written
to SQLite or provider-state cache, exported, sent over SSE, or stored in browser
local/session storage. OS credential-vault integration is not implemented.

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
| DeepSeek R1 0528 Qwen3 | `deepseek-r1:8b`, `deepseek-r1:8b-0528-qwen3-q4_K_M` | current Ollama template limitation; a future/custom tool-aware digest must pass | weights fit, but the published template is not suitable for native-tool evaluation |
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
pass.

### DeepSeek R1 0528 Qwen3 8B diagnosis

The current official `deepseek-r1:8b` tag is the Qwen3-based 0528 release, but Qwen3
weights alone do not make its chat template tool-aware. The locally installed digest
`6995872bfe4c...` advertises `tools`, while its template omits the `.Tools` definition
injection present in the working `qwen3:8b` template. The default isolated probe
therefore returned reasoning/text and zero native calls. A second bounded
`schema_guided` probe used a 16K context, 1,024-token output budget, and 2,048-token
retry; it still returned zero calls and ended `probe_output_truncated` in reasoning.
It is not safe to pass this digest or to parse its prose as if it were a native call.

Use the locally verified `qwen3:8b` tag for native-tool evaluation. A separately named
custom DeepSeek model with a corrected tool-aware template, or a future upstream
digest, remains eligible only after its own exact-digest probe passes. The application
never pulls, replaces, or rewrites an Ollama model automatically.

The Ollama library currently labels [DeepSeek R1](https://ollama.com/library/deepseek-r1),
[Qwen 3](https://ollama.com/library/qwen3), and [Llama 3.1](https://ollama.com/library/llama3.1)
as tool-capable families. DeepSeek's published 8B
[template](https://ollama.com/library/deepseek-r1%3A8b/blobs/c5ad996bda6e) does not
include the tool-definition block shown by the working Qwen 3
[template](https://ollama.com/library/qwen3%3A8b/blobs/eb4402837c78). Family labels
therefore do not override Frontier's exact-tag, exact-digest compatibility gate.
