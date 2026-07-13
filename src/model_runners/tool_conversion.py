"""Provider payload conversion with strict structured argument parsing."""

from __future__ import annotations

import json
from typing import Any

from .errors import MalformedModelResponse
from .protocol import ModelMessage, ModelTool, ModelToolCall


def openai_tools(tools: list[ModelTool]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


def openai_messages(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        row: dict[str, Any] = {"role": message.role, "content": message.content or None}
        if message.tool_call_id:
            row["tool_call_id"] = message.tool_call_id
        if message.name:
            row["name"] = message.name
        if message.tool_calls:
            row["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in message.tool_calls
            ]
        result.append(row)
    return result


def parse_json_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise MalformedModelResponse("tool arguments must be a JSON object")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise MalformedModelResponse("tool arguments are not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise MalformedModelResponse("tool arguments must decode to an object")
    return parsed


def parse_openai_tool_calls(payload: list[dict[str, Any]] | None) -> tuple[ModelToolCall, ...]:
    calls: list[ModelToolCall] = []
    for index, item in enumerate(payload or []):
        function = item.get("function") or {}
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise MalformedModelResponse("tool call is missing a function name")
        calls.append(
            ModelToolCall(
                id=str(item.get("id") or f"call-{index}"),
                name=name,
                arguments=parse_json_arguments(function.get("arguments", "{}")),
            )
        )
    return tuple(calls)


def anthropic_tools(tools: list[ModelTool]) -> list[dict[str, Any]]:
    return [
        {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
        for tool in tools
    ]


def gemini_tools(tools: list[ModelTool]) -> list[dict[str, Any]]:
    return [{"functionDeclarations": [
        {"name": tool.name, "description": tool.description, "parameters": tool.input_schema}
        for tool in tools
    ]}]
