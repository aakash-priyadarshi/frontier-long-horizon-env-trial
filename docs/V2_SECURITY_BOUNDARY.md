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

Keys exist only in the local API process environment. Provider status is a boolean.
OpenAI-compatible URL validation rejects public HTTP and private/link-local/metadata
targets while permitting explicit loopback development. This is defense in depth,
not a production egress sandbox.

## Limitations

The service is a local developer tool without accounts or multi-tenant isolation.
Process owners can inspect their own environment and files. Hosted transports are
implemented but not claimed verified without credentials. APEX upstream execution
and Docker execution remain **NOT VERIFIED**. The external APEX-SWE checkout remains
read-only and unmodified.
