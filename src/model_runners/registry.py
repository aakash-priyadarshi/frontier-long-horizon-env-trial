"""Provider registry, safe runtime status, discovery, and isolated tool probes."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

from .anthropic import AnthropicAdapter
from .configuration import RuntimeProviderSettings, custom_headers_for
from .errors import ModelRunnerError, ProviderConfigurationError
from .gemini import GeminiAdapter
from .openai_compatible import OpenAICompatibleAdapter
from .protocol import ModelAdapter, ModelMessage, ModelRequestConfig, ModelTool
from .scripted import SCRIPTED_MODELS, ScriptedAdapter


PROVIDERS = (
    {
        "provider": "scripted",
        "display_name": "Scripted",
        "models": list(SCRIPTED_MODELS),
        "capabilities": {
            "temperature": False, "reasoning_effort": False, "deterministic": False,
            "custom_model": False, "custom_base_url": False, "connection_test": False,
            "model_discovery": False, "tool_probe": False,
        },
    },
    {
        "provider": "openai-compatible",
        "display_name": "OpenAI compatible",
        "models": [],
        "capabilities": {
            "temperature": True, "reasoning_effort": True, "deterministic": True,
            "custom_model": True, "custom_base_url": True, "connection_test": True,
            "model_discovery": True, "tool_probe": True,
        },
    },
    {
        "provider": "anthropic",
        "display_name": "Anthropic",
        "models": [],
        "capabilities": {
            "temperature": True, "reasoning_effort": False, "deterministic": True,
            "custom_model": True, "custom_base_url": False, "connection_test": False,
            "model_discovery": False, "tool_probe": True,
        },
    },
    {
        "provider": "gemini",
        "display_name": "Gemini",
        "models": [],
        "capabilities": {
            "temperature": True, "reasoning_effort": False, "deterministic": True,
            "custom_model": True, "custom_base_url": False, "connection_test": False,
            "model_discovery": False, "tool_probe": True,
        },
    },
    {
        "provider": "ollama",
        "display_name": "Ollama (local)",
        "models": [],
        "capabilities": {
            "temperature": True, "reasoning_effort": False, "deterministic": True,
            "custom_model": True, "custom_base_url": True, "connection_test": True,
            "model_discovery": True, "tool_probe": True,
        },
    },
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


class ProviderRegistry:
    def __init__(self, settings: RuntimeProviderSettings | None = None) -> None:
        self.settings = settings or RuntimeProviderSettings()
        self._factories: dict[str, Callable[[], ModelAdapter]] = {
            "scripted": ScriptedAdapter,
            "openai-compatible": lambda: OpenAICompatibleAdapter(settings=self.settings),
            "anthropic": lambda: AnthropicAdapter(settings=self.settings),
            "gemini": lambda: GeminiAdapter(settings=self.settings),
            "ollama": lambda: OpenAICompatibleAdapter(provider="ollama", settings=self.settings),
        }
        self._endpoint: dict[str, dict[str, Any]] = {}
        self._authentication: dict[str, dict[str, Any]] = {}
        self._model_status: dict[str, dict[str, Any]] = {}
        self._discovered_models: dict[str, list[dict[str, Any]]] = {}
        self._tool_probes: dict[tuple[str, str], dict[str, Any]] = {}

    @staticmethod
    def _definition(provider: str) -> dict[str, Any]:
        item = next((entry for entry in PROVIDERS if entry["provider"] == provider), None)
        if item is None:
            raise KeyError(provider)
        return item

    def _credential(self, provider: str) -> dict[str, Any]:
        source = self.settings.credential_source(provider)
        if source == "not_required":
            state = "not_required"
        elif source == "missing":
            state = "missing"
        else:
            state = "available"
        return {"state": state, "source": source, "required": source != "not_required"}

    def _default_endpoint(self) -> dict[str, Any]:
        return {"state": "not_tested", "tested_at": None}

    def _default_authentication(self, provider: str) -> dict[str, Any]:
        state = "not_required" if self.settings.credential_source(provider) == "not_required" else "not_tested"
        return {"state": state, "tested_at": None}

    def _default_model_status(self, provider: str) -> dict[str, Any]:
        definition = self._definition(provider)
        if provider == "scripted":
            return {"state": "discovered", "count": len(definition["models"]), "tested_at": None}
        if not definition["capabilities"]["model_discovery"]:
            return {"state": "unsupported", "count": 0, "tested_at": None}
        return {"state": "not_tested", "count": 0, "tested_at": None}

    def _probe_for_model(self, provider: str, model: dict[str, Any]) -> dict[str, Any]:
        record = self._tool_probes.get((provider, str(model["id"])))
        if record is None:
            return {"state": "not_tested", "tested_at": None}
        digest = model.get("digest")
        if digest and record.get("model_digest") != digest:
            return {"state": "not_tested", "tested_at": None, "invalidated": True}
        return dict(record)

    def models(self, provider: str) -> list[dict[str, Any]]:
        definition = self._definition(provider)
        source = self._discovered_models.get(provider, list(definition["models"]))
        return [{**model, "tool_compatibility": self._probe_for_model(provider, model)} for model in source]

    def status(self, provider: str) -> dict[str, Any]:
        definition = self._definition(provider)
        credential = self._credential(provider)
        endpoint = dict(self._endpoint.get(provider, self._default_endpoint()))
        authentication = dict(self._authentication.get(provider, self._default_authentication(provider)))
        model_status = dict(self._model_status.get(provider, self._default_model_status(provider)))
        models = self.models(provider)
        model_by_id = {str(model["id"]): model for model in models}
        probes = []
        for (record_provider, record_model), record in self._tool_probes.items():
            if record_provider != provider:
                continue
            current_model = model_by_id.get(record_model)
            if current_model and current_model.get("digest") and current_model.get("digest") != record.get("model_digest"):
                continue
            probes.append(record)
        latest_probe = max(probes, key=lambda item: str(item.get("tested_at") or ""), default=None)
        try:
            public_base_url = self.settings.public_base_url(provider)
        except ProviderConfigurationError:
            public_base_url = None
            endpoint = {"state": "invalid_configuration", "tested_at": None}
        configured = credential["state"] != "missing"
        ready = configured and endpoint["state"] not in {"unreachable", "invalid_configuration"} and authentication["state"] != "invalid"
        return {
            **definition,
            "models": models,
            "configured": configured,
            "ready": ready,
            "credential": credential,
            "endpoint": endpoint,
            "authentication": authentication,
            "model_discovery": model_status,
            "tool_calling": dict(latest_probe) if latest_probe else {"state": "not_tested", "tested_at": None},
            "base_url": public_base_url,
        }

    def list(self) -> list[dict[str, Any]]:
        return [self.status(str(item["provider"])) for item in PROVIDERS]

    def create(self, provider: str) -> ModelAdapter:
        factory = self._factories.get(provider)
        if factory is None:
            raise KeyError(provider)
        return factory()

    def set_session_configuration(
        self,
        provider: str,
        *,
        credential: str | None = None,
        base_url: str | None = None,
        update_base_url: bool = False,
    ) -> dict[str, Any]:
        self._definition(provider)
        self.settings.update_session(
            provider,
            credential=credential,
            update_credential=credential is not None,
            base_url=base_url,
            update_base_url=update_base_url,
        )
        self._reset_runtime_status(provider)
        return self.status(provider)

    def clear_session_credential(self, provider: str) -> dict[str, Any]:
        self._definition(provider)
        self.settings.clear_session_credential(provider)
        self._reset_runtime_status(provider)
        return self.status(provider)

    def _reset_runtime_status(self, provider: str) -> None:
        self._endpoint.pop(provider, None)
        self._authentication.pop(provider, None)
        self._model_status.pop(provider, None)
        self._discovered_models.pop(provider, None)
        for key in [key for key in self._tool_probes if key[0] == provider]:
            self._tool_probes.pop(key, None)

    def _discovery_url(self, provider: str) -> str:
        base_url = self.settings.base_url_for(provider)
        if provider != "ollama":
            return base_url + "/models"
        parsed = urlparse(base_url)
        path = parsed.path.rstrip("/")
        if path.endswith("/v1"):
            path = path[:-3]
        root = urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", ""))
        return root + "/api/tags"

    def _request_models(self, provider: str) -> list[dict[str, Any]]:
        url = self._discovery_url(provider)
        headers = {"Accept": "application/json"}
        secret = self.settings.secret_for(provider)
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        headers.update(custom_headers_for(provider))
        request = urllib.request.Request(url, headers=headers, method="GET")
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=10) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ModelRunnerError("provider model discovery response was too large", code="model_discovery_failed")
        body = json.loads(raw.decode("utf-8"))
        items = body.get("models") if provider == "ollama" else body.get("data")
        if not isinstance(items, list):
            raise ModelRunnerError("provider returned malformed model discovery data", code="model_discovery_failed")
        models: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                raise ModelRunnerError("provider returned malformed model discovery data", code="model_discovery_failed")
            model_id = item.get("name") if provider == "ollama" else item.get("id")
            if not isinstance(model_id, str) or not model_id:
                raise ModelRunnerError("provider returned malformed model discovery data", code="model_discovery_failed")
            model: dict[str, Any] = {"id": model_id, "display_name": model_id}
            if provider == "ollama":
                if isinstance(item.get("size"), int):
                    model["size"] = item["size"]
                if isinstance(item.get("digest"), str):
                    model["digest"] = item["digest"]
                details = item.get("details")
                if isinstance(details, dict):
                    model["details"] = {
                        key: details[key]
                        for key in ("family", "parameter_size", "quantization_level")
                        if isinstance(details.get(key), str)
                    }
            models.append(model)
        return models

    async def discover_models(self, provider: str) -> dict[str, Any]:
        definition = self._definition(provider)
        if not definition["capabilities"]["model_discovery"]:
            self._model_status[provider] = {"state": "unsupported", "count": 0, "tested_at": None}
            return self.status(provider)
        tested_at = _utc_now()
        if not self.settings.configured(provider):
            self._endpoint[provider] = {"state": "not_tested", "tested_at": None}
            self._authentication[provider] = {"state": "not_tested", "tested_at": None}
            self._model_status[provider] = {"state": "failed", "count": 0, "tested_at": tested_at}
            return self.status(provider)
        try:
            started = time.perf_counter()
            models = await asyncio.to_thread(self._request_models, provider)
            latency_ms = round((time.perf_counter() - started) * 1000, 3)
        except urllib.error.HTTPError as exc:
            self._endpoint[provider] = {"state": "reachable", "tested_at": tested_at}
            auth_state = "invalid" if exc.code in {401, 403} else (
                "not_required" if self.settings.credential_source(provider) == "not_required" else "not_tested"
            )
            self._authentication[provider] = {"state": auth_state, "tested_at": tested_at}
            self._model_status[provider] = {"state": "failed", "count": 0, "tested_at": tested_at}
            self._discovered_models.pop(provider, None)
        except (urllib.error.URLError, TimeoutError, OSError):
            self._endpoint[provider] = {"state": "unreachable", "tested_at": tested_at}
            self._authentication[provider] = self._default_authentication(provider) | {"tested_at": tested_at}
            self._model_status[provider] = {"state": "failed", "count": 0, "tested_at": tested_at}
            self._discovered_models.pop(provider, None)
        except (ValueError, ModelRunnerError, ProviderConfigurationError):
            self._endpoint[provider] = {"state": "reachable", "tested_at": tested_at}
            auth_state = "not_required" if self.settings.credential_source(provider) == "not_required" else "valid"
            self._authentication[provider] = {"state": auth_state, "tested_at": tested_at}
            self._model_status[provider] = {"state": "failed", "count": 0, "tested_at": tested_at}
            self._discovered_models.pop(provider, None)
        else:
            self._endpoint[provider] = {"state": "reachable", "tested_at": tested_at, "latency_ms": latency_ms}
            auth_state = "not_required" if self.settings.credential_source(provider) == "not_required" else "valid"
            self._authentication[provider] = {"state": auth_state, "tested_at": tested_at}
            self._discovered_models[provider] = models
            self._model_status[provider] = {"state": "discovered", "count": len(models), "tested_at": tested_at}
        return self.status(provider)

    async def probe_tool_call(self, provider: str, model: str) -> dict[str, Any]:
        definition = self._definition(provider)
        if not definition["capabilities"]["tool_probe"]:
            raise ProviderConfigurationError("this provider does not support tool compatibility probes")
        tested_at = _utc_now()
        known_model = next((item for item in self.models(provider) if item["id"] == model), {"id": model})
        digest = known_model.get("digest")
        probe = ModelTool(
            name="frontier_probe",
            description="Return the supplied harmless compatibility value.",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string", "const": "frontier-probe"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )
        try:
            response = await self.create(provider).complete(
                messages=[
                    ModelMessage("system", "This is an isolated tool-format compatibility check. No environment tools are available."),
                    ModelMessage("user", "Call frontier_probe exactly once with value frontier-probe. Do not answer in text."),
                ],
                tools=[probe],
                config=ModelRequestConfig(
                    model=model, temperature=0, max_output_tokens=128, timeout_seconds=30,
                    max_retries=0, deterministic=True, custom_headers=custom_headers_for(provider),
                ),
            )
            passed = (
                len(response.tool_calls) == 1
                and response.tool_calls[0].name == "frontier_probe"
                and response.tool_calls[0].arguments == {"value": "frontier-probe"}
            )
            record = {
                "state": "passed" if passed else "failed",
                "tested_at": tested_at,
                "model": model,
                "model_digest": digest,
                "error_code": None if passed else "invalid_tool_call",
            }
            self._endpoint[provider] = {"state": "reachable", "tested_at": tested_at}
            self._authentication[provider] = {
                "state": "not_required" if self.settings.credential_source(provider) == "not_required" else "valid",
                "tested_at": tested_at,
            }
        except ModelRunnerError as exc:
            record = {
                "state": "failed", "tested_at": tested_at, "model": model,
                "model_digest": digest, "error_code": exc.code,
            }
            if exc.code == "provider_authentication_failed":
                self._endpoint[provider] = {"state": "reachable", "tested_at": tested_at}
                self._authentication[provider] = {"state": "invalid", "tested_at": tested_at}
            elif exc.code in {"provider_unreachable", "provider_timeout"}:
                self._endpoint[provider] = {"state": "unreachable", "tested_at": tested_at}
        except Exception:
            record = {
                "state": "failed", "tested_at": tested_at, "model": model,
                "model_digest": digest, "error_code": "provider_error",
            }
        self._tool_probes[(provider, model)] = record
        return dict(record)
