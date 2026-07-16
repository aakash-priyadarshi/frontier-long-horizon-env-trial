# V2 Security Boundary

## Model-visible surface

Each episode receives only the versioned incident system prompt, public manifest,
sanitized observations, previous public tool interactions, and the exact twelve
public tool schemas. Calls execute only through `EnvironmentProtocol.step`.

The model runner has no shell, unrestricted filesystem, database, GitHub/MCP,
arbitrary URL, hidden registry, fixture, authority, or verifier import. Unknown tool
names are rejected before `step`. Workspace paths remain bounded by the existing
agent surface. Direct hidden workload names remain rejected by that surface.

## Browser and record surface

Before persistence and delivery, the service removes credentials, authorization
fields, auth tags, capability handles, private verifier/database paths, and hidden
workload identifiers. Workspace edit content becomes a byte count and SHA-256
summary. Only P1/P2/P3 public workload outcomes are included. Hidden definitions and
member identity never appear in SQLite, SSE, API payloads, charts, or exports.

Candidate source retention is a separate bounded path. Only unified diffs of the five
public model-editable files are eligible. Diff lines are scanned before persistence;
secret assignments and known credential/token forms, private paths, privileged
identifier names, and hidden workload identifiers are redacted. Diff text is never
stored in SQLite or SSE. The sanitized artifact lives under the gitignored run
directory, is capped at 480 KiB of diff text, and is accepted by the API only when
its SHA-256 matches the immutable manifest in the run record. The episode JSON
download includes this already validated sanitized artifact when it is available.

The strict verifier's `score` and `verdict` are copied into the terminal payload.
The API exposes no score-update endpoint and the schema has no mutable score column.
Terminal payload mutation is rejected. A canonical digest binds result, model
configuration, prompt version, environment commit, timeline, and outcome.

## Secrets and network

Keys exist only in the local API process environment, the API's process-local
session credential store, or—after explicit user opt-in—the gitignored local `.env`.
The `.env` option is plaintext local-file persistence, not an OS credential vault.
The browser holds a newly entered key only long enough to submit it; the server never
returns it. Credential-changing requests require a
loopback Host and the configured dashboard Origin, use request bodies rather than
URLs, and return `Cache-Control: no-store`. Provider status separates credential
source, endpoint reachability, authentication, model discovery, and tool-call
compatibility.

Safe discovered-model metadata and tool-probe verdicts are stored separately in
`.frontier/provider-state.json`. That cache contains no keys, headers, prompts,
provider response text, or reasoning. Probe results are bound to the provider
endpoint and Ollama digest before reuse.

Stateless GPT-5.6 Responses calls use `store: false`. Opaque encrypted reasoning
continuations are replayed only inside the active process conversation and are
excluded from SQLite, provider cache, logs, SSE, exports, and browser responses.
Anthropic signed thinking blocks use the same memory-only lifecycle for native
Messages tool-loop continuity; episode JSON downloads serialize only the already
sanitized browser record and never include those blocks.

For local development, the configured `localhost` dashboard origin and the matching
`127.0.0.1` alias at the same port are the complete CORS allowlist. Credential
requests do not use wildcard CORS, and other Origins are rejected in the route even
when a non-browser client bypasses preflight.

Candidate-diff cleanup and terminal-episode deletion use the same loopback Host and
exact Origin checks. Diff-only cleanup leaves the score record and digest manifest
unchanged. Full episode deletion removes the run row, run-scoped and corresponding
batch events, result artifact, and candidate diff; it is unavailable while a run is
queued or active. If the deleted run was the last child, its empty batch is removed.

OpenAI-compatible URL validation rejects non-HTTP schemes, URL credentials, public
HTTP, and private/link-local/metadata targets while permitting explicit loopback
development. Ollama base URLs are loopback-only. Discovery requests reject redirects
and do not include response bodies in public errors. This is defense in depth, not a
production egress sandbox.

## Limitations

The service is a local developer tool without accounts or multi-tenant isolation.
Process owners can inspect their own environment and files. Hosted transports are
implemented but not claimed verified without credentials. APEX upstream execution
and Docker execution remain **NOT VERIFIED**. The external APEX-SWE checkout remains
read-only and unmodified.

OS credential-vault integration and UI-controlled Ollama downloads are not part of
this iteration. A model passing the isolated fake-tool format probe does not establish
that it can complete the real long-horizon environment.
