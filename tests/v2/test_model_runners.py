from __future__ import annotations

import asyncio
import json
import socket
import urllib.error
from concurrent.futures import ThreadPoolExecutor

import pytest

from evaluation_service.runner import PROMPT_VERSION, SYSTEM_PROMPT, public_tools
from model_runners.configuration import RuntimeProviderSettings, configured, custom_headers_for, validate_provider_base_url
from model_runners.errors import MalformedModelResponse, ModelRunnerError, ProviderConfigurationError
from model_runners.openai_compatible import OpenAICompatibleAdapter
from model_runners.protocol import ModelMessage, ModelRequestConfig, ModelResponse, ModelToolCall
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


def test_runtime_credentials_prefer_session_then_fall_back_to_environment() -> None:
    environment = {"ANTHROPIC_API_KEY": "environment-secret"}
    settings = RuntimeProviderSettings(environment)
    registry = ProviderRegistry(settings)
    assert registry.status("anthropic")["credential"]["source"] == "environment"
    registry.set_session_configuration("anthropic", credential="session-secret")
    assert settings.secret_for("anthropic") == "session-secret"
    assert registry.status("anthropic")["credential"]["source"] == "session"
    public = registry.clear_session_credential("anthropic")
    assert settings.secret_for("anthropic") == "environment-secret"
    assert public["credential"]["source"] == "environment"
    assert "session-secret" not in json.dumps(public)
    assert "environment-secret" not in json.dumps(public)


def test_session_replacement_is_atomic_and_drops_the_previous_key() -> None:
    settings = RuntimeProviderSettings({})
    settings.update_session(
        "openai-compatible",
        credential="first-session-secret",
        update_credential=True,
        base_url="https://api.openai.com/v1",
        update_base_url=True,
    )
    settings.update_session(
        "openai-compatible",
        credential="replacement-session-secret",
        update_credential=True,
    )
    assert settings.secret_for("openai-compatible") == "replacement-session-secret"
    assert "first-session-secret" not in settings._session_credentials.values()

    with pytest.raises(ProviderConfigurationError):
        settings.update_session(
            "openai-compatible",
            credential="rejected-session-secret",
            update_credential=True,
            base_url="https://user:password@provider.example/v1",
            update_base_url=True,
        )
    assert settings.secret_for("openai-compatible") == "replacement-session-secret"
    assert settings.base_url_for("openai-compatible") == "https://api.openai.com/v1"


def test_concurrent_provider_updates_never_cross_credentials() -> None:
    settings = RuntimeProviderSettings({})

    def update(provider: str, prefix: str) -> set[str]:
        observed: set[str] = set()
        for index in range(200):
            settings.set_session_credential(provider, f"{prefix}-{index}")
            value = settings.secret_for(provider)
            assert value is not None
            observed.add(value)
        return observed

    with ThreadPoolExecutor(max_workers=2) as executor:
        anthropic = executor.submit(update, "anthropic", "anthropic-only")
        gemini = executor.submit(update, "gemini", "gemini-only")
    assert all(value.startswith("anthropic-only-") for value in anthropic.result())
    assert all(value.startswith("gemini-only-") for value in gemini.result())
    assert settings.secret_for("anthropic").startswith("anthropic-only-")  # type: ignore[union-attr]
    assert settings.secret_for("gemini").startswith("gemini-only-")  # type: ignore[union-attr]


def test_provider_status_dimensions_are_independent_and_unsupported_discovery_is_neutral() -> None:
    registry = ProviderRegistry(RuntimeProviderSettings({}))
    ollama = registry.status("ollama")
    assert ollama["credential"]["state"] == "not_required"
    assert ollama["endpoint"]["state"] == "not_tested"
    assert ollama["authentication"]["state"] == "not_required"
    assert ollama["model_discovery"]["state"] == "not_tested"
    assert ollama["tool_calling"]["state"] == "not_tested"
    for provider in ("anthropic", "gemini"):
        status = registry.status(provider)
        assert status["model_discovery"]["state"] == "unsupported"
        assert status["capabilities"]["custom_model"] is True
        assert status["capabilities"]["tool_probe"] is True


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
    with pytest.raises(ProviderConfigurationError):
        validate_provider_base_url("file:///tmp/provider")
    with pytest.raises(ProviderConfigurationError):
        validate_provider_base_url("https://user:secret@provider.example/v1")


def test_provider_errors_never_include_authorization_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "authorization-secret-must-not-echo"
    adapter = OpenAICompatibleAdapter(
        base_url="https://127.0.0.1/v1",
        settings=RuntimeProviderSettings({"OPENAI_API_KEY": secret}),
    )

    class Opener:
        def open(self, request, timeout):  # type: ignore[no-untyped-def]
            assert request.get_header("Authorization") == f"Bearer {secret}"
            raise urllib.error.HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                {"Authorization": f"Bearer {secret}"},
                None,
            )

    monkeypatch.setattr("model_runners.openai_compatible.urllib.request.build_opener", lambda *args: Opener())
    with pytest.raises(ModelRunnerError) as caught:
        adapter._request({}, ModelRequestConfig(model="test", max_retries=0))
    message = str(caught.value)
    assert caught.value.code == "provider_authentication_failed"
    assert secret not in message
    assert "Authorization" not in message
    assert "Bearer" not in message


@pytest.mark.asyncio
async def test_ollama_offline_state_is_not_reported_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ProviderRegistry(RuntimeProviderSettings({}))

    def offline(_: str) -> list[dict]:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(registry, "_request_models", offline)
    status = await registry.discover_models("ollama")
    assert status["credential"] == {"state": "not_required", "source": "not_required", "required": False}
    assert status["endpoint"]["state"] == "unreachable"
    assert status["model_discovery"]["state"] == "failed"
    assert status["ready"] is False


def test_ollama_tags_populate_models_and_malformed_payload_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ProviderRegistry(RuntimeProviderSettings({}))

    class Response:
        def __init__(self, body: dict) -> None:
            self.body = body

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args):  # type: ignore[no-untyped-def]
            return False

        def read(self, size: int = -1) -> bytes:
            return json.dumps(self.body).encode()

    class Opener:
        body = {
            "models": [{
                "name": "qwen-local:latest", "size": 1234, "digest": "sha256:model",
                "details": {"family": "qwen", "parameter_size": "7B", "quantization_level": "Q4"},
            }]
        }

        def open(self, request, timeout):  # type: ignore[no-untyped-def]
            assert request.full_url == "http://127.0.0.1:11434/api/tags"
            assert timeout == 10
            return Response(self.body)

    opener = Opener()
    def build_opener(*handlers):  # type: ignore[no-untyped-def]
        assert len(handlers) == 1
        assert handlers[0].redirect_request(None, None, 302, "redirect", {}, "http://169.254.169.254/latest") is None
        return opener

    monkeypatch.setattr("model_runners.registry.urllib.request.build_opener", build_opener)
    models = registry._request_models("ollama")
    assert models == [{
        "id": "qwen-local:latest", "display_name": "qwen-local:latest", "size": 1234,
        "digest": "sha256:model",
        "details": {"family": "qwen", "parameter_size": "7B", "quantization_level": "Q4"},
    }]
    opener.body = {"models": {"unexpected": True}}
    with pytest.raises(ModelRunnerError, match="malformed model discovery"):
        registry._request_models("ollama")


@pytest.mark.asyncio
async def test_ollama_digest_change_invalidates_tool_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ProviderRegistry(RuntimeProviderSettings({}))
    discovered = [{"id": "local-model", "display_name": "local-model", "digest": "digest-one"}]
    monkeypatch.setattr(registry, "_request_models", lambda _: list(discovered))
    status = await registry.discover_models("ollama")
    assert status["models"][0]["digest"] == "digest-one"

    class ProbeAdapter:
        provider = "ollama"

        async def complete(self, *, messages, tools, config):  # type: ignore[no-untyped-def]
            assert [tool.name for tool in tools] == ["frontier_probe"]
            assert "environment" not in messages[-1].content.lower()
            return ModelResponse(tool_calls=(ModelToolCall("probe", "frontier_probe", {"value": "frontier-probe"}),))

    registry._factories["ollama"] = ProbeAdapter
    result = await registry.probe_tool_call("ollama", "local-model")
    assert result["state"] == "passed"
    assert result["model_digest"] == "digest-one"
    assert registry.models("ollama")[0]["tool_compatibility"]["state"] == "passed"

    discovered[0]["digest"] = "digest-two"
    await registry.discover_models("ollama")
    compatibility = registry.models("ollama")[0]["tool_compatibility"]
    assert compatibility["state"] == "not_tested"
    assert compatibility["invalidated"] is True
    assert registry.status("ollama")["tool_calling"]["state"] == "not_tested"


@pytest.mark.asyncio
async def test_malformed_discovery_and_redirect_fail_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ProviderRegistry(RuntimeProviderSettings({}))
    monkeypatch.setattr(
        registry,
        "_request_models",
        lambda _: (_ for _ in ()).throw(ModelRunnerError("malformed", code="model_discovery_failed")),
    )
    malformed = await registry.discover_models("ollama")
    assert malformed["endpoint"]["state"] == "reachable"
    assert malformed["model_discovery"]["state"] == "failed"

    redirect = urllib.error.HTTPError(
        "http://127.0.0.1:11434/api/tags",
        302,
        "redirect",
        {"Location": "http://169.254.169.254/latest"},
        None,
    )
    monkeypatch.setattr(registry, "_request_models", lambda _: (_ for _ in ()).throw(redirect))
    redirected = await registry.discover_models("ollama")
    assert redirected["endpoint"]["state"] == "reachable"
    assert redirected["model_discovery"]["state"] == "failed"


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
