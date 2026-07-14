"""Gemini generateContent adapter with native function-call conversion."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .configuration import RuntimeProviderSettings, secret_for
from .errors import ModelRunnerError, ProviderConfigurationError, ProviderTimeout
from .protocol import ModelMessage, ModelRequestConfig, ModelResponse, ModelTool, ModelToolCall
from .tool_conversion import gemini_tools
from .usage import estimate_cost


class GeminiAdapter:
    provider = "gemini"

    def __init__(self, *, settings: RuntimeProviderSettings | None = None) -> None:
        self._settings = settings

    def _request(self, payload: dict[str, Any], config: ModelRequestConfig) -> dict[str, Any]:
        key = secret_for(self.provider, self._settings)
        if not key:
            raise ProviderConfigurationError("Gemini credentials are not configured")
        model = urllib.parse.quote(config.model, safe="")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={urllib.parse.quote(key)}"
        request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"content-type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ModelRunnerError(
                f"provider request failed with HTTP {exc.code}",
                code="provider_authentication_failed" if exc.code in {401, 403} else "provider_http_error",
                retryable=exc.code in {408, 429} or exc.code >= 500,
            ) from exc
        except TimeoutError as exc:
            raise ProviderTimeout() from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ProviderTimeout() from exc
            raise ModelRunnerError("provider request failed", code="provider_unreachable", retryable=True) from exc

    async def complete(self, *, messages: list[ModelMessage], tools: list[ModelTool], config: ModelRequestConfig) -> ModelResponse:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        contents: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                continue
            role = "model" if message.role == "assistant" else "user"
            parts: list[dict[str, Any]] = []
            if message.content:
                if message.role == "tool":
                    parts.append({"functionResponse": {"name": message.name or "tool", "response": {"result": message.content}}})
                else:
                    parts.append({"text": message.content})
            parts.extend({"functionCall": {"name": call.name, "args": call.arguments}} for call in message.tool_calls)
            contents.append({"role": role, "parts": parts})
        generation: dict[str, Any] = {"maxOutputTokens": config.max_output_tokens}
        if config.temperature is not None:
            generation["temperature"] = 0 if config.deterministic else config.temperature
        payload = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents, "tools": gemini_tools(tools), "generationConfig": generation}
        if config.required_tool:
            payload["toolConfig"] = {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": [config.required_tool],
                }
            }
        started = time.perf_counter()
        body = await asyncio.to_thread(self._request, payload, config)
        latency = (time.perf_counter() - started) * 1000
        candidates = body.get("candidates") or []
        if not candidates:
            raise ModelRunnerError("provider returned no candidates", code="malformed_model_response")
        candidate = candidates[0]
        calls: list[ModelToolCall] = []
        texts: list[str] = []
        for index, part in enumerate((candidate.get("content") or {}).get("parts") or []):
            if "text" in part:
                texts.append(str(part["text"]))
            if "functionCall" in part:
                call = part["functionCall"]
                calls.append(ModelToolCall(f"gemini-{index}", str(call.get("name")), dict(call.get("args") or {})))
        usage = body.get("usageMetadata") or {}
        input_tokens = int(usage.get("promptTokenCount") or 0)
        output_tokens = int(usage.get("candidatesTokenCount") or 0)
        return ModelResponse(
            text="\n".join(texts), tool_calls=tuple(calls), provider_request_id=body.get("responseId"),
            input_tokens=input_tokens, output_tokens=output_tokens,
            cached_tokens=int(usage.get("cachedContentTokenCount") or 0),
            reasoning_tokens=int(usage.get("thoughtsTokenCount") or 0), latency_ms=latency,
            estimated_cost=estimate_cost(input_tokens=input_tokens, output_tokens=output_tokens, config=config),
            finish_reason=candidate.get("finishReason"),
        )
