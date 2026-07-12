from __future__ import annotations

from integrations.apex_swe.adapter import run_apex_trial
from training_ground.policies import valid_repair_policy


def test_apex_trial_valid_repair() -> None:
    result = run_apex_trial(
        task_id="apex-eval-001",
        policy=valid_repair_policy(),
        split="eval",
        seed=0,
        profile=0,
        max_steps=64,
    )
    assert result["success"] is True
    assert result["metadata"]["score"] == 1.0
