"""Internal provider-neutral model protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class ModelMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: tuple["ModelToolCall", ...] = ()


@dataclass(frozen=True)
class ModelTool:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ModelToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelRequestConfig:
    model: str
    temperature: float | None = None
    max_output_tokens: int = 4096
    reasoning_effort: str | None = None
    timeout_seconds: float = 60.0
    max_retries: int = 2
    deterministic: bool = False
    custom_headers: dict[str, str] = field(default_factory=dict)
    input_token_price_per_million: float | None = None
    output_token_price_per_million: float | None = None


@dataclass(frozen=True)
class ModelResponse:
    text: str = ""
    tool_calls: tuple[ModelToolCall, ...] = ()
    provider_request_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    latency_ms: float = 0.0
    estimated_cost: float | None = None
    finish_reason: str | None = None


@runtime_checkable
class ModelAdapter(Protocol):
    provider: str

    async def complete(
        self,
        *,
        messages: list[ModelMessage],
        tools: list[ModelTool],
        config: ModelRequestConfig,
    ) -> ModelResponse: ...
