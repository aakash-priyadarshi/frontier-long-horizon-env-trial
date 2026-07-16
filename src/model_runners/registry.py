"""Provider registry, safe runtime status, discovery, and isolated tool probes."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

from .anthropic import AnthropicAdapter
from .configuration import RuntimeProviderSettings, custom_headers_for
from .errors import ModelRunnerError, ProviderConfigurationError
from .gemini import GeminiAdapter
from .ollama_support import (
    limitation_for_model,
    profile_for_model,
    public_support_catalog,
    support_for_model,
    supports_reasoning_effort,
)
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
            "custom_model": True, "custom_base_url": False, "connection_test": True,
            "model_discovery": True, "tool_probe": True,
        },
    },
    {
        "provider": "gemini",
        "display_name": "Gemini",
        "models": [],
        "capabilities": {
            "temperature": True, "reasoning_effort": False, "deterministic": True,
            "custom_model": True, "custom_base_url": False, "connection_test": True,
            "model_discovery": True, "tool_probe": True,
        },
    },
    {
        "provider": "ollama",
        "display_name": "Ollama (local)",
        "models": [],
        "capabilities": {
            "temperature": True, "reasoning_effort": True, "deterministic": True,
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
    def __init__(
        self,
        settings: RuntimeProviderSettings | None = None,
        *,
        state_path: Path | None = None,
    ) -> None:
        self.settings = settings or RuntimeProviderSettings()
        self._state_path = state_path
        self._state_lock = threading.RLock()
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
        self._load_state()

    def _endpoint_binding(self, provider: str) -> str:
        try:
            return self.settings.public_base_url(provider) or f"provider:{provider}"
        except ProviderConfigurationError:
            return f"provider:{provider}:invalid"

    @staticmethod
    def _safe_cached_model(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        model_id = value.get("id")
        display_name = value.get("display_name")
        if not isinstance(model_id, str) or not model_id or len(model_id) > 200:
            return None
        result: dict[str, Any] = {
            "id": model_id,
            "display_name": display_name if isinstance(display_name, str) and len(display_name) <= 300 else model_id,
        }
        if isinstance(value.get("size"), int) and 0 <= value["size"] <= 2**63 - 1:
            result["size"] = value["size"]
        if isinstance(value.get("digest"), str) and len(value["digest"]) <= 256:
            result["digest"] = value["digest"]
        details = value.get("details")
        if isinstance(details, dict):
            safe_details = {
                key: details[key]
                for key in ("family", "parameter_size", "quantization_level")
                if isinstance(details.get(key), str) and len(details[key]) <= 200
            }
            if safe_details:
                result["details"] = safe_details
        return result

    @staticmethod
    def _safe_cached_probe(provider: str, model: str, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict) or value.get("state") not in {"passed", "failed"}:
            return None
        tested_at = value.get("tested_at")
        if not isinstance(tested_at, str) or len(tested_at) > 64:
            return None
        record: dict[str, Any] = {
            "state": value["state"],
            "tested_at": tested_at,
            "model": model,
            "model_digest": value.get("model_digest") if isinstance(value.get("model_digest"), str) else None,
            "profile": None,
            "observed": None,
            "error_code": value.get("error_code") if isinstance(value.get("error_code"), str) and len(value["error_code"]) <= 100 else None,
            "endpoint_binding": value.get("endpoint_binding") if isinstance(value.get("endpoint_binding"), str) and len(value["endpoint_binding"]) <= 2_048 else f"provider:{provider}",
        }
        profile = value.get("profile")
        if provider == "ollama" and isinstance(profile, dict):
            allowed_profile = {
                key: profile[key]
                for key in (
                    "context_window", "max_output_tokens", "retry_output_tokens",
                    "timeout_seconds", "temperature", "thinking", "prompt_style",
                )
                if isinstance(profile.get(key), (str, int, float, type(None)))
            }
            record["profile"] = allowed_profile
        observed = value.get("observed")
        if isinstance(observed, dict):
            record["observed"] = {
                "finish_reason": observed.get("finish_reason") if isinstance(observed.get("finish_reason"), str) else None,
                "tool_call_count": observed.get("tool_call_count") if isinstance(observed.get("tool_call_count"), int) else 0,
                "returned_text": bool(observed.get("returned_text")),
                "returned_reasoning": bool(observed.get("returned_reasoning")),
            }
        return record

    def _load_state(self) -> None:
        path = self._state_path
        if path is None or not path.is_file():
            return
        try:
            if path.stat().st_size > 5_000_000:
                return
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return
        providers = body.get("providers") if isinstance(body, dict) and body.get("version") == 1 else None
        if not isinstance(providers, dict):
            return
        for provider, value in providers.items():
            if provider not in {str(item["provider"]) for item in PROVIDERS} or not isinstance(value, dict):
                continue
            models = value.get("models")
            if isinstance(models, list) and len(models) <= 5_000:
                safe_models = [item for item in (self._safe_cached_model(model) for model in models) if item]
                self._discovered_models[provider] = safe_models
                self._model_status[provider] = {
                    "state": "discovered", "count": len(safe_models),
                    "tested_at": value.get("models_tested_at") if isinstance(value.get("models_tested_at"), str) else None,
                    "cached": True,
                }
            probes = value.get("tool_probes")
            if isinstance(probes, dict) and len(probes) <= 5_000:
                for model, probe in probes.items():
                    if isinstance(model, str) and 0 < len(model) <= 200:
                        safe_probe = self._safe_cached_probe(provider, model, probe)
                        if safe_probe is not None:
                            self._tool_probes[(provider, model)] = safe_probe

    def _save_state(self) -> None:
        path = self._state_path
        if path is None:
            return
        providers: dict[str, Any] = {}
        for definition in PROVIDERS:
            provider = str(definition["provider"])
            if provider == "scripted":
                continue
            models = self._discovered_models.get(provider)
            probes = {
                model: record
                for (record_provider, model), record in self._tool_probes.items()
                if record_provider == provider
            }
            if models is not None or probes:
                providers[provider] = {
                    "models": models or [],
                    "models_tested_at": self._model_status.get(provider, {}).get("tested_at"),
                    "tool_probes": probes,
                }
        content = json.dumps({"version": 1, "providers": providers}, sort_keys=True, separators=(",", ":")) + "\n"
        with self._state_lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
                temporary.write_text(content, encoding="utf-8")
                os.replace(temporary, path)
            except OSError:
                # Persistence is a convenience cache; provider operations remain usable.
                return

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
        if record.get("endpoint_binding") is not None and record.get("endpoint_binding") != self._endpoint_binding(provider):
            return {"state": "not_tested", "tested_at": None, "invalidated": True}
        digest = model.get("digest")
        if digest and record.get("model_digest") != digest:
            return {"state": "not_tested", "tested_at": None, "invalidated": True}
        return {key: value for key, value in record.items() if key != "endpoint_binding"}

    def models(self, provider: str) -> list[dict[str, Any]]:
        definition = self._definition(provider)
        source = self._discovered_models.get(provider, list(definition["models"]))
        models = [{**model, "tool_compatibility": self._probe_for_model(provider, model)} for model in source]
        if provider != "ollama":
            return models
        enriched: list[dict[str, Any]] = []
        for model in models:
            support = support_for_model(str(model["id"]))
            limitation = limitation_for_model(str(model["id"]))
            enriched.append({
                **model,
                "tool_support": (
                    {
                        "profile_id": support["id"],
                        "profile_name": support["name"],
                        "support": support["support"],
                        "notes": support["notes"],
                    }
                    if support is not None
                    else None
                ),
                "tool_limitation": limitation,
                "inference_capabilities": {
                    "reasoning_effort": supports_reasoning_effort(str(model["id"])),
                },
            })
        return enriched

    @staticmethod
    def ollama_tool_support() -> dict[str, Any]:
        return public_support_catalog()

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
            if record.get("endpoint_binding") is None or record.get("endpoint_binding") == self._endpoint_binding(provider):
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
            "tool_calling": (
                {key: value for key, value in latest_probe.items() if key != "endpoint_binding"}
                if latest_probe else {"state": "not_tested", "tested_at": None}
            ),
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
        persist: bool = False,
    ) -> dict[str, Any]:
        self._definition(provider)
        previous_binding = self._endpoint_binding(provider)
        if persist:
            self.settings.persist_local(
                provider,
                credential=credential,
                update_credential=credential is not None,
                base_url=base_url,
                update_base_url=update_base_url,
            )
        else:
            self.settings.update_session(
                provider,
                credential=credential,
                update_credential=credential is not None,
                base_url=base_url,
                update_base_url=update_base_url,
            )
        self._reset_runtime_status(provider, clear_cache=previous_binding != self._endpoint_binding(provider))
        return self.status(provider)

    def clear_session_credential(self, provider: str, *, remove_local: bool = False) -> dict[str, Any]:
        self._definition(provider)
        if remove_local:
            self.settings.clear_local_credential(provider)
        else:
            self.settings.clear_session_credential(provider)
        self._reset_runtime_status(provider)
        return self.status(provider)

    def _reset_runtime_status(self, provider: str, *, clear_cache: bool = False) -> None:
        self._endpoint.pop(provider, None)
        self._authentication.pop(provider, None)
        if clear_cache:
            self._model_status.pop(provider, None)
            self._discovered_models.pop(provider, None)
            for key in [key for key in self._tool_probes if key[0] == provider]:
                self._tool_probes.pop(key, None)
            self._save_state()

    def _discovery_url(self, provider: str) -> str:
        if provider == "anthropic":
            return "https://api.anthropic.com/v1/models?limit=100"
        if provider == "gemini":
            return "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"
        base_url = self.settings.base_url_for(provider)
        if provider == "openai-compatible":
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
        if secret and provider == "anthropic":
            headers["x-api-key"] = secret
            headers["anthropic-version"] = "2023-06-01"
        elif secret and provider == "gemini":
            headers["x-goog-api-key"] = secret
        elif secret:
            headers["Authorization"] = f"Bearer {secret}"
        headers.update(custom_headers_for(provider))
        request = urllib.request.Request(url, headers=headers, method="GET")
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=10) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ModelRunnerError("provider model discovery response was too large", code="model_discovery_failed")
        body = json.loads(raw.decode("utf-8"))
        items = body.get("models") if provider in {"ollama", "gemini"} else body.get("data")
        if not isinstance(items, list):
            raise ModelRunnerError("provider returned malformed model discovery data", code="model_discovery_failed")
        models: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                raise ModelRunnerError("provider returned malformed model discovery data", code="model_discovery_failed")
            if provider == "ollama":
                model_id = item.get("name")
            elif provider == "gemini":
                methods = item.get("supportedGenerationMethods")
                if isinstance(methods, list) and "generateContent" not in methods:
                    continue
                model_id = item.get("baseModelId")
                if not model_id and isinstance(item.get("name"), str):
                    model_id = item["name"].removeprefix("models/")
            else:
                model_id = item.get("id")
            if not isinstance(model_id, str) or not model_id:
                raise ModelRunnerError("provider returned malformed model discovery data", code="model_discovery_failed")
            display_name = item.get("display_name") if provider == "anthropic" else item.get("displayName")
            model: dict[str, Any] = {
                "id": model_id,
                "display_name": display_name if isinstance(display_name, str) and display_name else model_id,
            }
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
            self._model_status[provider] = {"state": "failed", "count": len(self._discovered_models.get(provider, [])), "tested_at": tested_at}
        except (urllib.error.URLError, TimeoutError, OSError):
            self._endpoint[provider] = {"state": "unreachable", "tested_at": tested_at}
            self._authentication[provider] = self._default_authentication(provider) | {"tested_at": tested_at}
            self._model_status[provider] = {"state": "failed", "count": len(self._discovered_models.get(provider, [])), "tested_at": tested_at}
        except (ValueError, ModelRunnerError, ProviderConfigurationError):
            self._endpoint[provider] = {"state": "reachable", "tested_at": tested_at}
            auth_state = "not_required" if self.settings.credential_source(provider) == "not_required" else "valid"
            self._authentication[provider] = {"state": auth_state, "tested_at": tested_at}
            self._model_status[provider] = {"state": "failed", "count": len(self._discovered_models.get(provider, [])), "tested_at": tested_at}
        else:
            self._endpoint[provider] = {"state": "reachable", "tested_at": tested_at, "latency_ms": latency_ms}
            auth_state = "not_required" if self.settings.credential_source(provider) == "not_required" else "valid"
            self._authentication[provider] = {"state": auth_state, "tested_at": tested_at}
            self._discovered_models[provider] = models
            self._model_status[provider] = {"state": "discovered", "count": len(models), "tested_at": tested_at}
            self._save_state()
        return self.status(provider)

    async def probe_tool_call(
        self,
        provider: str,
        model: str,
        *,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        definition = self._definition(provider)
        if not definition["capabilities"]["tool_probe"]:
            raise ProviderConfigurationError("this provider does not support tool compatibility probes")
        if options is not None and provider != "ollama":
            raise ProviderConfigurationError("custom tool-probe options are available only for Ollama")
        tested_at = _utc_now()
        known_model = next((item for item in self.models(provider) if item["id"] == model), {"id": model})
        digest = known_model.get("digest")
        probe = ModelTool(
            name="frontier_probe",
            description="Call this harmless compatibility tool with the exact value requested by the user.",
            input_schema={
                "type": "object",
                "properties": {
                    "value": {
                        "type": "string",
                        "description": "The exact value frontier-probe.",
                    }
                },
                "required": ["value"],
            },
        )
        is_ollama = provider == "ollama"
        profile = profile_for_model(model) if is_ollama else {}
        if options is not None:
            profile.update(options)
        prompt_style = str(profile.get("prompt_style", "strict"))
        system_prompt = "This is an isolated tool-format compatibility check. No environment tools are available."
        user_prompt = "Call frontier_probe exactly once with value frontier-probe. Do not answer in text."
        if prompt_style == "minimal":
            system_prompt = "Use the supplied native tool when requested."
        elif prompt_style == "schema_guided":
            system_prompt = (
                "This is an isolated native function-call format check. Exactly one harmless tool is supplied in "
                "the request tools field. Emit a native tool call, never prose; no environment tools are available."
            )
            user_prompt = (
                "Invoke frontier_probe exactly once. Its only required string argument is value, and value must "
                "equal frontier-probe. Return the call through the native tool-call channel, not as JSON text."
            )
        try:
            messages = [
                ModelMessage("system", system_prompt),
                ModelMessage("user", user_prompt),
            ]
            adapter = self.create(provider)

            async def complete(max_output_tokens: int, timeout_seconds: int) -> Any:
                thinking = str(profile.get("thinking", "off")) if is_ollama else "default"
                return await adapter.complete(
                    messages=messages,
                    tools=[probe],
                    config=ModelRequestConfig(
                        model=model,
                        # Ollama thinking models (including Qwen3 and DeepSeek-R1) can
                        # otherwise spend the entire probe budget reasoning before
                        # emitting the requested tool call. Hosted providers do not
                        # receive this Ollama-specific compatibility option.
                        reasoning_effort=(
                            None if not is_ollama or thinking == "default"
                            else "none" if thinking == "off"
                            else thinking
                        ),
                        temperature=float(profile.get("temperature", 0)) if is_ollama else None,
                        max_output_tokens=max_output_tokens,
                        context_window=int(profile["context_window"]) if is_ollama else None,
                        timeout_seconds=timeout_seconds,
                        max_retries=0,
                        deterministic=is_ollama,
                        required_tool=None if is_ollama else "frontier_probe",
                        custom_headers=custom_headers_for(provider),
                    ),
                )

            initial_tokens = int(profile.get("max_output_tokens", 512)) if is_ollama else 512
            initial_timeout = int(profile.get("timeout_seconds", 120)) if is_ollama else 60
            response = await complete(initial_tokens, initial_timeout)
            passed = (
                len(response.tool_calls) == 1
                and response.tool_calls[0].name == "frontier_probe"
                and response.tool_calls[0].arguments == {"value": "frontier-probe"}
            )
            retry_tokens = profile.get("retry_output_tokens") if is_ollama else None
            if (
                is_ollama
                and retry_tokens is not None
                and int(retry_tokens) > initial_tokens
                and not passed
                and response.finish_reason in {"length", "max_tokens", "MAX_TOKENS"}
            ):
                response = await complete(int(retry_tokens), min(300, max(initial_timeout, 180)))
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
                "profile": dict(profile) if is_ollama else None,
                "observed": {
                    "finish_reason": response.finish_reason,
                    "tool_call_count": len(response.tool_calls),
                    "returned_text": bool(response.text),
                    "returned_reasoning": bool(response.reasoning),
                },
                "error_code": None if passed else (
                    "probe_output_truncated"
                    if response.finish_reason in {"length", "max_tokens", "MAX_TOKENS"}
                    else "invalid_tool_call"
                ),
                "endpoint_binding": self._endpoint_binding(provider),
            }
            self._endpoint[provider] = {"state": "reachable", "tested_at": tested_at}
            self._authentication[provider] = {
                "state": "not_required" if self.settings.credential_source(provider) == "not_required" else "valid",
                "tested_at": tested_at,
            }
        except ModelRunnerError as exc:
            record = {
                "state": "failed", "tested_at": tested_at, "model": model,
                "model_digest": digest, "profile": dict(profile) if is_ollama else None,
                "observed": None, "error_code": exc.code,
                "endpoint_binding": self._endpoint_binding(provider),
            }
            if exc.code == "provider_authentication_failed":
                self._endpoint[provider] = {"state": "reachable", "tested_at": tested_at}
                self._authentication[provider] = {"state": "invalid", "tested_at": tested_at}
            elif exc.code == "provider_unreachable":
                self._endpoint[provider] = {"state": "unreachable", "tested_at": tested_at}
        except Exception:
            record = {
                "state": "failed", "tested_at": tested_at, "model": model,
                "model_digest": digest, "profile": dict(profile) if is_ollama else None,
                "observed": None, "error_code": "provider_error",
                "endpoint_binding": self._endpoint_binding(provider),
            }
        self._tool_probes[(provider, model)] = record
        self._save_state()
        return {key: value for key, value in record.items() if key != "endpoint_binding"}
