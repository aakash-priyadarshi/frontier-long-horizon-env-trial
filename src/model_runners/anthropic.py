"""Anthropic Messages API adapter with native tool conversion."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import Any

from .configuration import RuntimeProviderSettings, secret_for
from .errors import ModelRunnerError, ProviderConfigurationError, ProviderTimeout
from .protocol import ModelMessage, ModelRequestConfig, ModelResponse, ModelTool, ModelToolCall
from .tool_conversion import anthropic_tools, provider_tool_names
from .usage import estimate_cost


class AnthropicAdapter:
    provider = "anthropic"

    # These adaptive-thinking models reject any non-default sampling value,
    # including temperature=0, with HTTP 400. Keep this model-specific instead of
    # disabling temperature for older Claude models that still support it.
    _PROVIDER_MANAGED_SAMPLING_PREFIXES = (
        "claude-fable-5",
        "claude-mythos-5",
        "claude-mythos-preview",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-5",
    )

    def __init__(self, *, settings: RuntimeProviderSettings | None = None) -> None:
        self._settings = settings

    @classmethod
    def _uses_provider_managed_sampling(cls, model: str) -> bool:
        return model.lower().startswith(cls._PROVIDER_MANAGED_SAMPLING_PREFIXES)

    @staticmethod
    def _safe_http_error(exc: urllib.error.HTTPError) -> tuple[str, str]:
        """Classify Anthropic failures without exposing response text or headers."""

        try:
            raw = exc.read(32_768)
        except (OSError, AttributeError):
            raw = b""
        error_type = ""
        try:
            body = json.loads(raw.decode("utf-8"))
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                error_type = str(error.get("type") or "").lower()
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        if exc.code in {401, 403} or error_type in {"authentication_error", "permission_error"}:
            return "provider_authentication_failed", "provider authentication failed"
        if exc.code == 429 or error_type == "rate_limit_error":
            return "provider_rate_limited", "provider rate limit was reached"
        if exc.code == 404 or error_type == "not_found_error":
            return "provider_model_not_found", "provider model was not found or is not available to this key"
        if exc.code in {400, 409, 422} or error_type == "invalid_request_error":
            return "provider_request_incompatible", "provider rejected an Anthropic request parameter or conversation block"
        return "provider_http_error", f"provider request failed with HTTP {exc.code}"

    @staticmethod
    def _continuation_blocks(reasoning: str) -> list[dict[str, str]]:
        """Decode bounded Anthropic thinking blocks kept only in runner memory."""

        try:
            continuation = json.loads(reasoning)
        except json.JSONDecodeError as exc:
            raise ModelRunnerError(
                "provider continuation is malformed", code="malformed_model_request"
            ) from exc
        if not isinstance(continuation, dict) or continuation.get("provider") != "anthropic":
            raise ModelRunnerError("provider continuation is malformed", code="malformed_model_request")
        raw_blocks = continuation.get("blocks")
        if not isinstance(raw_blocks, list) or len(raw_blocks) > 64:
            raise ModelRunnerError("provider continuation is malformed", code="malformed_model_request")
        blocks: list[dict[str, str]] = []
        for block in raw_blocks:
            if not isinstance(block, dict):
                raise ModelRunnerError("provider continuation is malformed", code="malformed_model_request")
            block_type = block.get("type")
            if block_type == "thinking":
                thinking = block.get("thinking")
                signature = block.get("signature")
                if not isinstance(thinking, str) or not isinstance(signature, str):
                    raise ModelRunnerError("provider continuation is malformed", code="malformed_model_request")
                if len(thinking) > 2_000_000 or len(signature) > 10_000_000:
                    raise ModelRunnerError("provider continuation is too large", code="malformed_model_request")
                blocks.append({"type": "thinking", "thinking": thinking, "signature": signature})
            elif block_type == "redacted_thinking":
                data = block.get("data")
                if not isinstance(data, str) or len(data) > 10_000_000:
                    raise ModelRunnerError("provider continuation is malformed", code="malformed_model_request")
                blocks.append({"type": "redacted_thinking", "data": data})
            else:
                raise ModelRunnerError("provider continuation is malformed", code="malformed_model_request")
        return blocks

    def _request(self, payload: dict[str, Any], config: ModelRequestConfig) -> dict[str, Any]:
        key = secret_for(self.provider, self._settings)
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
            code, message = self._safe_http_error(exc)
            raise ModelRunnerError(
                message,
                code=code,
                retryable=exc.code in {408, 409, 429} or exc.code >= 500,
            ) from exc
        except TimeoutError as exc:
            raise ProviderTimeout() from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ProviderTimeout() from exc
            raise ModelRunnerError("provider request failed", code="provider_unreachable", retryable=True) from exc

    async def complete(self, *, messages: list[ModelMessage], tools: list[ModelTool], config: ModelRequestConfig) -> ModelResponse:
        tool_names = provider_tool_names(tools)
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        converted: list[dict[str, Any]] = []
        pending_tool_results: list[dict[str, Any]] = []

        def flush_tool_results() -> None:
            if pending_tool_results:
                converted.append({"role": "user", "content": list(pending_tool_results)})
                pending_tool_results.clear()

        for message in messages:
            if message.role == "system":
                continue
            if message.role == "tool":
                if not message.tool_call_id:
                    raise ModelRunnerError("tool result is missing its call id", code="malformed_model_request")
                pending_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.content,
                })
            elif message.tool_calls:
                flush_tool_results()
                blocks: list[dict[str, Any]] = []
                if message.reasoning:
                    blocks.extend(self._continuation_blocks(message.reasoning))
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                blocks.extend({"type": "tool_use", "id": call.id, "name": tool_names.provider_name(call.name), "input": call.arguments} for call in message.tool_calls)
                converted.append({"role": "assistant", "content": blocks})
            else:
                flush_tool_results()
                if message.role == "assistant" and message.reasoning:
                    blocks = self._continuation_blocks(message.reasoning)
                    if message.content:
                        blocks.append({"type": "text", "text": message.content})
                    converted.append({"role": "assistant", "content": blocks})
                else:
                    converted.append({"role": message.role, "content": message.content})
        flush_tool_results()
        payload: dict[str, Any] = {
            "model": config.model,
            "system": system,
            "messages": converted,
            "tools": anthropic_tools(tools, names=tool_names),
            "max_tokens": config.max_output_tokens,
        }
        if config.required_tool:
            payload["tool_choice"] = {"type": "tool", "name": tool_names.provider_name(config.required_tool)}
        else:
            # The evaluation executes one environment transition at a time. This
            # Anthropic-native control prevents parallel calls while retaining auto
            # tool selection on every model turn.
            payload["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
        if config.temperature is not None and not self._uses_provider_managed_sampling(config.model):
            payload["temperature"] = 0 if config.deterministic else config.temperature
        started = time.perf_counter()
        body = await asyncio.to_thread(self._request, payload, config)
        latency = (time.perf_counter() - started) * 1000
        calls: list[ModelToolCall] = []
        texts: list[str] = []
        continuation: list[dict[str, str]] = []
        for block in body.get("content") or []:
            if block.get("type") == "text":
                texts.append(str(block.get("text") or ""))
            elif block.get("type") == "tool_use":
                calls.append(ModelToolCall(str(block.get("id")), tool_names.canonical_name(str(block.get("name"))), dict(block.get("input") or {})))
            elif block.get("type") == "thinking":
                thinking = block.get("thinking")
                signature = block.get("signature")
                if not isinstance(thinking, str) or not isinstance(signature, str):
                    raise ModelRunnerError("provider returned malformed thinking state", code="malformed_model_response")
                if len(thinking) > 2_000_000 or len(signature) > 10_000_000:
                    raise ModelRunnerError("provider returned oversized thinking state", code="malformed_model_response")
                continuation.append({"type": "thinking", "thinking": thinking, "signature": signature})
            elif block.get("type") == "redacted_thinking":
                data = block.get("data")
                if not isinstance(data, str) or len(data) > 10_000_000:
                    raise ModelRunnerError("provider returned malformed thinking state", code="malformed_model_response")
                continuation.append({"type": "redacted_thinking", "data": data})
        usage = body.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        return ModelResponse(
            text="\n".join(texts),
            reasoning=(
                json.dumps({"provider": "anthropic", "blocks": continuation}, separators=(",", ":"))
                if continuation else ""
            ),
            tool_calls=tuple(calls), provider_request_id=body.get("id"),
            input_tokens=input_tokens, output_tokens=output_tokens,
            cached_tokens=int(usage.get("cache_read_input_tokens") or 0), latency_ms=latency,
            estimated_cost=estimate_cost(input_tokens=input_tokens, output_tokens=output_tokens, config=config),
            finish_reason=body.get("stop_reason"),
        )
