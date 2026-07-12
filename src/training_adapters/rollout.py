"""Scripted and generic rollout runners (no paid model calls).

These runners wrap the canonical training_ground environment so that smoke tests,
APEX adapters, and Gymnasium share the same episode logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from training_ground.loader import load_environment

from .sanitize import sanitize_payload


class Policy(Protocol):
    def select(self, observation: dict[str, Any], step: int) -> tuple[str, dict[str, Any]]:
        ...


@dataclass
class RolloutStep:
    step: int
    tool: str
    arguments: dict[str, Any]
    response: dict[str, Any]
    observation: dict[str, Any]


@dataclass
class RolloutResult:
    fixture_index: int
    steps: list[RolloutStep] = field(default_factory=list)
    final_observation: dict[str, Any] = field(default_factory=dict)
    success: bool = False
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return sanitize_payload(
            {
                "fixture_index": self.fixture_index,
                "success": self.success,
                "truncated": self.truncated,
                "step_count": len(self.steps),
                "final_observation": self.final_observation,
                "steps": [
                    {
                        "step": s.step,
                        "tool": s.tool,
                        "arguments": s.arguments,
                        "response": s.response,
                    }
                    for s in self.steps
                ],
            }
        )


class ScriptedRecoveryPolicy:
    """Deterministic public recovery path used for smoke tests.

    pause → rollback r0 → restore → settings edit → deploy → P1/P2/P3 → resume
    """

    def __init__(self) -> None:
        self._plan: list[tuple[str, dict[str, Any]]] = [
            ("release.status", {}),
            ("recovery.pause", {}),
            ("release.rollback", {"revision": "r0"}),
            ("recovery.restore", {"snapshot_id": "S0"}),
            (
                "workspace.edit",
                {
                    "path": "service/settings.toml",
                    "content": (
                        "[service]\n"
                        "intake_enabled = true\n"
                        "settlement_enabled = true\n"
                        "attempt_budget = 2\n"
                        'transient_behavior = "retry"\n'
                    ),
                },
            ),
            ("release.deploy", {}),
            ("runtime.run", {"workload_id": "P1"}),
            ("runtime.run", {"workload_id": "P2"}),
            ("runtime.run", {"workload_id": "P3"}),
            ("recovery.resume", {}),
            ("release.status", {}),
        ]
        self._index = 0

    def select(self, observation: dict[str, Any], step: int) -> tuple[str, dict[str, Any]]:
        if self._index >= len(self._plan):
            return ("release.status", {})
        action = self._plan[self._index]
        self._index += 1
        return action


def run_rollout(
    *,
    profile: int = 0,
    policy: Policy | None = None,
    max_steps: int = 32,
) -> RolloutResult:
    """Execute a policy against the training_ground environment."""
    policy = policy or ScriptedRecoveryPolicy()
    result = RolloutResult(fixture_index=profile)
    env = load_environment(
        "eval",
        0,
        options={"profile": profile, "max_steps": max_steps},
    )
    observation, _ = env.reset()
    try:
        for step in range(max_steps):
            tool, arguments = policy.select(observation, step)
            observation, reward, terminated, truncated, info = env.step(
                {"tool": tool, "arguments": arguments}
            )
            result.steps.append(
                RolloutStep(
                    step=step,
                    tool=tool,
                    arguments=arguments,
                    response=info.get("response", {}),
                    observation=observation,
                )
            )
            if (
                observation.get("incident") == "closed"
                and observation.get("public_canary") == "pass"
            ):
                result.success = True
                result.final_observation = {"ok": True, "status": observation}
                break
            if terminated or truncated:
                result.truncated = not result.success
                result.final_observation = {"ok": False, "status": observation}
                break
        else:
            result.truncated = True
            result.final_observation = {"ok": False, "status": observation}
    finally:
        env.close()
    return result


def run_rollout_from_action_list(
    actions: list[tuple[str, dict[str, Any]]], *, profile: int = 0
) -> RolloutResult:
    class _ListPolicy:
        def __init__(self) -> None:
            self.i = 0

        def select(self, observation: dict[str, Any], step: int) -> tuple[str, dict[str, Any]]:
            if self.i >= len(actions):
                return ("release.status", {})
            item = actions[self.i]
            self.i += 1
            return item

    return run_rollout(profile=profile, policy=_ListPolicy(), max_steps=len(actions) + 2)
