from __future__ import annotations

from pathlib import Path

import pytest

import training_ground.episode as episode_module
from training_adapters.sanitize import sanitize_payload
from training_ground import load_environment
from training_ground.manifests import build_manifest
from training_ground.protocol import EnvironmentError

from tests.final_audit.conftest import execute_policy


def test_reset_twice_reuses_same_work_directory(tmp_path: Path) -> None:
    env = load_environment("eval", 0, work_dir=tmp_path / "episode")
    try:
        first, _ = env.reset()
        second, _ = env.reset()
        assert first == second
    finally:
        env.close()

def test_reset_after_close_reuses_same_work_directory(tmp_path: Path) -> None:
    env = load_environment("eval", 0, work_dir=tmp_path / "episode")
    env.reset()
    env.close()
    try:
        obs, info = env.reset()
        assert obs["incident"] == "open"
        assert info["instance_id"] == build_manifest("eval", 0).instance_id
    finally:
        env.close()


def test_reset_seed_selects_the_requested_deterministic_instance(tmp_path: Path) -> None:
    env = load_environment("eval", 0, work_dir=tmp_path / "episode")
    try:
        _, info = env.reset(seed=17)
        expected = build_manifest("eval", 17)
        assert info["manifest"]["seed"] == 17
        assert info["instance_id"] == expected.instance_id
    finally:
        env.close()


def test_step_after_terminated_is_rejected(tmp_path: Path) -> None:
    env = execute_policy(profile=0, seed=0, work_dir=tmp_path / "terminated")
    try:
        assert env.grade()["score"] == 1.0
        with pytest.raises(EnvironmentError):
            env.step({"tool": "release.status", "arguments": {}})
    finally:
        env.close()


def test_step_after_truncated_is_rejected(tmp_path: Path) -> None:
    env = load_environment(
        "eval", 0, options={"profile": 0, "max_steps": 1}, work_dir=tmp_path / "truncated"
    )
    try:
        env.reset()
        _, _, terminated, truncated, _ = env.step(
            {"tool": "release.status", "arguments": {}}
        )
        assert not terminated and truncated
        with pytest.raises(EnvironmentError):
            env.step({"tool": "release.status", "arguments": {}})
    finally:
        env.close()


def test_arguments_list_is_rejected_not_coerced(tmp_path: Path) -> None:
    env = load_environment("eval", 0, work_dir=tmp_path)
    try:
        env.reset()
        obs, _, _, _, info = env.step({"tool": "release.status", "arguments": []})
        assert obs["error"]["code"] == "invalid_arguments"
        assert info["response"]["error"]["code"] == "invalid_arguments"
    finally:
        env.close()


def test_unknown_extra_action_fields_are_rejected(tmp_path: Path) -> None:
    env = load_environment("eval", 0, work_dir=tmp_path)
    try:
        env.reset()
        obs, _, _, _, info = env.step(
            {"tool": "release.status", "arguments": {}, "unexpected": "field"}
        )
        assert obs["error"]["code"] == "invalid_action"
        assert info["response"]["error"]["code"] == "invalid_action"
    finally:
        env.close()


def test_raw_tool_response_is_sanitized_before_info(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = {
        "profile": 1,
        "database": "C:\\private\\service.sqlite3",
        "token_hex": "deadbeef",
        "safe": "visible",
    }
    monkeypatch.setattr(episode_module, "dispatch_action", lambda *args: raw)
    env = load_environment("eval", 0, work_dir=tmp_path)
    try:
        env.reset()
        _, _, _, _, info = env.step({"tool": "release.status", "arguments": {}})
        assert info["response"] == sanitize_payload(raw)
        assert "profile" not in info["response"]
    finally:
        env.close()


def test_child_process_death_is_controlled_truncation(tmp_path: Path) -> None:
    env = load_environment("eval", 0, work_dir=tmp_path)
    try:
        env.reset()
        assert env._gateway is not None and env._gateway._process is not None
        env._gateway._process.kill()
        env._gateway._process.wait(timeout=5)
        obs, reward, terminated, truncated, info = env.step(
            {"tool": "release.status", "arguments": {}}
        )
        assert reward == 0.0
        assert not terminated and truncated
        assert obs["error"]["code"] == "gateway_unavailable"
        assert info["response"]["error"]["code"] == "gateway_unavailable"
    finally:
        env.close()
