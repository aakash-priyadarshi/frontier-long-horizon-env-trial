"""Dependency-light OpenAI-compatible chat-completions adapter."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import Any

from .configuration import base_url_for, secret_for, validate_provider_base_url
from .errors import ModelRunnerError, ProviderConfigurationError
from .protocol import ModelMessage, ModelRequestConfig, ModelResponse, ModelTool
from .tool_conversion import openai_messages, openai_tools, parse_openai_tool_calls
from .usage import estimate_cost


class OpenAICompatibleAdapter:
    provider = "openai-compatible"

    def __init__(self, *, provider: str = "openai-compatible", base_url: str | None = None) -> None:
        self.provider = provider
        self._base_url = base_url

    def _request(self, payload: dict[str, Any], config: ModelRequestConfig) -> tuple[dict[str, Any], str | None]:
        key = secret_for(self.provider)
        if self.provider != "ollama" and not key:
            raise ProviderConfigurationError(f"{self.provider} credentials are not configured")
        base_url = validate_provider_base_url(self._base_url or base_url_for(self.provider))
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        headers.update(config.custom_headers)
        request = urllib.request.Request(
            base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8")), response.headers.get("x-request-id")
        except urllib.error.HTTPError as exc:
            retryable = exc.code in {408, 409, 429} or exc.code >= 500
            raise ModelRunnerError(
                f"provider request failed with HTTP {exc.code}",
                code="provider_http_error",
                retryable=retryable,
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ModelRunnerError("provider request failed", retryable=True) from exc

    async def complete(
        self,
        *,
        messages: list[ModelMessage],
        tools: list[ModelTool],
        config: ModelRequestConfig,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": openai_messages(messages),
            "tools": openai_tools(tools),
            "tool_choice": "auto",
            "max_tokens": config.max_output_tokens,
        }
        if config.temperature is not None:
            payload["temperature"] = 0 if config.deterministic else config.temperature
        if config.reasoning_effort:
            payload["reasoning_effort"] = config.reasoning_effort
        started = time.perf_counter()
        body, header_request_id = await asyncio.to_thread(self._request, payload, config)
        latency_ms = (time.perf_counter() - started) * 1000
        choices = body.get("choices") or []
        if not choices:
            raise ModelRunnerError("provider returned no choices", code="malformed_model_response")
        choice = choices[0]
        message = choice.get("message") or {}
        usage = body.get("usage") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        return ModelResponse(
            text=str(message.get("content") or ""),
            tool_calls=parse_openai_tool_calls(message.get("tool_calls")),
            provider_request_id=str(body.get("id") or header_request_id or "") or None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=int(prompt_details.get("cached_tokens") or 0),
            reasoning_tokens=int(completion_details.get("reasoning_tokens") or 0),
            latency_ms=latency_ms,
            estimated_cost=estimate_cost(
                input_tokens=input_tokens, output_tokens=output_tokens, config=config
            ),
            finish_reason=choice.get("finish_reason"),
        )
