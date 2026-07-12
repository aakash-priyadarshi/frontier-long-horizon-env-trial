from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from training_ground.policies import valid_repair_policy

from tests.final_audit.conftest import execute_policy


def _has_tool(
    policy: list[dict[str, Any]],
    tool: str,
    predicate: Callable[[dict[str, Any]], bool] | None = None,
) -> bool:
    return any(
        action.get("tool") == tool
        and (predicate is None or predicate(action.get("arguments", {})))
        for action in policy
    )


REQUIRED_TRAJECTORY = {
    "trace-acquisition": lambda p: _has_tool(p, "telemetry.logs"),
    "trace-use": lambda p: _has_tool(p, "telemetry.trace"),
    "state-inspection": lambda p: _has_tool(p, "state.inspect"),
    "non-discriminating-experiment": lambda p: _has_tool(
        p, "runtime.run", lambda a: a.get("cutpoint") == "s5.exit"
    ),
    "discriminating-experiment": lambda p: _has_tool(
        p, "runtime.run", lambda a: a.get("cutpoint") == "s2.exit"
    ),
    "pause": lambda p: _has_tool(p, "recovery.pause"),
    "rollback": lambda p: _has_tool(p, "release.rollback"),
    "restore": lambda p: _has_tool(p, "recovery.restore"),
    "edit": lambda p: _has_tool(p, "workspace.edit"),
    "deploy": lambda p: _has_tool(p, "release.deploy"),
    "public-p1": lambda p: _has_tool(
        p, "runtime.run", lambda a: a.get("workload_id") == "P1"
    ),
    "public-p2": lambda p: _has_tool(
        p, "runtime.run", lambda a: a.get("workload_id") == "P2"
    ),
    "public-p3": lambda p: _has_tool(
        p, "runtime.run", lambda a: a.get("workload_id") == "P3"
    ),
    "resume": lambda p: _has_tool(p, "recovery.resume"),
    "final-confirmation": lambda p: bool(p)
    and p[-1].get("tool") == "release.status",
}


@pytest.mark.parametrize(
    ("requirement", "check"), REQUIRED_TRAJECTORY.items(), ids=REQUIRED_TRAJECTORY
)
def test_pair_blind_policy_contains_required_meaningful_action(
    requirement: str, check: Callable[[list[dict[str, Any]]], bool]
) -> None:
    assert check(valid_repair_policy()), requirement


def test_pair_blind_policy_executes_at_least_fifteen_meaningful_actions(
    tmp_path: Path,
) -> None:
    policy = valid_repair_policy()
    assert len(policy) >= 15
    env = execute_policy(profile=0, seed=0, work_dir=tmp_path, policy=policy)
    try:
        transcript = [
            entry for entry in env.transcript() if entry.get("kind") == "step"
        ]
        assert len(transcript) >= 15
        assert transcript[-1]["tool"] == "release.status"
        assert env.grade()["score"] == 1.0
    finally:
        env.close()
