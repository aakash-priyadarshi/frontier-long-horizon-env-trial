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

The strict verifier's `score` and `verdict` are copied into the terminal payload.
The API exposes no score-update endpoint and the schema has no mutable score column.
Terminal payload mutation is rejected. A canonical digest binds result, model
configuration, prompt version, environment commit, timeline, and outcome.

## Secrets and network

Keys exist only in the local API process environment or the API's process-local
session credential store. The browser holds a newly entered key only long enough to
submit it; the server never returns it. Credential-changing requests require a
loopback Host and the configured dashboard Origin, use request bodies rather than
URLs, and return `Cache-Control: no-store`. Provider status separates credential
source, endpoint reachability, authentication, model discovery, and tool-call
compatibility.

For local development, the configured `localhost` dashboard origin and the matching
`127.0.0.1` alias at the same port are the complete CORS allowlist. Credential
requests do not use wildcard CORS, and other Origins are rejected in the route even
when a non-browser client bypasses preflight.

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

OS credential-vault persistence and UI-controlled Ollama downloads are not part of
this iteration. A model passing the isolated fake-tool format probe does not establish
that it can complete the real long-horizon environment.
