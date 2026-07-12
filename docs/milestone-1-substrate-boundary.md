# Milestone 1 substrate boundary

## Status

Milestone 1 audit fixes are implemented and awaiting targeted re-audit. This document
describes the implemented substrate only. It does not describe an agent tool API,
workload suite, hidden verifier, model evaluation, or production deployment system.

## Authenticated snapshots and recovery

Each fixture receives a `RecoveryAuthority` capability from privileged build or test
code. The authority uses HMAC-SHA256 and keeps its key and fixture scope in privileged
process memory. Neither value is written to SQLite or copied into the public
workspace, status output, logs, paths, roots, or evidence receipts.

Snapshot authentication binds:

- snapshot identity;
- canonical service-state payload and root;
- creation tick;
- fixture authority scope.

Recovery proof authentication additionally binds:

- snapshot identity;
- pre-restore and post-restore service-state roots;
- the complete prior audit root;
- restore action and fake-clock tick;
- actor capability scope;
- the exact restore audit sequence and entry hash.

Restoration requires paused intake, an authenticated snapshot, and a valid prior
audit chain. It restores only canonical service-data tables, appends an audit
transition and authenticated recovery proof, and preserves prior telemetry and audit
history. Direct row mutation plus a syntactically valid audit entry does not produce
a valid recovery proof.

This mechanism provides local privileged authentication. It is not production OS,
process, container, or deployment isolation.

## Canonical roots

The substrate keeps these boundaries separate:

| Root | Contents |
|---|---|
| `source` | Sorted neutral public source artifacts. |
| `config` | Canonical bytes for the active deployment configuration. |
| `service_state` | Journal, cursor, effects, intents, event marks, and command mappings. |
| `deployment` | Revision code roots, configuration bytes and roots, activation ticks, and statuses. |
| `runtime` | Fake tick and intake state. |
| `telemetry` | Explicitly sequenced append-only telemetry rows. |
| `audit` | The complete chained audit history. |
| `snapshot` | Semantic snapshot content excluding authentication tags. |

Authentication tags are intentionally excluded from public and semantic roots. This
allows matched fixtures to retain equal public roots while cross-fixture snapshot
substitution still fails authentication.

## Public surface and future mount boundary

Milestone 1 enumerates and compares the intended public surface:

- every public workspace path and file digest;
- serialized public status;
- ticket, visible logs, and artifact-derived revision diff;
- visible exceptions exercised by verification;
- public roots and combined public bytes;
- package use of process or environment metadata;
- human evidence receipt fields.

The following are privileged and must not be mounted into a future agent runtime:

- the fixture-building package source;
- fixture SQLite databases;
- audit and human evidence receipts;
- Milestone 1 tests and process probes;
- authority keys and privileged build scripts.

The future agent-mount boundary remains **NOT VERIFIED** until later packaging or
runtime work implements and tests it. Milestone 2 must not begin before the targeted
Milestone 1 re-audit is reviewed and explicit approval is given.

## Reproduction

Run the focused tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\milestone_1 -q
```

Run tests and regenerate the live receipt in one command:

```powershell
.\.venv\Scripts\python.exe scripts\verify_milestone_1.py
```
