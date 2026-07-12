# Frontier Long-Horizon Environment Trial

An original research and implementation trial for a deterministic, long-horizon
coding-agent environment. The current build is intentionally limited to the first
approved implementation milestone: a paired incident-service substrate with matched
public artifacts and distinct privileged histories.

## Current status

**Milestone 1 closed after targeted re-audit. Milestone 2 interaction-layer
implementation is explicitly approved.**

The repository currently provides:

- a single-process Python 3.12 service substrate backed by SQLite;
- an integer-only fake clock with deterministic transition costs;
- separate canonical roots for source, active configuration, service data,
  deployment state, runtime state, telemetry, audit history, and snapshot semantics;
- byte-identical neutral public workspaces for both fixtures;
- shared `r0` and `r1` revision history plus a candidate placeholder;
- locally HMAC-authenticated `S0` restoration with authenticated recovery provenance;
- focused negative tests for forgery, reproducibility, recovery provenance, and
  complete public-surface enumeration;
- a one-command verifier that reruns tests and regenerates the evidence receipt from
  fresh fixtures.

The agent tool API, hidden verifier, workload suite, solution controls, container
runtime, and model evaluations are intentionally deferred to later approved
milestones.

## Repository layout

```text
research/                     Research, approved design, and independent audit
src/event_service_substrate/  Deterministic service and persistence substrate
tests/milestone_1/            Focused Milestone 1 verification
scripts/                      Reproducible verification entrypoints
docs/                         Implemented Milestone 1 boundary documentation
evidence/                     Machine-readable verification receipts
```

## Setup

Python 3.12 is required. From PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

## Verify

Run the focused suite directly:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\milestone_1 -q
```

Regenerate the machine-readable receipt from a fresh live run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_milestone_1.py
```

The entrypoint stops if pytest or any live root, equality, authentication, recovery,
or leak check fails. On success it writes `evidence/milestone-1-substrate.json`.

## Security boundary

Snapshot and recovery authenticity use HMAC-SHA256 with a capability supplied by
privileged fixture-building code. The key is not stored in SQLite, public workspace
files, status output, logs, canonical roots, or evidence receipts. Authentication
binds the snapshot identity, state payload and root, creation tick, fixture scope,
and recovery transition provenance.

This is local privileged authentication, not production OS, process, container, or
deployment isolation. The future agent-mount boundary is **NOT VERIFIED**. Privileged
builder package source, fixture databases, audit receipts, tests, and authority key
material must not be mounted into a future agent runtime.

The implemented root boundaries are documented in
`docs/milestone-1-substrate-boundary.md`.

## Project constraints

- All task concepts, code, tests, and evidence are original to this trial.
- Claims must be supported by reproducible evidence.
- The public workspace must not disclose its privileged fixture selection.
- Implementation work advances only through reviewed milestones.
- Milestone 2 interaction-layer work may begin under the approved milestone scope.
