"""Dependency-light OpenAI-compatible chat-completions adapter."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .configuration import RuntimeProviderSettings, base_url_for, secret_for, validate_provider_base_url
from .errors import ModelRunnerError, ProviderConfigurationError, ProviderTimeout
from .protocol import ModelMessage, ModelRequestConfig, ModelResponse, ModelTool
from .tool_conversion import ollama_messages, openai_messages, openai_tools, parse_openai_tool_calls
from .usage import approximate_tokens, estimate_cost


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _safe_ollama_http_error(exc: urllib.error.HTTPError) -> tuple[str, str]:
    """Map a small allowlist of local runtime failures without returning provider text."""

    try:
        raw = exc.read(32_768)
    except OSError:
        raw = b""
    lowered = raw.decode("utf-8", errors="ignore").lower()
    if any(marker in lowered for marker in ("out of memory", "cudamalloc failed", "failed to allocate")):
        return (
            "provider_out_of_memory",
            "Ollama could not fit the model and requested context in available memory",
        )
    if "context length" in lowered and any(marker in lowered for marker in ("exceed", "too large", "maximum")):
        return (
            "provider_context_limit",
            "Ollama rejected the requested context window",
        )
    return "provider_http_error", f"provider request failed with HTTP {exc.code}"


class OpenAICompatibleAdapter:
    provider = "openai-compatible"

    def __init__(
        self,
        *,
        provider: str = "openai-compatible",
        base_url: str | None = None,
        settings: RuntimeProviderSettings | None = None,
    ) -> None:
        self.provider = provider
        self._base_url = base_url
        self._settings = settings

    def _request(self, payload: dict[str, Any], config: ModelRequestConfig) -> tuple[dict[str, Any], str | None]:
        key = secret_for(self.provider, self._settings)
        if self.provider != "ollama" and not key:
            raise ProviderConfigurationError(f"{self.provider} credentials are not configured")
        base_url = validate_provider_base_url(
            self._base_url or base_url_for(self.provider, self._settings),
            local_only=self.provider == "ollama",
        )
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
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(request, timeout=config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8")), response.headers.get("x-request-id")
        except urllib.error.HTTPError as exc:
            retryable = exc.code in {408, 409, 429} or exc.code >= 500
            raise ModelRunnerError(
                f"provider request failed with HTTP {exc.code}",
                code="provider_authentication_failed" if exc.code in {401, 403} else "provider_http_error",
                retryable=retryable,
            ) from exc
        except TimeoutError as exc:
            raise ProviderTimeout() from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ProviderTimeout() from exc
            raise ModelRunnerError("provider request failed", code="provider_unreachable", retryable=True) from exc

    def _request_ollama(self, payload: dict[str, Any], config: ModelRequestConfig) -> dict[str, Any]:
        base_url = validate_provider_base_url(
            self._base_url or base_url_for("ollama", self._settings),
            local_only=True,
        )
        parsed = urllib.parse.urlsplit(base_url)
        path = parsed.path.rstrip("/")
        if path.endswith("/v1"):
            path = path[:-3]
        url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path + "/api/chat", "", ""))
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(request, timeout=config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            code, message = _safe_ollama_http_error(exc)
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

    async def _complete_ollama(
        self,
        *,
        messages: list[ModelMessage],
        tools: list[ModelTool],
        config: ModelRequestConfig,
    ) -> ModelResponse:
        options: dict[str, Any] = {"num_predict": config.max_output_tokens}
        if config.context_window is not None:
            options["num_ctx"] = config.context_window
        if config.temperature is not None:
            options["temperature"] = 0 if config.deterministic else config.temperature
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": ollama_messages(messages),
            "tools": openai_tools(tools),
            "stream": False,
            "options": options,
        }
        if config.reasoning_effort:
            payload["think"] = False if config.reasoning_effort == "none" else config.reasoning_effort
        started = time.perf_counter()
        body = await asyncio.to_thread(self._request_ollama, payload, config)
        latency_ms = (time.perf_counter() - started) * 1000
        message = body.get("message")
        if not isinstance(message, dict):
            raise ModelRunnerError("provider returned no message", code="malformed_model_response")
        reasoning = str(message.get("thinking") or "")
        tool_calls = parse_openai_tool_calls(message.get("tool_calls"))
        input_tokens = int(body.get("prompt_eval_count") or 0)
        output_tokens = int(body.get("eval_count") or 0)
        return ModelResponse(
            text=str(message.get("content") or ""),
            reasoning=reasoning,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=approximate_tokens(reasoning),
            latency_ms=latency_ms,
            estimated_cost=estimate_cost(
                input_tokens=input_tokens, output_tokens=output_tokens, config=config
            ),
            finish_reason="tool_calls" if tool_calls else str(body.get("done_reason") or "stop"),
        )

    async def complete(
        self,
        *,
        messages: list[ModelMessage],
        tools: list[ModelTool],
        config: ModelRequestConfig,
    ) -> ModelResponse:
        if self.provider == "ollama":
            return await self._complete_ollama(messages=messages, tools=tools, config=config)
        payload: dict[str, Any] = {
            "model": config.model,
            # Ollama thinking models require their private reasoning field to
            # be replayed with the assistant tool call on subsequent turns.
            # Hosted OpenAI-compatible APIs do not receive this extension.
            "messages": openai_messages(
                messages, include_reasoning=self.provider == "ollama"
            ),
            "tools": openai_tools(tools),
            "tool_choice": (
                {"type": "function", "function": {"name": config.required_tool}}
                if config.required_tool
                else "auto"
            ),
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
            reasoning=str(message.get("reasoning") or ""),
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
