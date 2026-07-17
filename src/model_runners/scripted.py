"""Deterministic, credential-free adapter that exercises the real environment."""

from __future__ import annotations

from training_ground.policies import BROAD_EVENT_DEDUP_FLOW, valid_repair_policy

from .protocol import ModelMessage, ModelRequestConfig, ModelResponse, ModelTool, ModelToolCall


SCRIPTED_MODELS = (
    {"id": "scripted-valid", "display_name": "Scripted valid repair"},
    {"id": "scripted-wrong-control", "display_name": "Scripted wrong-control repair"},
)


class ScriptedAdapter:
    provider = "scripted"

    def __init__(self) -> None:
        self._cursor = 0

    async def complete(
        self,
        *,
        messages: list[ModelMessage],
        tools: list[ModelTool],
        config: ModelRequestConfig,
    ) -> ModelResponse:
        policy = (
            valid_repair_policy()
            if config.model == "scripted-valid"
            else valid_repair_policy(flow=BROAD_EVENT_DEDUP_FLOW)
        )
        if self._cursor >= len(policy):
            return ModelResponse(text="Episode complete.", finish_reason="stop")
        action = policy[self._cursor]
        self._cursor += 1
        call = ModelToolCall(
            id=f"scripted-{self._cursor}",
            name=action["tool"],
            arguments=dict(action.get("arguments") or {}),
        )
        return ModelResponse(
            text="",
            tool_calls=(call,),
            provider_request_id=f"scripted-request-{self._cursor}",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0.0,
            estimated_cost=0.0,
            finish_reason="tool_calls",
        )
