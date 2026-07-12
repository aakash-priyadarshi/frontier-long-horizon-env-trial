from __future__ import annotations

import json

import pytest

from training_adapters.gym_env import IncidentGymEnv
from training_adapters.protocol import ALLOWED_TOOLS
from training_ground.policies import LOGICAL_IDENTITY_FLOW, SETTINGS, valid_repair_policy


def test_gym_env_optional() -> None:
    pytest.importorskip("gymnasium")

    env = IncidentGymEnv(profile=0, max_steps=64)
    obs, info = env.reset()
    assert "allowed_tools" in info
    assert set(info["allowed_tools"]) == set(ALLOWED_TOOLS)
    obs, reward, terminated, truncated, info = env.step(
        {"tool": "bash", "arguments_json": env._encode_text("{}")}
    )
    assert "error" in json.loads(bytes(obs["status_json"]).decode("utf-8") if not isinstance(obs["status_json"], str) else env._decode_text(obs["status_json"]))
    terminated = False
    reward = 0.0
    for action in valid_repair_policy(flow=LOGICAL_IDENTITY_FLOW, settings=SETTINGS):
        obs, reward, terminated, truncated, info = env.step(
            {
                "tool": action["tool"],
                "arguments_json": env._encode_text(json.dumps(action["arguments"])),
            }
        )
        if terminated or truncated:
            break
    env.close()
    assert terminated is True
    assert reward == 1.0


def test_gym_check_env() -> None:
    pytest.importorskip("gymnasium")
    from gymnasium.utils.env_checker import check_env

    env = IncidentGymEnv(profile=0, max_steps=8)
    check_env(env, skip_render_check=True)
    env.close()
