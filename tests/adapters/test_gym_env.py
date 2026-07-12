from __future__ import annotations

import pytest

from training_adapters.protocol import ALLOWED_TOOLS


def test_gym_env_optional() -> None:
    pytest.importorskip("gymnasium")
    import json

    from training_adapters.gym_env import IncidentGymEnv

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
    policy_actions = [
        ("recovery.pause", {}),
        ("release.rollback", {"revision": "r0"}),
        ("recovery.restore", {"snapshot_id": "S0"}),
        (
            "workspace.edit",
            {
                "path": "service/settings.toml",
                "content": (
                    "[service]\nintake_enabled = true\nsettlement_enabled = true\n"
                    "attempt_budget = 2\ntransient_behavior = \"retry\"\n"
                ),
            },
        ),
        ("release.deploy", {}),
        ("runtime.run", {"workload_id": "P1"}),
        ("runtime.run", {"workload_id": "P2"}),
        ("runtime.run", {"workload_id": "P3"}),
        ("recovery.resume", {}),
    ]
    terminated = False
    for tool, args in policy_actions:
        obs, reward, terminated, truncated, info = env.step(
            {"tool": tool, "arguments_json": json.dumps(args)}
        )
        if terminated:
            break
    env.close()
    assert terminated is True
    assert reward == 1.0
