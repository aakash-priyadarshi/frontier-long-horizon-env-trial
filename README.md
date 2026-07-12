# Frontier Long-Horizon Environment Trial

An original research and implementation trial for a deterministic, long-horizon
coding-agent environment. The current build is intentionally limited to the first
approved implementation milestone: a paired incident-service substrate with matched
public artifacts and distinct privileged histories.

## Current status

Milestone 1 is complete. The repository currently provides:

- a single-process Python 3.12 service substrate backed by SQLite;
- an integer-only fake clock with deterministic transition costs;
- canonical source, configuration, state, telemetry, audit, and snapshot roots;
- byte-identical neutral public workspaces for both fixtures;
- shared `r0` and `r1` revision history plus a candidate placeholder;
- signed `S0` restoration that preserves telemetry and audit history;
- focused tests for reproducibility, recovery provenance, and public-surface leaks.

The agent tool API, hidden verifier, workload suite, solution controls, container
runtime, and model evaluations are intentionally deferred to later approved
milestones.

## Repository layout

```text
research/                     Research and approved verifier-spike design
src/event_service_substrate/  Deterministic service and persistence substrate
tests/milestone_1/            Focused Milestone 1 verification
evidence/                     Machine-readable verification receipts
```

## Setup

Python 3.12 is required. From PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest tests\milestone_1 -q
```

The corresponding machine-readable result is stored in
`evidence/milestone-1-substrate.json`.

## Project constraints

- All task concepts, code, tests, and evidence are original to this trial.
- Claims must be supported by reproducible evidence.
- The public workspace must not disclose its privileged fixture selection.
- Implementation work advances only through reviewed milestones.
