# Talon local API and privileged CLI

Talon is additively mounted at `/api/drone`. It has a separate lazy service,
`TalonStore`, SQLite database, artifact directory, record schemas, and event scopes.
Original Frontier routes remain available if Talon initialization fails.

## Local configuration

```dotenv
TALON_DATA_DIR=.frontier/talon
TALON_DATABASE_PATH=.frontier/talon/talon.sqlite3
TALON_RETENTION_DAYS=0
FRONTIER_DASHBOARD_ORIGIN=http://localhost:3000
```

Mutation routes require a loopback request host and an approved local dashboard
`Origin`. `http://localhost:3000` and its intentional `127.0.0.1` alias are allowed;
credentialed wildcard CORS is not used. Record and export responses are no-store.

## Public routes

Discovery and safety education:

```text
GET  /api/drone/health
GET  /api/drone/policy
POST /api/drone/policy/approval-demo
GET  /api/drone/scenarios
GET  /api/drone/models
GET  /api/drone/comparisons
```

Dataset jobs:

```text
POST /api/drone/datasets/generate
GET  /api/drone/datasets
GET  /api/drone/datasets/{dataset_id}
POST /api/drone/datasets/{dataset_id}/cancel
GET  /api/drone/datasets/{dataset_id}/events
```

Training jobs:

```text
POST /api/drone/training-runs
GET  /api/drone/training-runs
GET  /api/drone/training-runs/{run_id}
POST /api/drone/training-runs/{run_id}/cancel
GET  /api/drone/training-runs/{run_id}/events
```

Evaluation jobs and retention:

```text
POST   /api/drone/evaluations
GET    /api/drone/evaluations
GET    /api/drone/evaluations/{evaluation_id}
POST   /api/drone/evaluations/{evaluation_id}/cancel
GET    /api/drone/evaluations/{evaluation_id}/events
GET    /api/drone/exports/{evaluation_id}.json
DELETE /api/drone/records/{record_id}
```

## Create requests and idempotency

Dataset generation always uses the private training partition and all privileged
profiles; callers cannot select an evaluation answer or family through the public
API.

```json
{
  "seed_start": 0,
  "seed_count": 2,
  "timeout_seconds": 120
}
```

Training accepts a completed local dataset:

```json
{
  "dataset_id": "dataset_0123456789abcdef01234567",
  "architecture": "gru",
  "epochs": 10,
  "learning_rate": 0.001,
  "batch_size": 32,
  "context_length": 20,
  "random_seed": 0,
  "timeout_seconds": 300
}
```

Evaluation accepts a completed digest-bound training run and executes every private
profile for the requested evaluation seed domain:

```json
{
  "training_run_id": "talon_train_0123456789abcdef0123456789abcdef",
  "seed_start": 0,
  "seed_count": 1,
  "timeout_seconds": 120
}
```

Send an `Idempotency-Key` header of 8-128 visible ASCII characters on create. The
same key and canonical payload return the existing record; a conflicting payload
returns 409. No key means a new job.

## Events

Dataset, training, and evaluation streams persist monotonically increasing IDs and
support either `Last-Event-ID` or `?after=` replay. Events are public allowlisted
payloads. Evaluation emits each safe timeline step as it completes, then a bounded
episode summary. Exactly one authoritative terminal event is persisted. Reconnect
after a terminal event replays remaining events and closes.

Cancellation is idempotent while cancellation is pending. It cannot change a
completed record. Timeout/cancellation stops the spawned worker and removes partial
artifacts before terminal finalization.

## Public schemas and exports

List/detail endpoints serialize explicit public allowlists rather than raw database
rows. A completed evaluation export contains only:

- opaque evaluation and episode IDs;
- status, record/application/checkpoint digests and public versions;
- aggregate metrics;
- public observation/recommendation/gate timeline;
- final score, verdict, high-level failure categories, and calibration bins.

It cannot contain private family/member IDs, partition or instance digests, expert
actions, hidden truth, full predicate names, private paths, credentials, capability
tokens, raw reasoning, or operator personal information. A recursive safety scan is
run after serialization. Dataset/training exports are intentionally unavailable from
the reviewer endpoint.

Private datasets, training manifests, checkpoints, and full verifier results exist
only beneath `TALON_DATA_DIR/private/<record-id>`. There is no public private-training export
route. Direct filesystem review is a privileged local operator action.

Dataset files are not trusted because they contain a digest string. The strict
loader reconstructs the canonical `talon.private-dataset/3.0` input, recomputes its
SHA-256 digest, compares it safely, and rejects mismatches before normalization,
training, evaluation, checkpoint creation, or inspection. Checkpoint and training
manifests bind the digest returned by that verified loader.

## Retention

`TALON_RETENTION_DAYS=0` disables automatic pruning. A positive value prunes old
terminal records only when no record depends on them. Explicit deletion has the same
dependency rule. A persistent deletion plan is committed before files enter
quarantine; restart recovery restores an uncommitted deletion or completes a
database-committed one.

## Privileged CLI

The CLI is a local privileged operator interface. Unlike public API responses, its
private dataset/evaluation commands may accept a verifier-owned family key and write
private artifacts. Do not expose CLI output as a reviewer export.

```text
python -m drone_training generate-dataset --help
python -m drone_training train-gru --help
python -m drone_training train-decision-transformer --help
python -m drone_training evaluate --help
python -m drone_training inspect-checkpoint --help
python -m drone_training inspect-dataset --help
```

Use `--partition train`, `validation`, or `evaluation` exactly as permitted by the
subcommand. Training refuses non-training data; evaluation requires validation or
evaluation and verifies checkpoint digest and instance non-overlap. CLI timeouts use
killable spawned processes.
