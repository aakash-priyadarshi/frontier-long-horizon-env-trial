"""Scripted and generic rollout runners (no paid model calls)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from training_ground.loader import load_environment
from training_ground.policies import LOGICAL_IDENTITY_FLOW, SETTINGS, valid_repair_policy

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
    strict_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return sanitize_payload(
            {
                "fixture_index": self.fixture_index,
                "success": self.success,
                "truncated": self.truncated,
                "strict_score": self.strict_score,
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
    """Strict valid repair policy used for APEX/local smokes."""

    def __init__(self, flow: str = LOGICAL_IDENTITY_FLOW, settings: str = SETTINGS) -> None:
        self._plan = [
            (action["tool"], action["arguments"])
            for action in valid_repair_policy(flow=flow, settings=settings)
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
    max_steps: int = 64,
    require_strict: bool = True,
) -> RolloutResult:
    """Execute a policy against the training_ground environment.

    When ``require_strict`` is True (default), success requires the real strict
    verifier score of 1.0 — public canary closure alone is not enough.
    """
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
                    response={"digest": info.get("response_digest")},
                    observation=observation,
                )
            )
            if terminated or truncated:
                grade = info.get("grade") or env.grade()
                result.strict_score = float(grade.get("score", 0.0))
                if require_strict:
                    result.success = result.strict_score == 1.0
                else:
                    result.success = (
                        observation.get("incident") == "closed"
                        and observation.get("public_canary") == "pass"
                    )
                result.truncated = truncated and not result.success
                result.final_observation = {
                    "ok": result.success,
                    "status": observation,
                    "strict_score": result.strict_score,
                }
                break
        else:
            grade = env.grade()
            result.strict_score = float(grade.get("score", 0.0))
            result.truncated = True
            result.final_observation = {"ok": False, "status": observation}
    finally:
        env.close()
    return result
