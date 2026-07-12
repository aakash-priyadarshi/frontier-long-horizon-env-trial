"""Scripted and generic rollout runners (no paid model calls)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .protocol import AdapterResponse
from .sanitize import sanitize_payload
from .session import ProtocolGateway, ProtocolSession


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
    """Execute a policy against a live ProtocolSession."""
    policy = policy or ScriptedRecoveryPolicy()
    result = RolloutResult(fixture_index=profile)
    with ProtocolGateway(profile) as session:
        observation = session.observation()
        for step in range(max_steps):
            tool, arguments = policy.select(observation, step)
            response: AdapterResponse = session.call(tool, arguments)
            observation = session.observation()
            result.steps.append(
                RolloutStep(
                    step=step,
                    tool=tool,
                    arguments=arguments,
                    response=response.to_dict(),
                    observation=observation,
                )
            )
            status = observation.get("status") if observation.get("ok") else {}
            if (
                isinstance(status, dict)
                and status.get("incident") == "closed"
                and status.get("public_canary") == "pass"
            ):
                result.success = True
                break
        else:
            result.truncated = True
        result.final_observation = observation
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
