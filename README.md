# Frontier Long-Horizon Environment Trial

An original research and implementation trial for a deterministic, long-horizon
coding-agent environment. The current build is intentionally limited to the first
approved implementation milestone: a paired incident-service substrate with matched
public artifacts and distinct privileged histories.

## Current status

**Milestone 1 closed after targeted re-audit. Milestone 2 interaction-layer
implementation is closed: the audit findings C1, M1-M5 and the remaining
targeted gaps (trace capability authority, source-commit binding, gateway error
codes, fixed tool dispatch, and deterministic evidence) are implemented and
verified.**

The repository currently provides:

- a single-process Python 3.12 service substrate backed by SQLite;
- an integer-only fake clock with deterministic transition costs;
- separate canonical roots for source, active configuration, service data,
  deployment state, runtime state, telemetry, audit history, and snapshot semantics;
- byte-identical neutral public workspaces for both fixtures;
- shared `r0` and `r1` revision history plus a candidate placeholder;
- locally HMAC-authenticated `S0` restoration with authenticated recovery provenance;
- HMAC-secured, epoch-bound trace capability tokens that bind each session, run,
  selector, and view and are invalidated on state transitions;
- a process-separated JSON tool gateway that is the evaluated agent's only
  supported interface (the privileged controller owns the fixture, session, and
  runtime; the evaluated side speaks JSON-lines over stdin/stdout);
- focused Milestone 2 interaction-layer tests plus the Milestone 1 regression baseline;
- one-command verifiers that rerun tests and regenerate evidence receipts from
  fresh fixtures.

The hidden verifier, full workload suite, solution controls, container runtime,
and model evaluations are intentionally deferred to later approved milestones.

## Repository layout

```text
research/                     Research, approved design, and independent audit
src/event_service_substrate/  Deterministic service and persistence substrate
src/agent_surface/            Evaluated-agent interaction layer and gateway
tests/milestone_1/            Focused Milestone 1 verification
tests/milestone_2/            Focused Milestone 2 interaction-layer verification
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

Run the full test suite (Milestone 1 regression baseline plus Milestone 2):

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Regenerate the machine-readable receipts from fresh live runs:

```powershell
.\.venv\Scripts\python.exe scripts\verify_milestone_1.py
.\.venv\Scripts\python.exe scripts\verify_milestone_2.py
```

The `verify_milestone_2.py` entrypoint runs `pytest tests/milestone_1` and
`pytest tests/milestone_2` separately, then performs a live agent-surface run
through the process-separated JSON gateway. It stops if pytest or any live root,
equality, authentication, recovery, leak, or capability check fails. On success it
writes `evidence/milestone-2-interaction-layer.json` with the source commit SHA,
per-milestone test counts, and a total count.
`verify_milestone_1.py` and `verify_milestone_2.py` accept `--source-commit` to
bind the receipt to the implementation commit when the receipt is committed at
repository tip.

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
- Milestone 2 audit remediation applies only the confirmed findings and related
  non-blocking fixes; later milestones are not begun automatically.
