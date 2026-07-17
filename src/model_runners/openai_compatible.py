"""Dependency-light OpenAI Responses and compatible chat-completions adapter."""

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
from .ollama_support import support_for_model, supports_reasoning_effort
from .protocol import ModelMessage, ModelRequestConfig, ModelResponse, ModelTool, ModelToolCall
from .tool_conversion import (
    ollama_messages,
    openai_messages,
    openai_tools,
    parse_openai_tool_calls,
    parse_json_arguments,
    provider_tool_names,
)
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

    @staticmethod
    def _uses_current_openai_chat_parameters(model: str) -> bool:
        normalized = model.lower()
        return normalized.startswith(("gpt-5", "o1", "o3", "o4"))

    def _uses_openai_responses_api(self, model: str) -> bool:
        """Use OpenAI's current native tool protocol only for the GPT-5.6 family.

        Other OpenAI-compatible endpoints may expose only Chat Completions, so the
        provider and exact model family are both intentionally required.
        """

        return self.provider == "openai-compatible" and model.lower().startswith("gpt-5.6")

    @staticmethod
    def _safe_hosted_http_error(exc: urllib.error.HTTPError) -> tuple[str, str]:
        """Classify a bounded allowlist of provider errors without echoing provider text."""

        try:
            raw = exc.read(32_768)
        except (OSError, AttributeError):
            raw = b""
        code = ""
        param = ""
        try:
            body = json.loads(raw.decode("utf-8"))
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                code = str(error.get("code") or "").lower()
                param = str(error.get("param") or "").lower()
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        if exc.code in {401, 403}:
            return "provider_authentication_failed", "provider authentication failed"
        if exc.code == 429:
            if code in {"insufficient_quota", "billing_hard_limit_reached"}:
                return "provider_quota_exceeded", "provider quota is unavailable"
            return "provider_rate_limited", "provider rate limit was reached"
        if exc.code == 404 and code in {"model_not_found", "not_found"}:
            return "provider_model_not_found", "provider model was not found or is not available to this key"
        if exc.code == 400 and (code in {"unsupported_parameter", "invalid_parameter"} or param):
            return "provider_request_incompatible", "provider rejected a request parameter for this model"
        if exc.code in {400, 404, 409, 422}:
            return "provider_request_rejected", f"provider rejected the request with HTTP {exc.code}"
        return "provider_http_error", f"provider request failed with HTTP {exc.code}"

    def _request_at_path(
        self,
        payload: dict[str, Any],
        config: ModelRequestConfig,
        path: str,
    ) -> tuple[dict[str, Any], str | None]:
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
            base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(request, timeout=config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8")), response.headers.get("x-request-id")
        except urllib.error.HTTPError as exc:
            code, message = self._safe_hosted_http_error(exc)
            retryable = exc.code in {408, 409, 429} or exc.code >= 500
            raise ModelRunnerError(
                message,
                code=code,
                retryable=retryable,
            ) from exc
        except TimeoutError as exc:
            raise ProviderTimeout() from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ProviderTimeout() from exc
            raise ModelRunnerError("provider request failed", code="provider_unreachable", retryable=True) from exc

    def _request(self, payload: dict[str, Any], config: ModelRequestConfig) -> tuple[dict[str, Any], str | None]:
        return self._request_at_path(payload, config, "/chat/completions")

    def _request_responses(
        self, payload: dict[str, Any], config: ModelRequestConfig
    ) -> tuple[dict[str, Any], str | None]:
        return self._request_at_path(payload, config, "/responses")

    @staticmethod
    def _responses_input(messages: list[ModelMessage], tool_names: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                if not message.tool_call_id:
                    raise ModelRunnerError("tool result is missing its call id", code="malformed_model_request")
                items.append({
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": message.content,
                })
                continue
            if message.role == "assistant" and message.reasoning:
                try:
                    continuation = json.loads(message.reasoning)
                except json.JSONDecodeError as exc:
                    raise ModelRunnerError(
                        "provider continuation is malformed", code="malformed_model_request"
                    ) from exc
                if not isinstance(continuation, list) or not all(
                    isinstance(item, dict)
                    and item.get("type") == "reasoning"
                    and isinstance(item.get("encrypted_content"), str)
                    and len(item["encrypted_content"]) <= 10_000_000
                    for item in continuation
                ):
                    raise ModelRunnerError(
                        "provider continuation is malformed", code="malformed_model_request"
                    )
                items.extend(continuation)
            role = "developer" if message.role == "system" else message.role
            if message.content:
                items.append({"role": role, "content": message.content})
            for call in message.tool_calls:
                items.append({
                    "type": "function_call",
                    "call_id": call.id,
                    "name": tool_names.provider_name(call.name),
                    "arguments": json.dumps(call.arguments),
                })
        return items

    async def _complete_responses(
        self,
        *,
        messages: list[ModelMessage],
        tools: list[ModelTool],
        config: ModelRequestConfig,
    ) -> ModelResponse:
        tool_names = provider_tool_names(tools)
        payload: dict[str, Any] = {
            "model": config.model,
            "input": self._responses_input(messages, tool_names),
            "tools": [
                {
                    "type": "function",
                    "name": tool_names.provider_name(tool.name),
                    "description": tool.description,
                    "parameters": tool.input_schema,
                    # The environment schemas intentionally permit optional fields
                    # and therefore do not satisfy OpenAI strict-schema constraints.
                    "strict": False,
                }
                for tool in tools
            ],
            "tool_choice": (
                {"type": "function", "name": tool_names.provider_name(config.required_tool)}
                if config.required_tool
                else "auto"
            ),
            "max_output_tokens": config.max_output_tokens,
            "parallel_tool_calls": False,
            # Evaluation prompts and outputs must not be retained provider-side.
            "store": False,
        }
        payload["reasoning"] = {"context": "all_turns"}
        if config.reasoning_effort:
            payload["reasoning"]["effort"] = config.reasoning_effort
        started = time.perf_counter()
        body, header_request_id = await asyncio.to_thread(self._request_responses, payload, config)
        latency_ms = (time.perf_counter() - started) * 1000
        output = body.get("output")
        if not isinstance(output, list):
            raise ModelRunnerError("provider returned malformed output", code="malformed_model_response")
        text_parts: list[str] = []
        calls: list[ModelToolCall] = []
        continuation: list[dict[str, Any]] = []
        for index, item in enumerate(output):
            if not isinstance(item, dict):
                raise ModelRunnerError("provider returned malformed output", code="malformed_model_response")
            if item.get("type") == "reasoning":
                encrypted_content = item.get("encrypted_content")
                if isinstance(encrypted_content, str) and len(encrypted_content) <= 10_000_000:
                    reasoning_item: dict[str, Any] = {
                        "type": "reasoning",
                        "encrypted_content": encrypted_content,
                        "summary": [],
                    }
                    if isinstance(item.get("id"), str) and len(item["id"]) <= 512:
                        reasoning_item["id"] = item["id"]
                    continuation.append(reasoning_item)
            elif item.get("type") == "function_call":
                name = item.get("name")
                if not isinstance(name, str) or not name:
                    raise ModelRunnerError("tool call is missing a function name", code="malformed_model_response")
                calls.append(ModelToolCall(
                    id=str(item.get("call_id") or item.get("id") or f"call-{index}"),
                    name=tool_names.canonical_name(name),
                    arguments=parse_json_arguments(item.get("arguments", "{}")),
                ))
            elif item.get("type") == "message":
                content = item.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "output_text":
                            text_parts.append(str(part.get("text") or ""))
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        input_details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
        output_details = usage.get("output_tokens_details") if isinstance(usage.get("output_tokens_details"), dict) else {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        incomplete = body.get("incomplete_details") if isinstance(body.get("incomplete_details"), dict) else {}
        finish_reason = "tool_calls" if calls else (
            "max_tokens" if incomplete.get("reason") == "max_output_tokens" else str(body.get("status") or "stop")
        )
        return ModelResponse(
            text="".join(text_parts),
            # Opaque stateless continuation, held only in the active runner's
            # in-memory message list and never included in public records.
            reasoning=json.dumps(continuation, separators=(",", ":")) if continuation else "",
            tool_calls=tuple(calls),
            provider_request_id=str(body.get("id") or header_request_id or "") or None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=int(input_details.get("cached_tokens") or 0),
            reasoning_tokens=int(output_details.get("reasoning_tokens") or 0),
            latency_ms=latency_ms,
            estimated_cost=estimate_cost(
                input_tokens=input_tokens, output_tokens=output_tokens, config=config
            ),
            finish_reason=finish_reason,
        )

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
        support = support_for_model(config.model)
        if config.reasoning_effort and (support is None or supports_reasoning_effort(config.model)):
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
        if self._uses_openai_responses_api(config.model):
            return await self._complete_responses(messages=messages, tools=tools, config=config)
        tool_names = provider_tool_names(tools)
        current_openai_parameters = self._uses_current_openai_chat_parameters(config.model)
        payload: dict[str, Any] = {
            "model": config.model,
            # Ollama thinking models require their private reasoning field to
            # be replayed with the assistant tool call on subsequent turns.
            # Hosted OpenAI-compatible APIs do not receive this extension.
            "messages": openai_messages(
                messages,
                include_reasoning=self.provider == "ollama",
                names=tool_names,
            ),
            "tools": openai_tools(tools, names=tool_names),
            "tool_choice": (
                {
                    "type": "function",
                    "function": {"name": tool_names.provider_name(config.required_tool)},
                }
                if config.required_tool
                else "auto"
            ),
        }
        token_limit_field = "max_completion_tokens" if current_openai_parameters else "max_tokens"
        payload[token_limit_field] = config.max_output_tokens
        if config.temperature is not None and not (
            current_openai_parameters and config.reasoning_effort != "none"
        ):
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
            tool_calls=parse_openai_tool_calls(message.get("tool_calls"), names=tool_names),
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
