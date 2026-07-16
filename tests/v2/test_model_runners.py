from __future__ import annotations

import asyncio
import io
import json
import re
import socket
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from evaluation_service.runner import PROMPT_VERSION, SYSTEM_PROMPT, public_tools
from evaluation_service.schemas import ProviderToolProbeOptions
from model_runners.anthropic import AnthropicAdapter
from model_runners.configuration import RuntimeProviderSettings, configured, custom_headers_for, validate_provider_base_url
from model_runners.errors import MalformedModelResponse, ModelRunnerError, ProviderConfigurationError, ProviderTimeout
from model_runners.gemini import GeminiAdapter
from model_runners.ollama_support import limitation_for_model, profile_for_model, public_support_catalog, support_for_model, supports_reasoning_effort
from model_runners.openai_compatible import OpenAICompatibleAdapter
from model_runners.protocol import ModelMessage, ModelRequestConfig, ModelResponse, ModelTool, ModelToolCall
from model_runners.registry import ProviderRegistry
from model_runners.scripted import ScriptedAdapter
from model_runners.tool_conversion import (
    anthropic_tools,
    gemini_tools,
    ollama_messages,
    openai_messages,
    openai_tools,
    parse_json_arguments,
    parse_openai_tool_calls,
    provider_tool_names,
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


def test_local_env_precedence_persistence_replacement_and_removal(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("# user setting\nUNRELATED=value\nANTHROPIC_API_KEY=old-local\n", encoding="utf-8")
    settings = RuntimeProviderSettings(
        {"ANTHROPIC_API_KEY": "process-secret"},
        local_env_path=env_path,
    )
    assert settings.credential_source("anthropic") == "local_env"
    assert settings.secret_for("anthropic") == "old-local"

    settings.set_session_credential("anthropic", "session-secret")
    assert settings.credential_source("anthropic") == "session"
    settings.persist_local("anthropic", credential="replacement-local", update_credential=True)
    assert settings.credential_source("anthropic") == "local_env"
    assert settings.secret_for("anthropic") == "replacement-local"
    contents = env_path.read_text(encoding="utf-8")
    assert "old-local" not in contents
    assert "session-secret" not in contents
    assert "UNRELATED=value" in contents

    assert settings.clear_local_credential("anthropic") is True
    assert settings.credential_source("anthropic") == "environment"
    assert settings.secret_for("anthropic") == "process-secret"
    assert "replacement-local" not in env_path.read_text(encoding="utf-8")


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


def test_provider_status_dimensions_are_independent_and_cloud_discovery_is_available() -> None:
    registry = ProviderRegistry(RuntimeProviderSettings({}))
    ollama = registry.status("ollama")
    assert ollama["credential"]["state"] == "not_required"
    assert ollama["endpoint"]["state"] == "not_tested"
    assert ollama["authentication"]["state"] == "not_required"
    assert ollama["model_discovery"]["state"] == "not_tested"
    assert ollama["tool_calling"]["state"] == "not_tested"
    for provider in ("anthropic", "gemini"):
        status = registry.status(provider)
        assert status["model_discovery"]["state"] == "not_tested"
        assert status["capabilities"]["model_discovery"] is True
        assert status["capabilities"]["connection_test"] is True
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


def test_provider_tool_names_are_safe_collision_resistant_and_reversible() -> None:
    tools = [
        ModelTool("release.status", "Dotted name.", {}),
        ModelTool("release_status", "Existing safe name.", {}),
        ModelTool("1 invalid tool", "Invalid start and characters.", {}),
        ModelTool("x" * 80, "Overlong name.", {}),
    ]
    names = provider_tool_names(tools)

    aliases = tuple(names.provider_name(tool.name) for tool in tools)
    assert len(set(aliases)) == len(aliases)
    assert names.provider_name("release_status") == "release_status"
    assert names.provider_name("release.status") != "release_status"
    assert all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", alias) for alias in aliases)
    assert tuple(names.canonical_name(alias) for alias in aliases) == tuple(tool.name for tool in tools)


def test_provider_tool_conversions_alias_the_real_environment_names() -> None:
    tools = public_tools()
    names = provider_tool_names(tools)
    expected = {name.replace(".", "_") for name in ALLOWED_TOOLS}

    assert {item["function"]["name"] for item in openai_tools(tools, names=names)} == expected
    assert {item["name"] for item in anthropic_tools(tools, names=names)} == expected
    assert {
        item["name"] for item in gemini_tools(tools, names=names)[0]["functionDeclarations"]
    } == expected


def test_openai_message_conversion_preserves_tool_result() -> None:
    payload = openai_messages([ModelMessage("tool", "{}", tool_call_id="call-1", name="release.status")])
    assert payload == [{"role": "tool", "content": "{}", "tool_call_id": "call-1", "name": "release.status"}]


def test_ollama_reasoning_state_is_replayed_only_when_explicitly_enabled() -> None:
    message = ModelMessage(
        "assistant",
        tool_calls=(ModelToolCall("call-1", "release.status", {}),),
        reasoning="private planning state",
    )
    hosted = openai_messages([message])
    ollama = openai_messages([message], include_reasoning=True)
    assert "reasoning" not in hosted[0]
    assert ollama[0]["reasoning"] == "private planning state"
    native = ollama_messages([message])
    assert native[0]["thinking"] == "private planning state"
    assert native[0]["tool_calls"][0]["function"]["arguments"] == {}


@pytest.mark.asyncio
async def test_native_ollama_adapter_sets_context_and_preserves_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = OpenAICompatibleAdapter(provider="ollama")

    def request(payload: dict, config: ModelRequestConfig) -> dict:
        assert payload["stream"] is False
        assert payload["think"] == "low"
        assert payload["options"]["num_ctx"] == 16_384
        assert payload["options"]["num_predict"] == 2_048
        assert payload["messages"][0]["thinking"] == "prior private state"
        return {
            "message": {
                "role": "assistant",
                "content": "",
                "thinking": "next private state",
                "tool_calls": [{"function": {"name": "release.status", "arguments": {}}}],
            },
            "prompt_eval_count": 100,
            "eval_count": 20,
            "done_reason": "stop",
        }

    monkeypatch.setattr(adapter, "_request_ollama", request)
    response = await adapter.complete(
        messages=[ModelMessage("assistant", reasoning="prior private state")],
        tools=public_tools(),
        config=ModelRequestConfig(
            model="qwen3:8b",
            context_window=16_384,
            max_output_tokens=2_048,
            reasoning_effort="low",
        ),
    )
    assert response.tool_calls[0].name == "release.status"
    assert response.reasoning == "next private state"
    assert response.finish_reason == "tool_calls"
    assert response.reasoning_tokens > 0


@pytest.mark.asyncio
async def test_native_ollama_adapter_omits_thinking_for_llama31(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = OpenAICompatibleAdapter(provider="ollama")

    def request(payload: dict, config: ModelRequestConfig) -> dict:
        assert "think" not in payload
        return {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "release.status", "arguments": {}}}],
            },
            "prompt_eval_count": 100,
            "eval_count": 20,
            "done_reason": "stop",
        }

    monkeypatch.setattr(adapter, "_request_ollama", request)
    response = await adapter.complete(
        messages=[ModelMessage("user", "Check status.")],
        tools=public_tools(),
        config=ModelRequestConfig(model="llama3.1:8b", reasoning_effort="low"),
    )
    assert response.tool_calls[0].name == "release.status"


def test_ollama_reasoning_support_is_model_specific() -> None:
    assert supports_reasoning_effort("qwen3:8b") is True
    assert supports_reasoning_effort("gpt-oss:20b") is True
    assert supports_reasoning_effort("llama3.1:8b") is False
    assert supports_reasoning_effort("unlisted-local-model") is False


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


def test_all_hosted_adapters_classify_wrapped_transport_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapped_timeout = urllib.error.URLError(TimeoutError("safe timeout"))

    class Opener:
        def open(self, request, timeout):  # type: ignore[no-untyped-def]
            raise wrapped_timeout

    openai = OpenAICompatibleAdapter(
        provider="ollama",
        base_url="http://127.0.0.1:11434/v1",
        settings=RuntimeProviderSettings({}),
    )
    monkeypatch.setattr("model_runners.openai_compatible.urllib.request.build_opener", lambda *args: Opener())
    with pytest.raises(ProviderTimeout):
        openai._request({}, ModelRequestConfig(model="test", max_retries=0))

    def timed_out(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise wrapped_timeout

    anthropic = AnthropicAdapter(settings=RuntimeProviderSettings({"ANTHROPIC_API_KEY": "test-key"}))
    monkeypatch.setattr("model_runners.anthropic.urllib.request.urlopen", timed_out)
    with pytest.raises(ProviderTimeout):
        anthropic._request({}, ModelRequestConfig(model="test", max_retries=0))

    gemini = GeminiAdapter(settings=RuntimeProviderSettings({"GEMINI_API_KEY": "test-key"}))
    monkeypatch.setattr("model_runners.gemini.urllib.request.urlopen", timed_out)
    with pytest.raises(ProviderTimeout):
        gemini._request({}, ModelRequestConfig(model="test", max_retries=0))


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


@pytest.mark.parametrize(
    ("provider", "environment", "expected_url", "expected_header", "body", "expected"),
    [
        (
            "anthropic",
            {"ANTHROPIC_API_KEY": "anthropic-discovery-secret"},
            "https://api.anthropic.com/v1/models?limit=100",
            ("X-api-key", "anthropic-discovery-secret"),
            {"data": [{"id": "claude-test", "display_name": "Claude Test"}]},
            [{"id": "claude-test", "display_name": "Claude Test"}],
        ),
        (
            "gemini",
            {"GEMINI_API_KEY": "gemini-discovery-secret"},
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
            ("X-goog-api-key", "gemini-discovery-secret"),
            {"models": [
                {"name": "models/gemini-test", "baseModelId": "gemini-test", "displayName": "Gemini Test", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/embedding-test", "baseModelId": "embedding-test", "supportedGenerationMethods": ["embedContent"]},
            ]},
            [{"id": "gemini-test", "display_name": "Gemini Test"}],
        ),
    ],
)
def test_hosted_model_discovery_uses_provider_auth_without_secret_urls(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    environment: dict[str, str],
    expected_url: str,
    expected_header: tuple[str, str],
    body: dict,
    expected: list[dict],
) -> None:
    registry = ProviderRegistry(RuntimeProviderSettings(environment))

    class Response:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args):  # type: ignore[no-untyped-def]
            return False

        def read(self, size: int = -1) -> bytes:
            return json.dumps(body).encode()

    class Opener:
        def open(self, request, timeout):  # type: ignore[no-untyped-def]
            assert request.full_url == expected_url
            assert environment[next(iter(environment))] not in request.full_url
            assert request.get_header(expected_header[0]) == expected_header[1]
            assert timeout == 10
            return Response()

    monkeypatch.setattr("model_runners.registry.urllib.request.build_opener", lambda *handlers: Opener())
    assert registry._request_models(provider) == expected


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
            assert tools[0].input_schema == {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "string",
                        "description": "The exact value frontier-probe.",
                    }
                },
                "required": ["value"],
            }
            assert "environment" not in messages[-1].content.lower()
            assert config.reasoning_effort == "none"
            assert config.temperature == 0
            assert config.max_output_tokens == 512
            assert config.context_window == 16_384
            assert config.timeout_seconds == 120
            assert config.max_retries == 0
            assert config.deterministic is True
            assert config.required_tool is None
            return ModelResponse(tool_calls=(ModelToolCall("probe", "frontier_probe", {"value": "frontier-probe"}),))

    registry._factories["ollama"] = ProbeAdapter
    result = await registry.probe_tool_call("ollama", "local-model")
    assert result["state"] == "passed"
    assert result["model_digest"] == "digest-one"
    assert result["profile"]["context_window"] == 16_384
    assert result["observed"]["tool_call_count"] == 1
    assert registry.models("ollama")[0]["tool_compatibility"]["state"] == "passed"

    discovered[0]["digest"] = "digest-two"
    await registry.discover_models("ollama")
    compatibility = registry.models("ollama")[0]["tool_compatibility"]
    assert compatibility["state"] == "not_tested"
    assert compatibility["invalidated"] is True
    assert registry.status("ollama")["tool_calling"]["state"] == "not_tested"


@pytest.mark.asyncio
async def test_model_discovery_and_tool_probe_cache_survive_restart_and_stay_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "provider-state.json"
    settings = RuntimeProviderSettings({})
    registry = ProviderRegistry(settings, state_path=state_path)
    monkeypatch.setattr(
        registry,
        "_request_models",
        lambda _: [{"id": "local-model", "display_name": "Local model", "digest": "digest-one"}],
    )
    await registry.discover_models("ollama")

    class ProbeAdapter:
        provider = "ollama"

        async def complete(self, *, messages, tools, config):  # type: ignore[no-untyped-def]
            return ModelResponse(
                tool_calls=(ModelToolCall("probe", "frontier_probe", {"value": "frontier-probe"}),),
                finish_reason="tool_calls",
            )

    registry._factories["ollama"] = ProbeAdapter
    await registry.probe_tool_call("ollama", "local-model")
    assert state_path.is_file()
    assert "credential-secret" not in state_path.read_text(encoding="utf-8")

    restarted_settings = RuntimeProviderSettings({})
    restarted = ProviderRegistry(restarted_settings, state_path=state_path)
    status = restarted.status("ollama")
    assert status["models"][0]["id"] == "local-model"
    assert status["models"][0]["tool_compatibility"]["state"] == "passed"
    assert status["model_discovery"]["cached"] is True
    assert "endpoint_binding" not in json.dumps(status)

    restarted_settings.set_session_base_url("ollama", "http://127.0.0.1:11435/v1")
    invalidated = restarted.models("ollama")[0]["tool_compatibility"]
    assert invalidated["state"] == "not_tested"
    assert invalidated["invalidated"] is True


@pytest.mark.asyncio
async def test_ollama_thinking_model_probe_disables_reasoning_before_tool_call() -> None:
    registry = ProviderRegistry(RuntimeProviderSettings({}))

    class ThinkingAdapter:
        provider = "ollama"

        async def complete(self, *, messages, tools, config):  # type: ignore[no-untyped-def]
            if config.reasoning_effort != "none":
                return ModelResponse(finish_reason="length", reasoning_tokens=config.max_output_tokens)
            return ModelResponse(
                tool_calls=(ModelToolCall("probe", "frontier_probe", {"value": "frontier-probe"}),),
                finish_reason="tool_calls",
            )

    registry._factories["ollama"] = ThinkingAdapter
    result = await registry.probe_tool_call("ollama", "qwen3:8b")
    assert result["state"] == "passed"
    assert result["error_code"] is None


@pytest.mark.asyncio
async def test_custom_ollama_probe_applies_only_bounded_inference_options() -> None:
    registry = ProviderRegistry(RuntimeProviderSettings({}))

    class CustomProbeAdapter:
        provider = "ollama"

        async def complete(self, *, messages, tools, config):  # type: ignore[no-untyped-def]
            assert [tool.name for tool in tools] == ["frontier_probe"]
            assert "native function-call format" in messages[0].content
            assert config.context_window == 8_192
            assert config.max_output_tokens == 768
            assert config.timeout_seconds == 90
            assert config.temperature == 0.2
            assert config.reasoning_effort == "low"
            return ModelResponse(
                tool_calls=(ModelToolCall("probe", "frontier_probe", {"value": "frontier-probe"}),),
                finish_reason="tool_calls",
            )

    registry._factories["ollama"] = CustomProbeAdapter
    result = await registry.probe_tool_call(
        "ollama",
        "unlisted/model:tag",
        options={
            "context_window": 8_192,
            "max_output_tokens": 768,
            "retry_output_tokens": None,
            "timeout_seconds": 90,
            "temperature": 0.2,
            "thinking": "low",
            "prompt_style": "schema_guided",
        },
    )
    assert result["state"] == "passed"
    assert result["profile"]["prompt_style"] == "schema_guided"
    assert result["observed"] == {
        "finish_reason": "tool_calls",
        "tool_call_count": 1,
        "returned_text": False,
        "returned_reasoning": False,
    }


def test_tool_probe_schema_rejects_unbounded_or_incoherent_options() -> None:
    with pytest.raises(ValueError, match="less than or equal to 262144"):
        ProviderToolProbeOptions(context_window=1_000_000)
    with pytest.raises(ValueError, match="retry_output_tokens must be at least"):
        ProviderToolProbeOptions(max_output_tokens=2_048, retry_output_tokens=512)


def test_ollama_support_catalog_is_explicit_and_excludes_known_deepseek_templates() -> None:
    catalog = public_support_catalog()
    assert {item["id"] for item in catalog["items"]} >= {
        "qwen3", "deepseek-r1-0528-qwen3", "llama3.1", "llama3.2", "qwen2.5", "granite3.3"
    }
    assert support_for_model("qwen3:8b")["support"] == "locally_verified"
    assert profile_for_model("gpt-oss:20b")["thinking"] == "low"
    current_deepseek = "deepseek-r1:8b"
    assert support_for_model(current_deepseek) is None
    assert limitation_for_model(current_deepseek)["code"] == "published_template_without_tool_definitions"
    legacy = "deepseek-r1:8b-llama-distill-q4_K_M"
    assert support_for_model(legacy) is None
    assert limitation_for_model(legacy)["code"] == "legacy_template_without_tool_definitions"
    assert catalog["custom_probe"]["isolated_tool"] == "frontier_probe"
    assert catalog["custom_probe"]["executes_tool"] is False
    assert catalog["custom_probe"]["stores_model_output"] is False


def test_ollama_out_of_memory_response_maps_to_safe_diagnostic(monkeypatch: pytest.MonkeyPatch) -> None:
    secret_provider_text = "cudaMalloc failed: out of memory at private-local-path"

    class FailingOpener:
        def open(self, request, timeout):  # type: ignore[no-untyped-def]
            raise urllib.error.HTTPError(
                request.full_url,
                500,
                "Internal Server Error",
                {},
                io.BytesIO(json.dumps({"error": secret_provider_text}).encode()),
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: FailingOpener())
    adapter = OpenAICompatibleAdapter(provider="ollama")
    with pytest.raises(ModelRunnerError) as caught:
        adapter._request_ollama(
            {"model": "local-model", "messages": []},
            ModelRequestConfig(model="local-model"),
        )
    assert caught.value.code == "provider_out_of_memory"
    assert "model and requested context" in str(caught.value)
    assert "private-local-path" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "environment"),
    [
        ("openai-compatible", {"OPENAI_API_KEY": "test-openai-key"}),
        ("anthropic", {"ANTHROPIC_API_KEY": "test-anthropic-key"}),
        ("gemini", {"GEMINI_API_KEY": "test-gemini-key"}),
    ],
)
async def test_hosted_tool_probes_use_provider_neutral_request_options(
    provider: str,
    environment: dict[str, str],
) -> None:
    registry = ProviderRegistry(RuntimeProviderSettings(environment))

    class HostedAdapter:
        async def complete(self, *, messages, tools, config):  # type: ignore[no-untyped-def]
            assert config.reasoning_effort is None
            assert config.temperature is None
            assert config.max_output_tokens == 512
            assert config.timeout_seconds == 60
            assert config.max_retries == 0
            assert config.deterministic is False
            assert config.required_tool == "frontier_probe"
            return ModelResponse(
                tool_calls=(ModelToolCall("probe", "frontier_probe", {"value": "frontier-probe"}),),
                finish_reason="tool_calls",
            )

    registry._factories[provider] = HostedAdapter
    result = await registry.probe_tool_call(provider, "provider-model")
    assert result["state"] == "passed"
    assert result["error_code"] is None


@pytest.mark.asyncio
async def test_tool_probe_reports_truncation_separately_from_invalid_tool_calls() -> None:
    registry = ProviderRegistry(RuntimeProviderSettings({}))
    requests: list[tuple[int, float]] = []

    class TruncatedAdapter:
        provider = "ollama"

        async def complete(self, *, messages, tools, config):  # type: ignore[no-untyped-def]
            requests.append((config.max_output_tokens, config.timeout_seconds))
            return ModelResponse(finish_reason="length")

    registry._factories["ollama"] = TruncatedAdapter
    result = await registry.probe_tool_call("ollama", "thinking-model")
    assert result["state"] == "failed"
    assert result["error_code"] == "probe_output_truncated"
    assert requests == [(512, 120), (2048, 180)]


@pytest.mark.asyncio
async def test_ollama_probe_recovers_when_thinking_exhausts_initial_budget() -> None:
    registry = ProviderRegistry(RuntimeProviderSettings({}))
    requests: list[int] = []

    class VerboseThinkingAdapter:
        provider = "ollama"

        async def complete(self, *, messages, tools, config):  # type: ignore[no-untyped-def]
            requests.append(config.max_output_tokens)
            if config.max_output_tokens == 512:
                return ModelResponse(finish_reason="length", reasoning_tokens=512)
            return ModelResponse(
                tool_calls=(ModelToolCall("probe", "frontier_probe", {"value": "frontier-probe"}),),
                finish_reason="tool_calls",
            )

    registry._factories["ollama"] = VerboseThinkingAdapter
    result = await registry.probe_tool_call("ollama", "verbose-thinking-model")
    assert result["state"] == "passed"
    assert result["error_code"] is None
    assert requests == [512, 2048]


@pytest.mark.asyncio
async def test_model_timeout_does_not_falsely_mark_reachable_endpoint_offline() -> None:
    registry = ProviderRegistry(RuntimeProviderSettings({}))
    registry._endpoint["ollama"] = {"state": "reachable", "tested_at": "earlier"}

    class SlowAdapter:
        provider = "ollama"

        async def complete(self, *, messages, tools, config):  # type: ignore[no-untyped-def]
            raise ProviderTimeout()

    registry._factories["ollama"] = SlowAdapter
    result = await registry.probe_tool_call("ollama", "slow-model")
    assert result["state"] == "failed"
    assert result["error_code"] == "provider_timeout"
    assert registry.status("ollama")["endpoint"]["state"] == "reachable"


@pytest.mark.asyncio
async def test_hosted_adapters_force_only_the_isolated_probe_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = ModelTool(
        "frontier_probe",
        "Harmless probe.",
        {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
    )
    config = ModelRequestConfig(
        model="gpt-5.6-sol",
        max_output_tokens=512,
        required_tool="frontier_probe",
    )
    messages = [ModelMessage("system", "Compatibility check."), ModelMessage("user", "Call the tool.")]

    openai = OpenAICompatibleAdapter()

    def openai_request(payload, request_config):  # type: ignore[no-untyped-def]
        assert payload["tool_choice"] == {"type": "function", "name": "frontier_probe"}
        assert "temperature" not in payload
        assert payload["reasoning"] == {"context": "all_turns"}
        assert payload["max_output_tokens"] == 512
        assert payload["store"] is False
        assert payload["parallel_tool_calls"] is False
        return ({
            "id": "openai-response",
            "status": "completed",
            "output": [{
                "type": "function_call", "call_id": "openai-probe",
                "name": "frontier_probe", "arguments": '{"value":"frontier-probe"}',
            }],
        }, None)

    monkeypatch.setattr(openai, "_request_responses", openai_request)
    openai_response = await openai.complete(messages=messages, tools=[tool], config=config)
    assert openai_response.tool_calls[0].name == "frontier_probe"

    anthropic = AnthropicAdapter()

    def anthropic_request(payload, request_config):  # type: ignore[no-untyped-def]
        assert payload["tool_choice"] == {"type": "tool", "name": "frontier_probe"}
        assert "temperature" not in payload
        return {
            "content": [{
                "type": "tool_use",
                "id": "anthropic-probe",
                "name": "frontier_probe",
                "input": {"value": "frontier-probe"},
            }],
            "stop_reason": "tool_use",
        }

    monkeypatch.setattr(anthropic, "_request", anthropic_request)
    anthropic_response = await anthropic.complete(messages=messages, tools=[tool], config=config)
    assert anthropic_response.tool_calls[0].name == "frontier_probe"

    gemini = GeminiAdapter()

    def gemini_request(payload, request_config):  # type: ignore[no-untyped-def]
        assert payload["toolConfig"] == {
            "functionCallingConfig": {
                "mode": "ANY",
                "allowedFunctionNames": ["frontier_probe"],
            }
        }
        assert "temperature" not in payload["generationConfig"]
        return {
            "candidates": [{
                "content": {"parts": [{
                    "functionCall": {
                        "name": "frontier_probe",
                        "args": {"value": "frontier-probe"},
                    }
                }]},
                "finishReason": "STOP",
            }]
        }

    monkeypatch.setattr(gemini, "_request", gemini_request)
    gemini_response = await gemini.complete(messages=messages, tools=[tool], config=config)
    assert gemini_response.tool_calls[0].name == "frontier_probe"


@pytest.mark.asyncio
async def test_openai_current_models_use_safe_tools_and_current_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OpenAICompatibleAdapter()
    messages = [
        ModelMessage(
            "assistant",
            tool_calls=(ModelToolCall("prior-call", "release.status", {}),),
        ),
        ModelMessage("tool", "{}", tool_call_id="prior-call", name="release.status"),
    ]

    def request(payload, request_config):  # type: ignore[no-untyped-def]
        assert payload["max_output_tokens"] == 2048
        assert "temperature" not in payload
        assert payload["reasoning"] == {"context": "all_turns", "effort": "low"}
        assert payload["tool_choice"] == {"type": "function", "name": "release_status"}
        assert payload["input"][0] == {
            "type": "function_call", "call_id": "prior-call",
            "name": "release_status", "arguments": "{}",
        }
        assert payload["input"][1] == {
            "type": "function_call_output", "call_id": "prior-call", "output": "{}",
        }
        assert {item["name"] for item in payload["tools"]} == {
            name.replace(".", "_") for name in ALLOWED_TOOLS
        }
        assert all(item["strict"] is False for item in payload["tools"])
        assert payload["store"] is False
        return ({
            "id": "openai-current",
            "status": "completed",
            "output": [
                {
                    "type": "reasoning", "id": "reasoning-next",
                    "encrypted_content": "opaque-provider-continuation", "summary": [],
                },
                {
                    "type": "function_call", "call_id": "next-call",
                    "name": "workspace_read", "arguments": '{"path":"service/flow.py"}',
                },
            ],
            "usage": {
                "input_tokens": 20, "output_tokens": 6,
                "input_tokens_details": {"cached_tokens": 3},
                "output_tokens_details": {"reasoning_tokens": 2},
            },
        }, None)

    monkeypatch.setattr(adapter, "_request_responses", request)
    response = await adapter.complete(
        messages=messages,
        tools=public_tools(),
        config=ModelRequestConfig(
            model="gpt-5.6-sol",
            temperature=0,
            reasoning_effort="low",
            max_output_tokens=2048,
            required_tool="release.status",
        ),
    )
    assert response.tool_calls == (
        ModelToolCall("next-call", "workspace.read", {"path": "service/flow.py"}),
    )
    assert (response.input_tokens, response.output_tokens, response.cached_tokens, response.reasoning_tokens) == (20, 6, 3, 2)
    replay = adapter._responses_input(
        [
            ModelMessage("assistant", tool_calls=response.tool_calls, reasoning=response.reasoning),
            ModelMessage("tool", "{}", tool_call_id="next-call", name="workspace.read"),
        ],
        provider_tool_names(public_tools()),
    )
    assert replay[0] == {
        "type": "reasoning", "id": "reasoning-next",
        "encrypted_content": "opaque-provider-continuation", "summary": [],
    }
    assert replay[1]["type"] == "function_call"
    assert replay[2] == {"type": "function_call_output", "call_id": "next-call", "output": "{}"}


@pytest.mark.asyncio
async def test_anthropic_full_episode_tools_are_aliased_and_restored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = AnthropicAdapter()
    messages = [
        ModelMessage(
            "assistant",
            tool_calls=(ModelToolCall("prior-call", "release.status", {}),),
        ),
        ModelMessage("tool", "{}", tool_call_id="prior-call", name="release.status"),
    ]

    def request(payload, request_config):  # type: ignore[no-untyped-def]
        assert payload["tool_choice"] == {"type": "tool", "name": "release_status"}
        assert payload["messages"][0]["content"][0]["name"] == "release_status"
        assert {item["name"] for item in payload["tools"]} == {
            name.replace(".", "_") for name in ALLOWED_TOOLS
        }
        return {
            "id": "anthropic-current",
            "content": [{
                "type": "tool_use",
                "id": "next-call",
                "name": "workspace_read",
                "input": {"path": "service/flow.py"},
            }],
            "stop_reason": "tool_use",
        }

    monkeypatch.setattr(adapter, "_request", request)
    response = await adapter.complete(
        messages=messages,
        tools=public_tools(),
        config=ModelRequestConfig(
            model="claude-fable-5",
            max_output_tokens=2048,
            required_tool="release.status",
        ),
    )
    assert response.tool_calls == (
        ModelToolCall("next-call", "workspace.read", {"path": "service/flow.py"}),
    )


@pytest.mark.asyncio
async def test_anthropic_fable_uses_native_adaptive_tool_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = AnthropicAdapter()
    payloads: list[dict[str, object]] = []

    def request(payload, request_config):  # type: ignore[no-untyped-def]
        payloads.append(payload)
        if len(payloads) == 1:
            assert payload["tool_choice"] == {
                "type": "auto",
                "disable_parallel_tool_use": True,
            }
            assert "temperature" not in payload
            return {
                "id": "anthropic-first",
                "content": [
                    {"type": "thinking", "thinking": "", "signature": "signed-private-state"},
                    {"type": "tool_use", "id": "call-status", "name": "release_status", "input": {}},
                    {
                        "type": "tool_use",
                        "id": "call-read",
                        "name": "workspace_read",
                        "input": {"path": "service/flow.py"},
                    },
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 20, "output_tokens": 8},
            }
        assistant = payload["messages"][1]
        assert assistant["content"][0] == {
            "type": "thinking",
            "thinking": "",
            "signature": "signed-private-state",
        }
        assert [block["name"] for block in assistant["content"][1:]] == [
            "release_status",
            "workspace_read",
        ]
        assert payload["messages"][2] == {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call-status", "content": "{}"},
                {"type": "tool_result", "tool_use_id": "call-read", "content": "{\"content\":\"...\"}"},
            ],
        }
        return {
            "id": "anthropic-second",
            "content": [{"type": "text", "text": "done"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 40, "output_tokens": 2},
        }

    monkeypatch.setattr(adapter, "_request", request)
    config = ModelRequestConfig(
        model="claude-fable-5",
        temperature=0,
        deterministic=True,
        max_output_tokens=2048,
    )
    initial = [ModelMessage("user", "Inspect the incident.")]
    first = await adapter.complete(messages=initial, tools=public_tools(), config=config)
    assert first.tool_calls == (
        ModelToolCall("call-status", "release.status", {}),
        ModelToolCall("call-read", "workspace.read", {"path": "service/flow.py"}),
    )
    assert "signed-private-state" in first.reasoning
    second = await adapter.complete(
        messages=[
            *initial,
            ModelMessage("assistant", tool_calls=first.tool_calls, reasoning=first.reasoning),
            ModelMessage("tool", "{}", tool_call_id="call-status", name="release.status"),
            ModelMessage(
                "tool",
                "{\"content\":\"...\"}",
                tool_call_id="call-read",
                name="workspace.read",
            ),
        ],
        tools=public_tools(),
        config=config,
    )
    assert second.text == "done"
    assert second.reasoning == ""


def test_anthropic_http_error_is_classified_without_provider_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_text = "authorization: Bearer must-not-leak"
    error = urllib.error.HTTPError(
        "https://api.anthropic.com/v1/messages",
        400,
        "bad request",
        {},
        io.BytesIO(json.dumps({
            "type": "error",
            "error": {"type": "invalid_request_error", "message": secret_text},
        }).encode()),
    )

    def rejected(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise error

    monkeypatch.setattr("model_runners.anthropic.urllib.request.urlopen", rejected)
    adapter = AnthropicAdapter(
        settings=RuntimeProviderSettings({"ANTHROPIC_API_KEY": "test-key"})
    )
    with pytest.raises(ModelRunnerError) as exc_info:
        adapter._request({}, ModelRequestConfig(model="claude-fable-5", max_retries=0))
    assert exc_info.value.code == "provider_request_incompatible"
    assert secret_text not in str(exc_info.value)


@pytest.mark.asyncio
async def test_gemini_full_episode_tools_are_aliased_and_restored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = GeminiAdapter()

    def request(payload, request_config):  # type: ignore[no-untyped-def]
        assert payload["toolConfig"]["functionCallingConfig"]["allowedFunctionNames"] == [
            "release_status"
        ]
        assert {item["name"] for item in payload["tools"][0]["functionDeclarations"]} == {
            name.replace(".", "_") for name in ALLOWED_TOOLS
        }
        return {
            "responseId": "gemini-current",
            "candidates": [{
                "content": {"parts": [{
                    "functionCall": {
                        "name": "workspace_read",
                        "args": {"path": "service/flow.py"},
                    }
                }]},
                "finishReason": "STOP",
            }],
        }

    monkeypatch.setattr(adapter, "_request", request)
    response = await adapter.complete(
        messages=[ModelMessage("user", "Inspect the workspace.")],
        tools=public_tools(),
        config=ModelRequestConfig(
            model="gemini-tool-model",
            max_output_tokens=2048,
            required_tool="release.status",
        ),
    )
    assert response.tool_calls == (
        ModelToolCall("gemini-0", "workspace.read", {"path": "service/flow.py"}),
    )


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
                "choices": [{"message": {"content": "", "reasoning": "private planning", "tool_calls": [{"id": "c1", "function": {"name": "release.status", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "prompt_tokens_details": {"cached_tokens": 2}, "completion_tokens_details": {"reasoning_tokens": 1}},
            },
            None,
        ),
    )
    response = await adapter.complete(messages=[ModelMessage("user", "hello")], tools=public_tools(), config=ModelRequestConfig(model="test"))
    assert response.provider_request_id == "req-1"
    assert response.reasoning == "private planning"
    assert response.tool_calls[0].name == "release.status"
    assert (response.input_tokens, response.output_tokens, response.cached_tokens, response.reasoning_tokens) == (10, 4, 2, 1)


def test_prompt_is_versioned_and_does_not_name_privileged_details() -> None:
    assert PROMPT_VERSION == "frontier-incident-agent-v2.7"
    lowered = SYSTEM_PROMPT.lower()
    for forbidden in ("member a", "member b", "profile derivation", "strict verifier predicate", "gold repair"):
        assert forbidden not in lowered
    assert "twelve tools" in lowered
    assert "investigate" in lowered
    assert "telemetry.logs returns a trace-only handle" in lowered
    assert "diag-s2 + s2.exit" in lowered
    assert "correct the next call" in lowered
    assert "public incident ticket" in lowered
    assert "attempt_budget in settings.toml matches" not in lowered
    restore = next(tool for tool in public_tools() if tool.name == "recovery.restore")
    assert restore.input_schema["properties"]["snapshot_id"]["default"] == "S0"
    assert "not an integrity root digest" in restore.input_schema["properties"]["snapshot_id"]["description"]


def test_public_diagnostic_tool_contract_matches_runtime() -> None:
    tools = {tool.name: tool for tool in public_tools()}
    runtime_properties = tools["runtime.run"].input_schema["properties"]
    assert runtime_properties["workload_id"]["enum"] == [
        "P1", "P2", "P3", "diag-s2", "diag-s5",
    ]
    assert runtime_properties["cutpoint"]["enum"] == ["s2.exit", "s5.exit"]
    state_properties = tools["state.inspect"].input_schema["properties"]
    assert "telemetry.logs handle is trace-only" in state_properties["source"]["description"]
    assert "diagnostic runtime.run" in state_properties["source"]["description"]
