# Changelog

All notable V2 evaluation-dashboard changes are documented here. The frozen V1
environment, strict scoring contract, and `trial-submission-v1` tag are unchanged.

## [Unreleased] - 2026-07-14

### Added

- A dedicated Runs page with live episode progress and immutable historical runs,
  linked from the primary sidebar.
- Provider-aware quick-start presets, locally detected Ollama model selection, and
  hosted-provider model suggestions without automatic model installation.
- Read-only tool-use diagnostics that distinguish provider protocol failures,
  environment-tool precondition failures, missing repair phases, and repetitive
  read-only loops without changing strict scores.
- Compact per-turn diagnostics for finish reason, tool names, safe token totals,
  latency, and private-reasoning presence; model prose and reasoning content remain
  excluded.
- Ollama native `/api/chat` support with bounded context configuration and private
  reasoning-state replay for coherent multi-turn tool use.
- An isolated custom Ollama compatibility form for context, output/retry budgets,
  timeout, temperature, thinking mode, and server-owned prompt style.
- A documented support catalog for Qwen 3, current DeepSeek R1 Qwen3, Llama 3.1,
  Llama 3.2, Qwen 2.5, Granite 3.3, Mistral Small, and GPT-OSS profiles. Every exact
  installed digest still requires a passing probe.

### Changed

- Ollama format probes now start with a 16,384-token context instead of inheriting a
  model's potentially much larger default context. A single larger-output retry is
  used only when the first response is explicitly truncated.
- Local evaluation presets start at a 16K context on consumer GPUs while preserving
  user control over model limits, reasoning effort, temperature, retries, and
  episode budgets.
- `workspace.edit` guidance and schemas now make full-file replacement explicit;
  recovery guidance distinguishes the authenticated `S0` snapshot identifier from
  the snapshot integrity digest.
- Ollama evaluations require a passing compatibility result bound to the current
  model digest. Hosted provider probes continue to force only the isolated fake tool.

### Fixed

- DeepSeek R1 Llama-distill startup out-of-memory responses are classified as
  `provider_out_of_memory` instead of the misleading generic tool-use failure.
- The installed legacy `deepseek-r1:8b-llama-distill-q4_K_M` is now identified as a
  template-limited tag after it loads at 16K but answers the fake tool request in
  prose. The UI recommends the current Qwen3-based `deepseek-r1:8b` tag without
  downloading it automatically.
- Private trace handles remain available to the active model turn while sanitized
  records, SSE events, exports, logs, and the UI receive only public-safe results.
- Repeated successful read-only tool cycles receive one progress reminder and then
  terminate with an explicit loop reason instead of consuming the full action budget.

### Security

- The custom compatibility form cannot provide an arbitrary prompt or real
  environment tool. It exposes one harmless `frontier_probe`, executes nothing, and
  stores no model text.
- Provider HTTP error bodies are never returned to the UI. Only allowlisted local
  runtime classifications such as out-of-memory and context-limit are exposed.
- API credentials remain process-memory only, are absent from provider GETs,
  SQLite, SSE, exports, logs, exceptions, browser storage, and committed fixtures.
- Existing loopback-origin, credential CORS, base-URL, redirect, SSRF, and metadata
  protections remain in force.
