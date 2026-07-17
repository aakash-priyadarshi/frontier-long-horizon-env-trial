"""Provider payload conversion with strict structured argument parsing."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any

from .errors import MalformedModelResponse
from .protocol import ModelMessage, ModelTool, ModelToolCall


_PROVIDER_TOOL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class ProviderToolNames:
    """Bidirectional aliases for provider-restricted function names."""

    canonical_to_provider: dict[str, str]
    provider_to_canonical: dict[str, str]

    def provider_name(self, name: str) -> str:
        return self.canonical_to_provider.get(name, name)

    def canonical_name(self, name: str) -> str:
        return self.provider_to_canonical.get(name, name)


def provider_tool_names(tools: list[ModelTool]) -> ProviderToolNames:
    """Create stable aliases without changing the provider-neutral tool protocol."""

    canonical_names = tuple(dict.fromkeys(tool.name for tool in tools))
    bases: dict[str, str] = {}
    for name in canonical_names:
        base = re.sub(r"[^A-Za-z0-9_-]", "_", name)
        if not base or not re.match(r"^[A-Za-z_]", base):
            base = f"tool_{base}"
        bases[name] = base
    base_counts = Counter(bases.values())
    unchanged_names = {name for name in canonical_names if _PROVIDER_TOOL_NAME.fullmatch(name)}

    canonical_to_provider: dict[str, str] = {}
    provider_to_canonical: dict[str, str] = {}
    for name in canonical_names:
        if name in unchanged_names:
            alias = name
        else:
            base = bases[name]
            if (
                len(base) <= 64
                and base_counts[base] == 1
                and base not in unchanged_names
                and base not in provider_to_canonical
            ):
                alias = base
            else:
                attempt = 0
                while True:
                    digest_input = name if attempt == 0 else f"{name}\0{attempt}"
                    suffix = f"_{sha256(digest_input.encode('utf-8')).hexdigest()[:12]}"
                    alias = f"{base[:64 - len(suffix)]}{suffix}"
                    if alias not in unchanged_names and alias not in provider_to_canonical:
                        break
                    attempt += 1
        canonical_to_provider[name] = alias
        provider_to_canonical[alias] = name
    return ProviderToolNames(canonical_to_provider, provider_to_canonical)


def openai_tools(
    tools: list[ModelTool], *, names: ProviderToolNames | None = None
) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": names.provider_name(tool.name) if names else tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


def openai_messages(
    messages: list[ModelMessage], *, include_reasoning: bool = False,
    names: ProviderToolNames | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        row: dict[str, Any] = {"role": message.role, "content": message.content or None}
        if message.tool_call_id:
            row["tool_call_id"] = message.tool_call_id
        if message.name:
            row["name"] = names.provider_name(message.name) if names else message.name
        if message.tool_calls:
            row["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": names.provider_name(call.name) if names else call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]
        if include_reasoning and message.reasoning:
            row["reasoning"] = message.reasoning
        result.append(row)
    return result


def ollama_messages(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """Convert messages to Ollama's native multi-turn tool format."""

    result: list[dict[str, Any]] = []
    for message in messages:
        row: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.reasoning:
            row["thinking"] = message.reasoning
        if message.tool_calls:
            row["tool_calls"] = [
                {
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                }
                for call in message.tool_calls
            ]
        if message.role == "tool" and message.name:
            row["tool_name"] = message.name
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


def parse_openai_tool_calls(
    payload: list[dict[str, Any]] | None, *, names: ProviderToolNames | None = None
) -> tuple[ModelToolCall, ...]:
    calls: list[ModelToolCall] = []
    for index, item in enumerate(payload or []):
        function = item.get("function") or {}
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise MalformedModelResponse("tool call is missing a function name")
        calls.append(
            ModelToolCall(
                id=str(item.get("id") or f"call-{index}"),
                name=names.canonical_name(name) if names else name,
                arguments=parse_json_arguments(function.get("arguments", "{}")),
            )
        )
    return tuple(calls)


def anthropic_tools(
    tools: list[ModelTool], *, names: ProviderToolNames | None = None
) -> list[dict[str, Any]]:
    return [
        {
            "name": names.provider_name(tool.name) if names else tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in tools
    ]


def gemini_tools(
    tools: list[ModelTool], *, names: ProviderToolNames | None = None
) -> list[dict[str, Any]]:
    return [{"functionDeclarations": [
        {
            "name": names.provider_name(tool.name) if names else tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        }
        for tool in tools
    ]}]
