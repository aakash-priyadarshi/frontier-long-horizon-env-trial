# Training adapters and APEX interoperability

## Purpose

`src/training_adapters/` adds Gymnasium and APEX-SWE interoperability **without**
modifying the core substrate, gateway security model, verifier, reward logic,
hidden workloads, or evidence receipts.

## Shared protocol

- Version: `training_adapters.protocol.PROTOCOL_VERSION`
- Wire format: JSON-lines compatible with `agent_surface.gateway`
- Agent-legal tools: exactly the twelve names in `ALLOWED_TOOLS`
- Harness-only: `system.close`, `system.leak_probe`

## Components

| Module | Role |
|---|---|
| `protocol.py` | Request/response dataclasses |
| `tools.py` | Strict twelve-tool filter |
| `sanitize.py` | Strip privileged keys/tokens from observations |
| `session.py` | `ProtocolGateway` / `ProtocolSession` |
| `gym_env.py` | Optional Gymnasium env |
| `rollout.py` | Scripted rollout runner |
| `apex_compat.py` | APEX task-dir validation + result shaping |

## Security invariants

1. Adapters never export `AgentSession`, `StateStore`, fixture objects, or authority keys.
2. Tool calls outside the twelve-name inventory fail closed.
3. Sanitization removes profile/authority/sqlite/traceback material from transcripts.
4. APEX task packaging must not mount `evidence/`, tests, or builder keys into an
   evaluated runtime image beyond what the task Dockerfile explicitly copies
   (current smoke image copies `src` + the task pack only).

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/adapters -q
.\.venv\Scripts\python.exe scripts\smoke_adapters_local.py
.\.venv\Scripts\python.exe scripts\smoke_apex_scripted.py
.\.venv\Scripts\python.exe scripts\smoke_apex_docker.py
```
