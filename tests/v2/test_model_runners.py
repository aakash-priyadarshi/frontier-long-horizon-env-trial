from __future__ import annotations

import asyncio
import json
import socket

import pytest

from evaluation_service.runner import PROMPT_VERSION, SYSTEM_PROMPT, public_tools
from model_runners.configuration import configured, custom_headers_for, validate_provider_base_url
from model_runners.errors import MalformedModelResponse, ProviderConfigurationError
from model_runners.openai_compatible import OpenAICompatibleAdapter
from model_runners.protocol import ModelMessage, ModelRequestConfig
from model_runners.registry import ProviderRegistry
from model_runners.scripted import ScriptedAdapter
from model_runners.tool_conversion import (
    anthropic_tools,
    gemini_tools,
    openai_messages,
    openai_tools,
    parse_json_arguments,
    parse_openai_tool_calls,
)
from model_runners.usage import approximate_tokens, estimate_cost
from training_adapters.protocol import ALLOWED_TOOLS


def test_registry_lists_safe_provider_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "top-secret-value")
    providers = ProviderRegistry().list()
    anthropic = next(item for item in providers if item["provider"] == "anthropic")
    assert anthropic["configured"] is True
    assert "top-secret-value" not in json.dumps(providers)
    assert {item["provider"] for item in providers} == {
        "scripted", "openai-compatible", "anthropic", "gemini", "ollama"
    }


def test_missing_credentials_disable_optional_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert configured("anthropic") is False
    assert configured("scripted") is True
    assert configured("ollama") is True


def test_optional_headers_stay_server_side(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_EXTRA_HEADERS_JSON", '{"HTTP-Referer":"https://local.example"}')
    assert custom_headers_for("openai-compatible") == {"HTTP-Referer": "https://local.example"}
    assert custom_headers_for("anthropic") == {}


def test_exact_twelve_public_tool_schemas() -> None:
    tools = public_tools()
    assert len(tools) == 12
    assert tuple(tool.name for tool in tools) == ALLOWED_TOOLS
    for tool in tools:
        assert tool.input_schema["type"] == "object"
        assert tool.input_schema["additionalProperties"] is False


def test_provider_tool_conversions() -> None:
    tools = public_tools()
    assert len(openai_tools(tools)) == 12
    assert len(anthropic_tools(tools)) == 12
    assert len(gemini_tools(tools)[0]["functionDeclarations"]) == 12


def test_openai_message_conversion_preserves_tool_result() -> None:
    payload = openai_messages([ModelMessage("tool", "{}", tool_call_id="call-1", name="release.status")])
    assert payload == [{"role": "tool", "content": "{}", "tool_call_id": "call-1", "name": "release.status"}]


def test_tool_call_parser_requires_object_arguments() -> None:
    with pytest.raises(MalformedModelResponse):
        parse_json_arguments("[]")
    with pytest.raises(MalformedModelResponse):
        parse_json_arguments("{")
    calls = parse_openai_tool_calls([{"id": "x", "function": {"name": "release.status", "arguments": "{}"}}])
    assert calls[0].name == "release.status"
    assert calls[0].arguments == {}


def test_usage_and_price_accounting() -> None:
    config = ModelRequestConfig(
        model="test", input_token_price_per_million=2.0,
        output_token_price_per_million=10.0,
    )
    assert estimate_cost(input_tokens=1_000_000, output_tokens=500_000, config=config) == 7.0
    assert approximate_tokens("abcdefgh") == 2


def test_base_url_policy_allows_https_and_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 0))])
    assert validate_provider_base_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("8.8.8.8", 0))])
    assert validate_provider_base_url("https://provider.example/v1") == "https://provider.example/v1"


def test_base_url_policy_rejects_metadata_and_public_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("169.254.169.254", 0))])
    with pytest.raises(ProviderConfigurationError):
        validate_provider_base_url("http://169.254.169.254/latest")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("8.8.8.8", 0))])
    with pytest.raises(ProviderConfigurationError):
        validate_provider_base_url("http://provider.example/v1")


@pytest.mark.asyncio
async def test_scripted_adapter_is_deterministic() -> None:
    adapter = ScriptedAdapter()
    config = ModelRequestConfig(model="scripted-valid")
    first = await adapter.complete(messages=[], tools=public_tools(), config=config)
    second = await adapter.complete(messages=[], tools=public_tools(), config=config)
    assert first.tool_calls[0].name == "release.status"
    assert second.tool_calls[0].name == "telemetry.logs"
    assert first.estimated_cost == 0.0


@pytest.mark.asyncio
async def test_openai_adapter_response_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = OpenAICompatibleAdapter()
    monkeypatch.setattr(
        adapter,
        "_request",
        lambda payload, config: (
            {
                "id": "req-1",
                "choices": [{"message": {"content": "", "tool_calls": [{"id": "c1", "function": {"name": "release.status", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "prompt_tokens_details": {"cached_tokens": 2}, "completion_tokens_details": {"reasoning_tokens": 1}},
            },
            None,
        ),
    )
    response = await adapter.complete(messages=[ModelMessage("user", "hello")], tools=public_tools(), config=ModelRequestConfig(model="test"))
    assert response.provider_request_id == "req-1"
    assert response.tool_calls[0].name == "release.status"
    assert (response.input_tokens, response.output_tokens, response.cached_tokens, response.reasoning_tokens) == (10, 4, 2, 1)


def test_prompt_is_versioned_and_does_not_name_privileged_details() -> None:
    assert PROMPT_VERSION.startswith("frontier-incident-agent-v2")
    lowered = SYSTEM_PROMPT.lower()
    for forbidden in ("member a", "member b", "profile derivation", "strict verifier predicate", "gold repair"):
        assert forbidden not in lowered
    assert "twelve tools" in lowered
    assert "investigate" in lowered
