from __future__ import annotations

import json

import pytest

from training_adapters.gym_env import IncidentGymEnv
from training_adapters.protocol import ALLOWED_TOOLS
from training_ground.policies import IDEMPOTENT_FLOW, SETTINGS


def test_gym_env_optional() -> None:
    pytest.importorskip("gymnasium")

    env = IncidentGymEnv(profile=0, max_steps=20)
    obs, info = env.reset()
    assert "allowed_tools" in info
    assert set(info["allowed_tools"]) == set(ALLOWED_TOOLS)
    # Reject unknown tool via env step
    obs, reward, terminated, truncated, info = env.step(
        {"tool": "bash", "arguments_json": "{}"}
    )
    assert info["response"]["error"]["code"] == "unknown_tool"
    # Drive scripted recovery through gym actions
    policy = [
        ("telemetry.logs", {"alias": "Q-41"}),
        ("state.inspect", {"source": "public", "selector": {"stream": "settlement"}, "view": "progress"}),
        ("recovery.pause", {}),
        ("release.rollback", {"revision": "r0"}),
        ("recovery.restore", {"snapshot_id": "S0"}),
        ("workspace.read", {"path": "service/flow.py"}),
        ("workspace.read", {"path": "service/settings.toml"}),
        ("workspace.edit", {"path": "service/flow.py", "content": IDEMPOTENT_FLOW}),
        ("workspace.edit", {"path": "service/settings.toml", "content": SETTINGS}),
        ("release.deploy", {}),
        ("runtime.run", {"workload_id": "P1"}),
        ("runtime.run", {"workload_id": "P2"}),
        ("runtime.run", {"workload_id": "P3"}),
        ("recovery.resume", {}),
        ("release.status", {}),
    ]
    terminated = False
    for tool, args in policy:
        obs, reward, terminated, truncated, info = env.step(
            {"tool": tool, "arguments_json": json.dumps(args)}
        )
        if terminated:
            break
    env.close()
    assert terminated is True
    assert reward == 1.0
