from __future__ import annotations

import pytest

from training_ground import load_environment
from training_ground.manifests import build_manifest


def test_manifest_is_pair_blind() -> None:
    m = build_manifest("train", 0)
    public = m.public()
    assert "environment_version" in public
    assert "public_instance_id" in public
    assert "limits" in public
    assert "profile" not in public


def test_environment_reset_and_step() -> None:
    env = load_environment("dev", 1234, options={"max_steps": 10})
    obs, info = env.reset()
    assert "incident" in obs
    assert obs["incident"] == "open"
    assert "allowed_tools" in info
    # Unknown tool should be rejected with a controlled error observation.
    obs, reward, terminated, truncated, info = env.step(
        {"tool": "system.leak_probe", "arguments": {}}
    )
    assert "error" in obs
    assert reward == 0.0
    assert terminated is False
    env.close()
