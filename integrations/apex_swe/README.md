# APEX-SWE integration pack (read-only upstream)

This directory packages the frontier incident environment as an APEX-SWE
**integration** harness task. Upstream APEX-SWE is MIT-licensed and remains a
read-only checkout; this repository does not vendor APEX source.

## Upstream reviewed (APEX-SWE `7cfa580dd59704ff15cf558bda80257c23b6cb04`)

| Component | Path |
|---|---|
| License | `LICENSE` (MIT) |
| Root overview | `README.md` |
| Integration harness README | `integration/README.md` |
| Task load / timeouts | `integration/src/harness/executor.py` |
| Agent loop / Docker | `integration/src/harness/multi_step_runner.py` |
| Test parsing | `integration/src/harness/evaluator.py` |
| Result models | `integration/src/harness/data_models.py` |
| Tool executor | `integration/src/tools/tool_executor.py` |
| Docker manager | `integration/src/utils/docker_manager.py` |
| MCP service map | `integration/src/config/__init__.py` |
| Observability E2E (contrast) | `observability/README.md`, `observability/eval_runner/runner.py` |

## Task

`tasks/frontier-incident-smoke/` is a minimal integration task:

- `task.yaml` — instruction + timeouts (`max_agent_timeout_sec`, `max_test_timeout_sec`)
- `docker-compose.yaml` — `client` service (APEX compose contract)
- `Dockerfile` — installs this repository's `src` packages
- `scripted_agent.py` — deterministic twelve-tool recovery policy (**no paid models**)
- `run_tests.py` / `run-tests.sh` — emit APEX `PASSED`/`FAILED` markers

## Local smoke (no Docker, no API keys)

From the trial repository root:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_apex_scripted.py
```

## Docker smoke

Requires a running Docker daemon. Then:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_apex_docker.py
```

If Docker is unavailable, the script exits 0 with status `SKIPPED`.

## Tool boundary

APEX's native tools (terminal/keystrokes, Inspect bash, MCP shells) are **not**
granted inside this task's scripted path. The evaluated interface is strictly the
twelve gateway tools enforced by `training_adapters.ToolFilter`.

## Scoring note

This smoke task grades the **public recovery path** only. Hidden verifier /
oracle grading remains outside adapter scope and is not mounted.
