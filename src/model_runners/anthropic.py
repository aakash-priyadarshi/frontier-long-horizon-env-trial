"""Anthropic Messages API adapter with native tool conversion."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import Any

from .configuration import secret_for
from .errors import ModelRunnerError, ProviderConfigurationError
from .protocol import ModelMessage, ModelRequestConfig, ModelResponse, ModelTool, ModelToolCall
from .tool_conversion import anthropic_tools
from .usage import estimate_cost


class AnthropicAdapter:
    provider = "anthropic"

    def _request(self, payload: dict[str, Any], config: ModelRequestConfig) -> dict[str, Any]:
        key = secret_for(self.provider)
        if not key:
            raise ProviderConfigurationError("Anthropic credentials are not configured")
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ModelRunnerError(
                f"provider request failed with HTTP {exc.code}",
                retryable=exc.code in {408, 409, 429} or exc.code >= 500,
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ModelRunnerError("provider request failed", retryable=True) from exc

    async def complete(self, *, messages: list[ModelMessage], tools: list[ModelTool], config: ModelRequestConfig) -> ModelResponse:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        converted: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                continue
            if message.role == "tool":
                converted.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": message.tool_call_id, "content": message.content}]})
            elif message.tool_calls:
                blocks: list[dict[str, Any]] = []
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                blocks.extend({"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments} for call in message.tool_calls)
                converted.append({"role": "assistant", "content": blocks})
            else:
                converted.append({"role": message.role, "content": message.content})
        payload = {"model": config.model, "system": system, "messages": converted, "tools": anthropic_tools(tools), "max_tokens": config.max_output_tokens}
        if config.temperature is not None:
            payload["temperature"] = 0 if config.deterministic else config.temperature
        started = time.perf_counter()
        body = await asyncio.to_thread(self._request, payload, config)
        latency = (time.perf_counter() - started) * 1000
        calls: list[ModelToolCall] = []
        texts: list[str] = []
        for block in body.get("content") or []:
            if block.get("type") == "text":
                texts.append(str(block.get("text") or ""))
            elif block.get("type") == "tool_use":
                calls.append(ModelToolCall(str(block.get("id")), str(block.get("name")), dict(block.get("input") or {})))
        usage = body.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        return ModelResponse(
            text="\n".join(texts), tool_calls=tuple(calls), provider_request_id=body.get("id"),
            input_tokens=input_tokens, output_tokens=output_tokens,
            cached_tokens=int(usage.get("cache_read_input_tokens") or 0), latency_ms=latency,
            estimated_cost=estimate_cost(input_tokens=input_tokens, output_tokens=output_tokens, config=config),
            finish_reason=body.get("stop_reason"),
        )
