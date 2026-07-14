"""Documented Ollama tool-probe profiles and conservative model-family matching."""

from __future__ import annotations

from copy import deepcopy
from fnmatch import fnmatch
from typing import Any


DEFAULT_OLLAMA_PROBE_PROFILE: dict[str, Any] = {
    "context_window": 16_384,
    "max_output_tokens": 512,
    "retry_output_tokens": 2_048,
    "timeout_seconds": 120,
    "temperature": 0.0,
    "thinking": "off",
    "prompt_style": "strict",
}


# "Supported" means that Ollama publishes the family with native tool capability
# and Frontier has a bounded probe profile for it. Every exact tag and digest must
# still pass the isolated probe before an evaluation can start.
OLLAMA_TOOL_SUPPORT: tuple[dict[str, Any], ...] = (
    {
        "id": "qwen3",
        "name": "Qwen 3",
        "patterns": ["qwen3:*", "qwen3"],
        "examples": ["qwen3:8b", "qwen3:4b"],
        "support": "locally_verified",
        "hardware": "4B and 8B quantized tags are practical local starting points; probe the exact digest.",
        "notes": "Native tools and thinking are supported. Frontier disables thinking only for the format probe.",
        "profile": dict(DEFAULT_OLLAMA_PROBE_PROFILE),
    },
    {
        "id": "deepseek-r1-0528-qwen3",
        "name": "DeepSeek R1 0528 Qwen3",
        "patterns": ["deepseek-r1", "deepseek-r1:latest", "deepseek-r1:8b", "deepseek-r1:8b-0528-qwen3-*"],
        "examples": ["deepseek-r1:8b", "deepseek-r1:8b-0528-qwen3-q4_K_M"],
        "support": "profile_available",
        "hardware": "The Q4 8B tag is the DeepSeek option intended for an 8 GB GPU; use a bounded context.",
        "notes": "Use the current Qwen3-based 8B release. The older Llama-distill 8B template is excluded below.",
        "profile": dict(DEFAULT_OLLAMA_PROBE_PROFILE),
    },
    {
        "id": "llama3.1",
        "name": "Llama 3.1",
        "patterns": ["llama3.1", "llama3.1:*"],
        "examples": ["llama3.1:8b"],
        "support": "profile_available",
        "hardware": "Use a quantized 8B tag on an 8 GB GPU and keep the initial context at 16K or lower.",
        "notes": "Ollama publishes this family with native tool calling.",
        "profile": {**DEFAULT_OLLAMA_PROBE_PROFILE, "thinking": "default"},
    },
    {
        "id": "llama3.2",
        "name": "Llama 3.2",
        "patterns": ["llama3.2", "llama3.2:*"],
        "examples": ["llama3.2:3b", "llama3.2:1b"],
        "support": "profile_available",
        "hardware": "The 3B and 1B tags fit easily, but smaller size may limit long-horizon repair quality.",
        "notes": "Ollama publishes this family with native tool calling.",
        "profile": {**DEFAULT_OLLAMA_PROBE_PROFILE, "thinking": "default"},
    },
    {
        "id": "qwen2.5",
        "name": "Qwen 2.5",
        "patterns": ["qwen2.5", "qwen2.5:*"],
        "examples": ["qwen2.5:7b", "qwen2.5:3b"],
        "support": "profile_available",
        "hardware": "Quantized 3B or 7B tags are suitable for an 8 GB GPU.",
        "notes": "Ollama publishes this family with native tool calling; exact quantizations still require a probe.",
        "profile": {**DEFAULT_OLLAMA_PROBE_PROFILE, "thinking": "default"},
    },
    {
        "id": "granite3.3",
        "name": "IBM Granite 3.3",
        "patterns": ["granite3.3", "granite3.3:*"],
        "examples": ["granite3.3:8b", "granite3.3:2b"],
        "support": "profile_available",
        "hardware": "Both published sizes fit locally when quantized; 8B is the stronger evaluation candidate.",
        "notes": "The family documents function-calling tasks; pass the exact digest probe before use.",
        "profile": {**DEFAULT_OLLAMA_PROBE_PROFILE, "thinking": "default"},
    },
    {
        "id": "mistral-small",
        "name": "Mistral Small 3 / 3.1",
        "patterns": ["mistral-small", "mistral-small:*", "mistral-small3.1", "mistral-small3.1:*"],
        "examples": ["mistral-small:24b", "mistral-small3.1:latest"],
        "support": "profile_available",
        "hardware": "The roughly 14–15 GB quantized models are not a good fit for an 8 GB GPU without CPU offload.",
        "notes": "Native function calling is documented, but hardware fit and latency must be checked locally.",
        "profile": {**DEFAULT_OLLAMA_PROBE_PROFILE, "thinking": "default"},
    },
    {
        "id": "gpt-oss",
        "name": "GPT-OSS",
        "patterns": ["gpt-oss", "gpt-oss:*"],
        "examples": ["gpt-oss:20b"],
        "support": "profile_available",
        "hardware": "The 20B tag is about 14 GB and is not recommended for an 8 GB GPU without offload.",
        "notes": "This family requires a reasoning level; the profile uses low for the isolated probe.",
        "profile": {**DEFAULT_OLLAMA_PROBE_PROFILE, "thinking": "low"},
    },
)


OLLAMA_KNOWN_LIMITATIONS: tuple[dict[str, Any], ...] = (
    {
        "patterns": ["deepseek-r1:8b-llama-distill-*"],
        "name": "DeepSeek R1 Llama-distill 8B",
        "code": "legacy_template_without_tool_definitions",
        "detail": (
            "This legacy tag can advertise a tools capability while its installed chat template does not inject "
            "the supplied tool definitions. It may answer the probe in prose instead of emitting a native call."
        ),
        "recommendation": "Install and probe the current Qwen3-based tag: ollama pull deepseek-r1:8b",
    },
)


def _matches(model: str, patterns: list[str]) -> bool:
    normalized = model.strip().lower()
    return any(fnmatch(normalized, pattern.lower()) for pattern in patterns)


def limitation_for_model(model: str) -> dict[str, Any] | None:
    for limitation in OLLAMA_KNOWN_LIMITATIONS:
        if _matches(model, limitation["patterns"]):
            return deepcopy(limitation)
    return None


def support_for_model(model: str) -> dict[str, Any] | None:
    if limitation_for_model(model) is not None:
        return None
    for item in OLLAMA_TOOL_SUPPORT:
        if _matches(model, item["patterns"]):
            return deepcopy(item)
    return None


def profile_for_model(model: str) -> dict[str, Any]:
    support = support_for_model(model)
    if support is None:
        return dict(DEFAULT_OLLAMA_PROBE_PROFILE)
    return dict(support["profile"])


def public_support_catalog() -> dict[str, Any]:
    return {
        "items": deepcopy(list(OLLAMA_TOOL_SUPPORT)),
        "known_limitations": deepcopy(list(OLLAMA_KNOWN_LIMITATIONS)),
        "custom_probe": {
            "isolated_tool": "frontier_probe",
            "executes_tool": False,
            "stores_model_output": False,
            "fields": [
                {"name": "context_window", "minimum": 4_096, "maximum": 262_144},
                {"name": "max_output_tokens", "minimum": 128, "maximum": 8_192},
                {"name": "retry_output_tokens", "minimum": 128, "maximum": 8_192, "nullable": True},
                {"name": "timeout_seconds", "minimum": 10, "maximum": 300},
                {"name": "temperature", "minimum": 0, "maximum": 2},
                {"name": "thinking", "values": ["default", "off", "low", "medium", "high"]},
                {"name": "prompt_style", "values": ["strict", "minimal", "schema_guided"]},
            ],
        },
        "meaning": (
            "A catalog entry means a bounded native-tool profile is available, not that every tag will pass. "
            "Compatibility is established only by a passing probe for the current installed digest."
        ),
    }
