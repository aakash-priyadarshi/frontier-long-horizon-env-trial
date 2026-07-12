# Frontier Long-Horizon Environment Trial

An original research and implementation trial for a deterministic, long-horizon
coding-agent environment. The current build is intentionally limited to the first
approved implementation milestone: a paired incident-service substrate with matched
public artifacts and distinct privileged histories.

## Current status

**Final integrated build. The environment now provides a canonical `training_ground`
core, a strict `strict_verifier` grader, APEX-SWE integration adapters, and
reconciled Gymnasium/APEX wrappers. All 84 targeted tests and the final
verification script pass and produce a machine-readable receipt at
`evidence/final-environment.json`.**

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
- `src/training_ground/` — the canonical Gymnasium-compatible environment core
  with protocol, actions, observations, episodes, manifests, and CLI;
- `src/strict_verifier/` — deterministic ground-truth verifier, predicates,
  hidden workloads, reward ladder, and receipts;
- `src/training_adapters/` — Gymnasium env and APEX result shaping that wrap
  `training_ground`;
- `src/integrations/apex_swe/` — APEX-SWE task harness over `training_ground`;
- `tests/final_core/`, `tests/soundness/`, `tests/controls/`, and
  `tests/integrations/` — final-core, soundness, control, and integration tests.

Training/APEX interoperability adapters live under `src/training_adapters/` and
`src/integrations/apex_swe/` (see `docs/training-adapters.md`). They wrap the
`training_ground` core for Gymnasium rollouts and APEX-SWE task packaging without
changing the hidden verifier or evidence receipts.

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

Run the full test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Regenerate the final machine-readable receipt from fresh live runs:

```powershell
.\.venv\Scripts\python.exe scripts\verify_final_environment.py --output evidence\final-environment.json
```

The `verify_final_environment.py` entrypoint runs pytest, runs `training_ground`
scripted trajectories on `dev` and `eval` instances, lists public instance IDs,
validates the Gymnasium adapter, and writes `evidence/final-environment.json`.
Additional scripts:

```powershell
.\.venv\Scripts\python.exe -m training_ground.cli run-scripted --split eval --seed 0
.\.venv\Scripts\python.exe scripts\smoke_apex_scripted.py
.\.venv\Scripts\python.exe -m training_ground.cli list-instances --split eval --count 5
```

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
- Milestone 2 is closed after verification and evidence regeneration; later
  milestones are not begun automatically.
