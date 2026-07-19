# Changelog

All notable V2 evaluation-dashboard changes are documented here. The frozen V1
environment, strict scoring contract, and `trial-submission-v1` tag are unchanged.

## [Talon Milestone 2 - Unreleased] - 2026-07-18

### Added

- Canonical private offline transitions derived only after authoritative Milestone
  1 dataset verification, covering public history, behavior action, separate
  operational reward and safety cost, next history, termination and public masks.
- A deterministic GRU discrete-CQL policy with reward/safety critics, target
  network, masked TD targets, CQL regularization, safety filtering, fail-safe
  abstention, per-run RNG isolation and digest-bound atomic checkpoints.
- Frozen CQL evaluation in a weight-only `python -I` worker, disjoint instance
  checks, richer non-compensable safety metrics and separate raw/effective actions.
- Immutable public and privileged replay schemas, allowlisted replay API/SSE/export,
  and a responsive replay dashboard with transport, scrubber, speed, filtering,
  fullscreen, reduced motion and accessible Q/safety tables.
- Versioned offline-RL API and CLI routes, cancellation/timeouts/idempotency, CQL
  training inspector, model/evaluation comparison fields, tests and a check-only
  Milestone 2 verifier that refuses evidence generation from a dirty tree.

### Security

- Private transitions, expert labels, safety costs, hidden truth and privileged
  replay remain outside public SQLite, SSE, dashboard payloads and reviewer exports.
- Q values cannot bypass the public action mask, safety threshold, deterministic
  policy gate, one-time approval verifier or strict safety verifier. No physical
  response or hardware control is added.

## [Talon Milestone 1 - Unreleased] - 2026-07-17

### Added

- A separate simulation-only `drone_decision_ground` package with versioned
  structured observations, thirteen abstract recommendation actions, including a
  dedicated causal command-link verification request, explicit
  authority profiles, deterministic fake time, and a policy gate whose outputs
  always have `external_effect=false`.
- Fifteen deterministic privileged scenario profiles with unique behavioral
  signatures, causal evidence requests, meaningful partition/seed variation,
  multi-track and command-link transitions, and matched early public observations
  for a hidden pair. Public APIs expose only five generic capability groups.
- A separate `drone_decision_verifier` with strict semantic predicates, explicit
  non-compensable safety costs, canonical result digests, and scripted safe,
  over-escalation, under-escalation, skipped-authority, stale-track, and
  public-only negative controls.
- Versioned private expert trajectories and genuinely disjoint train, validation,
  and evaluation domains, with training-only normalization, canonical instance
  digests, checkpoint overlap rejection, authoritative full-dataset digest
  recomputation on every load, and digest-bound private manifests.
- A multi-head GRU behaviour-cloning policy and a causal Decision Transformer with
  action, threat, uncertainty, and missing-evidence supervision, canonical
  return-to-go, process/per-run RNG isolation, deterministic local training, atomic digest-checked checkpoints, and
  separately reported frozen validation/held-out accuracy. The unsupported
  `policy_risk` head and claim were removed.
- A privileged `python -m drone_training` CLI for dataset generation, GRU/Decision
  Transformer training, evaluation, and checkpoint inspection, with authoritative
  spawned-process timeouts.
- Additive loopback-only FastAPI routes under `/api/drone`, lazy Talon initialization,
  separate public SQLite/private artifact storage, payload-bound idempotency,
  killable job workers, immutable terminal records, live/replayable SSE, explicit
  export allowlists, dependency-safe deletion, restart recovery, and opt-in local
  retention.
- A separate `/talon` dashboard area for generic capabilities, policy/approval
  boundaries, datasets, live training, models, live strict evaluation timelines,
  safe export/deletion, comparisons, and accessible chart tables, with no
  physical-response UI or private scenario labels.
- Talon-focused environment, gate, scenario, verifier, dataset, model, checkpoint,
  persistence, API, SSE, and dashboard regression tests.

### Security

- The policy gate remains active during scripted and learned evaluation and cannot
  create an external effect. Response recommendations require sufficient evidence,
  permitted authority, operator availability, and human approval.
- One-time approvals are unpredictable, integrity-protected, expiring, atomically
  consumed, and bound to episode, active track, requested action, policy version,
  authority scope, and state revision.
- Evaluated policies run under `python -I` from a weight-only bundle after repository
  paths, metadata environment variables, filesystem access, and package listing are
  removed. Executable probes confirm privileged imports and paths are unavailable.
- Model-visible observations, policy inputs, public rewards, SSE, SQLite records,
  dashboard payloads, and reviewer exports reject hidden keys and values. Hidden
  truth, expert labels, and full predicates remain in privileged private artifacts.
- Cancellation/timeout terminate worker processes before a single terminal event;
  failed jobs cannot publish partial checkpoints. Checkpoint creation is fsync'd,
  validated, atomically published, digest-bound, and immutable.
- Milestone 1 intentionally excludes raw video, online RL, live sensors, physical
  mechanisms, autonomous response, operational deployment, and explanation LLMs.

## [Unreleased] - 2026-07-16

### Added

- Secure candidate-diff retention for new episodes: only bounded public workspace
  files are compared, sensitive lines and token-shaped values are redacted, diff text
  is size-capped outside SQLite, and the immutable run record binds its SHA-256.
- Candidate diff inspection in the episode page and sanitized episode JSON download,
  with per-run cleanup, bulk storage cleanup on Runs, and confirmed full deletion for
  terminal episodes. Diff-only cleanup preserves the original score record and digest.
- Run inspection now appends each sanitized authenticated action from the live SSE
  stream as soon as its environment tool completes, with replay-safe sequence
  deduplication and automatic scrolling while the model begins its next turn.
- Native one-click Windows and macOS launchers that check and install required
  system/project dependencies, health-check and reuse API/dashboard services, detect
  optional Ollama without installing it or pulling models, and keep runtime logs and
  dependency stamps under the ignored `.frontier/` directory.
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
- Explicit opt-in local `.env` credential persistence alongside the default
  session-only flow, with session/local/process precedence and removal from Settings.
- Restart-safe, credential-free caching for discovered model catalogs and
  endpoint/digest-bound tool compatibility verdicts.
- A one-click episode JSON download containing the complete sanitized run record,
  including tool timeline, per-turn diagnostics, strict result, and run metadata.

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
- Large hosted model catalogs now stay in bounded, searchable lists on Settings and
  New evaluation instead of expanding the page indefinitely.
- Recommended evaluation settings now include an explicit Custom state. Applied
  presets remain visibly selected, and editing any provider, model, seed, limit, or
  request parameter automatically switches the form to Custom without discarding the
  edited values.
- Episode pages provide a direct View diff action for securely retained candidates
  and clearly identify legacy runs whose exact model-written source predates
  candidate-diff retention.

### Fixed

- Public diagnostic schemas now match the environment exactly: diagnostic
  `runtime.run` calls advertise the required `diag-s2`/`s2.exit` and
  `diag-s5`/`s5.exit` pairs, telemetry-log handles are identified as trace-only,
  and `state.inspect` documents which public and runtime-authorized views accept
  which selectors. Tool-use diagnostics give the same actionable corrections.
- Claude Fable 5 and other provider-managed adaptive-thinking models no longer
  receive rejected non-default sampling fields. Anthropic evaluations now preserve
  signed thinking blocks in process memory between tool turns, group parallel tool
  results in the Messages-native format, and request serial tool use.
- Hosted evaluations now translate dotted canonical environment-tool names to
  collision-resistant provider-safe aliases for OpenAI-compatible, Anthropic, and
  Gemini requests, then restore the canonical names before authorization and
  execution. This closes the gap where an isolated `frontier_probe` passed but a
  real Claude or hosted-model episode failed immediately with HTTP 400.
- GPT-5.6 Sol and Terra now use OpenAI's current Responses function-call protocol
  with `store: false`; other current reasoning models retain corrected Chat
  Completions parameters and legacy compatible model IDs retain `max_tokens`.
- Ollama episode requests now apply reasoning effort per model instead of per
  provider. Non-thinking tool models such as `llama3.1:8b` no longer receive an
  unsupported `think` field that made Ollama reject the first turn with HTTP 400.
- The initial episode observation now ends with an explicit native `release.status`
  instruction, preventing capable local models from answering the opening turn in
  prose before the tool loop starts.
- Consecutive scripted `s2.exit` and `s5.exit` diagnostics now use distinct logical
  command identities, preventing the valid trajectory's `s5` probe from being
  rejected as a conflicting payload before its cutpoint executes.
- The current Qwen3-based `deepseek-r1:8b` tag is no longer presented as an expected
  native-tool choice: its published template omits tool-definition injection, and
  both the default and schema-guided exact-digest probes produced no native call.
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
- Session credentials remain process-memory only. Explicit local persistence writes
  plaintext only to the gitignored `.env`; credentials remain absent from provider
  GETs, SQLite, provider-state cache, SSE, exports, logs, exceptions, browser storage,
  and committed fixtures.
- Existing loopback-origin, credential CORS, base-URL, redirect, SSRF, and metadata
  protections remain in force.
