"""Provider registry and browser-safe capability metadata."""

from __future__ import annotations

from typing import Callable

from .anthropic import AnthropicAdapter
from .configuration import configured
from .gemini import GeminiAdapter
from .openai_compatible import OpenAICompatibleAdapter
from .protocol import ModelAdapter
from .scripted import SCRIPTED_MODELS, ScriptedAdapter


PROVIDERS = (
    {"provider": "scripted", "display_name": "Scripted", "models": list(SCRIPTED_MODELS), "capabilities": {"temperature": False, "reasoning_effort": False, "deterministic": False, "custom_model": False}},
    {"provider": "openai-compatible", "display_name": "OpenAI compatible", "models": [], "capabilities": {"temperature": True, "reasoning_effort": True, "deterministic": True, "custom_model": True}},
    {"provider": "anthropic", "display_name": "Anthropic", "models": [], "capabilities": {"temperature": True, "reasoning_effort": False, "deterministic": True, "custom_model": True}},
    {"provider": "gemini", "display_name": "Gemini", "models": [], "capabilities": {"temperature": True, "reasoning_effort": False, "deterministic": True, "custom_model": True}},
    {"provider": "ollama", "display_name": "Ollama (local)", "models": [], "capabilities": {"temperature": True, "reasoning_effort": False, "deterministic": True, "custom_model": True}},
)


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], ModelAdapter]] = {
            "scripted": ScriptedAdapter,
            "openai-compatible": OpenAICompatibleAdapter,
            "anthropic": AnthropicAdapter,
            "gemini": GeminiAdapter,
            "ollama": lambda: OpenAICompatibleAdapter(provider="ollama"),
        }

    def list(self) -> list[dict[str, object]]:
        return [{**item, "configured": configured(str(item["provider"]))} for item in PROVIDERS]

    def models(self, provider: str) -> list[dict[str, str]]:
        for item in PROVIDERS:
            if item["provider"] == provider:
                return list(item["models"])
        raise KeyError(provider)

    def create(self, provider: str) -> ModelAdapter:
        factory = self._factories.get(provider)
        if factory is None:
            raise KeyError(provider)
        return factory()
