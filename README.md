# Frontier Long-Horizon Environment Trial

An original research and implementation trial for a deterministic, long-horizon
coding-agent environment built around paired incident recovery with matched public
artifacts and distinct privileged histories.

## Current status

Version two adds a locally runnable model-evaluation control plane on
`feature/model-evaluation-dashboard`. The existing `training_ground` environment
and strict verifier remain the sole action and scoring authorities. Version one is
frozen at `trial-submission-v1` (`abcb015d…`); V2 is additive and is not merged to
`main`.

The V2 product includes:

- a FastAPI/SQLite evaluation service with SSE replay and immutable terminal records;
- provider-neutral scripted, OpenAI-compatible, Anthropic, Gemini, and Ollama adapters;
- a deterministic valid baseline and a wrong-control baseline over the real twelve tools;
- a shared `python -m model_eval` CLI;
- a responsive Next.js dashboard using Motion for React and Chart.js;
- credential, hidden-state, digest, API, unit, and Playwright verification.

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
  authenticated transcript checks, durable hidden workloads, reward ladder, and
  receipts;
- `src/training_adapters/` — Gymnasium env and APEX task-pack result shaping that wrap
  `training_ground`;
- `src/integrations/apex_swe/` — APEX-SWE task pack and local side-car smoke over
  `training_ground`;
- `tests/final_core/`, `tests/soundness/`, `tests/controls/`, and
  `tests/final_audit/` — final-core, soundness, control, and audit regression tests.

Training/APEX-facing adapters live under `src/training_adapters/` and
`src/integrations/apex_swe/` (see `docs/training-adapters.md`). Gymnasium is checked
with `gymnasium.utils.env_checker.check_env`. APEX is **task-pack compatibility plus
side-car smoke only**; real upstream `apx run` and model-driven harness execution
are **NOT VERIFIED**.

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

cd apps\dashboard
npm install
```

## Run version two

Start both services from the environment root:

```powershell
.\scripts\dev_v2.ps1
```

- Dashboard: `http://localhost:3000`
- API and OpenAPI: `http://localhost:8000`, `http://localhost:8000/docs`

Or use two terminals:

```powershell
.\.venv\Scripts\python.exe -m uvicorn evaluation_service.app:app --reload --port 8000
cd apps\dashboard
npm run dev
```

Credential-free CLI demo:

```powershell
.\.venv\Scripts\python.exe -m model_eval run --provider scripted --model scripted-valid --split eval --seed 0 --attempts 1
```

See `docs/V2_LOCAL_DEVELOPMENT.md` and `.env.example` for full configuration.

## Verify

Run the full test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Regenerate the final machine-readable receipt from fresh live runs:

```powershell
$source = git rev-parse HEAD

.\.venv\Scripts\python.exe scripts\verify_final_environment.py `
  --source-commit $source `
  --output evidence\final-environment.json
```

The `verify_final_environment.py` entrypoint validates source-commit binding, runs
pytest suites including `tests/final_audit`, runs `training_ground` scripted
trajectories on `dev` and `eval` instances, lists public instance IDs, validates the
Gymnasium adapter, records gold-family/control/reward snapshots, and writes
`evidence/final-environment.json`.

upstream apex-swe harness: **not verified**
docker execution: **not verified**
Additional scripts:

```powershell
.\.venv\Scripts\python.exe -m training_ground.cli run-scripted --split eval --seed 0
.\.venv\Scripts\python.exe scripts\smoke_apex_scripted.py
.\.venv\Scripts\python.exe -m training_ground.cli list-instances --split eval --count 5
```

Docker execution is **NOT VERIFIED** unless a Docker daemon is available and the
daemon-backed smoke/probe has completed.

## Security boundary

Snapshot, recovery, and transcript authenticity use HMAC-SHA256 capabilities
supplied by privileged fixture-building code. Keys are not stored in SQLite, public
workspace files, status output, logs, canonical roots, or evidence receipts.
Authentication binds snapshot identity, state payload and root, creation tick,
fixture scope, recovery transition provenance, and episode transcript chains.

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
- Final remediation is awaiting post-fix audit; later work is not begun automatically.
