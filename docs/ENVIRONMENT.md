# Environment core

## `training_ground`

`src/training_ground/` is the canonical Gymnasium-compatible environment core.

### Modules

- `protocol.py` — `EnvironmentProtocol`, `EnvironmentError`, and protocol constants.
- `actions.py` — `ToolAction` dispatch and the twelve-tool agent surface.
- `observations.py` — `ObservationSpace` and sanitized observation builders.
- `episode.py` — `IncidentEnv` (`Env` API) that drives `AgentSession`.
- `manifests.py` — `Manifest` and `list_instance_ids` for `train/dev/eval` splits.
- `limits.py` — `Limits` checks on step count, bytes, and tick.
- `authority.py` — `EpisodeAuthority` for transcript and integrity handling.
- `transcripts.py` — `TranscriptStore` and `EpisodeTranscript` for deterministic replay.
- `loader.py` — `load_environment(split, seed, options)` and `load_environment_from_manifest`.
- `cli.py` — `run-scripted`, `list-instances`, and `grade` CLI entrypoints.
- `policies.py` — pair-blind reference policies and `IDEMPOTENT_FLOW`/`SETTINGS`.

### Entrypoints

```powershell
.\.venv\Scripts\python.exe -m training_ground.cli run-scripted --split eval --seed 0
.\.venv\Scripts\python.exe -m training_ground.cli list-instances --split eval --count 5
```

### Python API

```python
from training_ground import load_environment, valid_repair_policy

env = load_environment("eval", 0, options={"max_steps": 64})
obs, info = env.reset()
for action in valid_repair_policy():
    obs, reward, terminated, truncated, info = env.step(action)
    if terminated or truncated:
        break
print(env.grade())
env.close()
```
