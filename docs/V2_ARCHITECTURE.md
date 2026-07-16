# V2 Architecture

## Authority flow

```text
Next.js dashboard
  -> local FastAPI evaluation API
    -> shared EvaluationOrchestrator
      -> provider-neutral ModelAdapter
        -> exact public 12-tool definitions
          -> training_ground EnvironmentProtocol.step
      -> EnvironmentProtocol.grade
        -> existing strict verifier (sole scoring authority)
      -> immutable SQLite result + canonical SHA-256 digest
      -> bounded sanitized candidate diff + digest manifest
    -> sanitized API, SSE, comparison, and export views
```

The dashboard does not import verifier code and never calculates reward. The runner
does not import verifier internals: it loads the public environment, sends only the
public manifest/observations and tool history to the model, calls `step`, and copies
the result returned by `grade` into the terminal record.

## Package boundaries

- `src/model_runners`: provider transport, tool conversion, errors, capabilities,
  usage, and configured-price accounting.
- `src/evaluation_service`: orchestration, execution budgets, public sanitization,
  SQLite persistence, SSE, comparison metrics, and FastAPI.
- `src/model_eval`: CLI over the same orchestrator and store.
- `apps/dashboard`: browser-only presentation and run control.
- Existing `training_ground`, `agent_surface`, and `strict_verifier`: unchanged V1
  environment and authority path.

One provider response may contain multiple structured tool calls. The runner executes
them sequentially in provider order, caps a single response at four calls, appends an
observation after each call, and stops immediately on termination, truncation,
cancellation, or a hard budget. Retryable transport failures use bounded exponential
backoff; non-retryable/malformed responses fail the run.

SQLite lives at `.frontier/evaluations.sqlite3`; run-local data is gitignored. A
schema metadata row provides explicit migration versioning. Queued or running
records found after API restart become terminal `interrupted` records; uncertain
provider requests are never automatically resumed.

Terminal run payloads are immutable. `record_digest` is SHA-256 over canonical JSON
excluding only audit/export metadata. A terminal record may be explicitly deleted,
but never edited. Comparison statistics derive from stored authoritative reward;
they do not create reward.

New terminal episodes compare only the five bounded public workspace files and write
a sanitized unified diff to `.frontier/runs/<run_id>/candidate-diff.json`. The
artifact is capped at 480 KiB of diff text; secret-shaped assignments, known token
formats, private paths, internal identifiers, and hidden workload identifiers are
redacted before the file is written. SQLite stores only the changed paths, size,
redaction/truncation metadata, and artifact digest. That manifest is part of the
immutable run digest. Deleting only the artifact therefore reclaims space without
rewriting the score record or its proof that the artifact once existed.
