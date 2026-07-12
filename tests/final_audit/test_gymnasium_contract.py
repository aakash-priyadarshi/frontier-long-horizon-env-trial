from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

gymnasium = pytest.importorskip("gymnasium")
from gymnasium.utils.env_checker import check_env

from training_adapters.gym_env import IncidentGymEnv
from training_ground import load_environment
from training_ground.policies import valid_repair_policy


def _gym_action(action: dict[str, Any]) -> dict[str, str]:
    return {
        "tool": action["tool"],
        "arguments_json": json.dumps(action.get("arguments", {}), sort_keys=True),
    }


def test_gymnasium_check_env_passes(tmp_path: Path) -> None:
    env = IncidentGymEnv(profile=0, seed=0, work_dir=str(tmp_path / "check"))
    try:
        check_env(env, skip_render_check=True)
    finally:
        env.close()


def test_reset_observation_belongs_to_space(tmp_path: Path) -> None:
    env = IncidentGymEnv(profile=0, work_dir=str(tmp_path))
    try:
        obs, _ = env.reset()
        assert env.observation_space.contains(obs), obs
    finally:
        env.close()


def test_reference_action_belongs_to_space(tmp_path: Path) -> None:
    env = IncidentGymEnv(profile=0, work_dir=str(tmp_path))
    try:
        action = _gym_action(valid_repair_policy()[0])
        assert env.action_space.contains(action), action
    finally:
        env.close()


def test_gym_seed_behavior_is_deterministic(tmp_path: Path) -> None:
    results = []
    for index in range(2):
        env = IncidentGymEnv(
            profile=0, seed=23, work_dir=str(tmp_path / f"seed-{index}")
        )
        try:
            obs, info = env.reset(seed=23)
            step = env.step(_gym_action(valid_repair_policy()[0]))
            results.append((obs, info["manifest"], step, env._core.transcript()))
        finally:
            env.close()
    assert results[0] == results[1]


def test_gym_and_direct_core_are_behaviorally_equivalent(tmp_path: Path) -> None:
    policy = valid_repair_policy()
    core = load_environment(
        "eval", 0, options={"profile": 0, "max_steps": 64}, work_dir=tmp_path / "core"
    )
    gym = IncidentGymEnv(
        profile=0,
        split="eval",
        seed=0,
        max_steps=64,
        work_dir=str(tmp_path / "gym"),
    )
    try:
        core.reset()
        gym.reset()
        core_results = []
        gym_results = []
        for action in policy:
            core_result = core.step(action)
            gym_result = gym.step(_gym_action(action))
            core_results.append(core_result[1:4])
            gym_results.append(gym_result[1:4])
            if core_result[2] or core_result[3]:
                break
        assert gym_results == core_results
        assert gym._core.transcript() == core.transcript()
        assert gym._core.grade() == core.grade()
    finally:
        gym.close()
        core.close()
