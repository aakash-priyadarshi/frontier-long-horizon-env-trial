# V2 Local API

Default origin: `http://localhost:8000`. OpenAPI is at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | service, overview metrics, source references |
| GET | `/api/providers` | safe configured status and capabilities |
| GET | `/api/providers/{provider}/models` | non-secret model catalog |
| POST | `/api/evaluations` | validate and queue a bounded batch |
| GET | `/api/evaluations` | paginated batch summaries |
| GET | `/api/evaluations/{batch_id}` | batch plus paginated episode summaries |
| POST | `/api/evaluations/{batch_id}/cancel` | cooperative cancellation |
| GET | `/api/evaluations/{batch_id}/events` | ordered replayable SSE |
| GET | `/api/runs/{run_id}` | immutable episode result and timeline |
| GET | `/api/runs/{run_id}/events` | run-scoped SSE |
| GET | `/api/comparisons?batch=…` | compatible comparison metrics/warnings |
| GET | `/api/exports/{batch_id}.json` | sanitized versioned JSON export |

SSE uses persisted monotonically increasing identifiers. Reconnect with the
`Last-Event-ID` header or `after` query parameter. Replay is capped (1,000 events by
default). The service streams changes rather than requiring aggressive polling.

Errors use `{"error":{"code":"…","message":"…"}}`; validation can add a bounded
`details` array. Raw exceptions, tracebacks, credentials, arbitrary paths, and
command execution are never part of the API. CORS allows only the configured local
dashboard origins and only GET/POST/OPTIONS.

The create schema covers provider/model, split, seed range, attempts, concurrency,
model controls, model-call/environment-step limits, token/cost limits, timeout, and
wall-clock budget. Extra fields are rejected.
