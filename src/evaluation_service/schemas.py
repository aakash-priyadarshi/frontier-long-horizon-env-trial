"""Typed API and persistence schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ModelConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int = Field(default=4096, ge=1, le=131_072)
    context_window: int | None = Field(default=None, ge=4_096, le=262_144)
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    timeout_seconds: float = Field(default=60, ge=1, le=900)
    max_retries: int = Field(default=2, ge=0, le=10)
    deterministic: bool = False
    input_token_price_per_million: float | None = Field(default=None, ge=0)
    output_token_price_per_million: float | None = Field(default=None, ge=0)


class EvaluationLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=64, ge=1, le=256)
    max_model_calls: int = Field(default=64, ge=1, le=256)
    input_token_budget: int | None = Field(default=None, ge=1)
    output_token_budget: int | None = Field(default=None, ge=1)
    cost_budget: float | None = Field(default=None, ge=0)
    wall_clock_seconds: float | None = Field(default=600, ge=1, le=86_400)


class EvaluationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["scripted", "openai-compatible", "anthropic", "gemini", "ollama"]
    model: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:/-]+$")
    split: Literal["train", "dev", "eval"] = "eval"
    seed_start: int = Field(default=0, ge=0, le=2_147_483_647)
    seed_count: int = Field(default=1, ge=1, le=100)
    attempts: int = Field(default=1, ge=1, le=20)
    concurrency: int = Field(default=1, ge=1, le=8)
    model_configuration: ModelConfiguration = Field(default_factory=ModelConfiguration)
    limits: EvaluationLimits = Field(default_factory=EvaluationLimits)

    @model_validator(mode="after")
    def validate_scripted_model(self) -> "EvaluationCreate":
        if self.provider == "scripted" and self.model not in {"scripted-valid", "scripted-wrong-control"}:
            raise ValueError("scripted provider requires a supported scripted model")
        if self.seed_count * self.attempts > 200:
            raise ValueError("an evaluation may contain at most 200 episodes")
        return self


class ProviderSessionConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential: SecretStr | None = Field(default=None, max_length=16_384)
    base_url: str | None = Field(default=None, max_length=2_048)
    persist: bool = False

    @model_validator(mode="after")
    def require_update(self) -> "ProviderSessionConfiguration":
        if not self.model_fields_set.intersection({"credential", "base_url"}):
            raise ValueError("credential or base_url is required")
        if "credential" in self.model_fields_set and self.credential is None:
            raise ValueError("credential cannot be null")
        return self


class ProviderToolProbeOptions(BaseModel):
    """Bounded, non-secret options for the isolated Ollama fake-tool probe."""

    model_config = ConfigDict(extra="forbid")

    context_window: int = Field(default=16_384, ge=4_096, le=262_144)
    max_output_tokens: int = Field(default=512, ge=128, le=8_192)
    retry_output_tokens: int | None = Field(default=2_048, ge=128, le=8_192)
    timeout_seconds: int = Field(default=120, ge=10, le=300)
    temperature: float = Field(default=0, ge=0, le=2)
    thinking: Literal["default", "off", "low", "medium", "high"] = "off"
    prompt_style: Literal["strict", "minimal", "schema_guided"] = "strict"

    @model_validator(mode="after")
    def validate_retry_budget(self) -> "ProviderToolProbeOptions":
        if self.retry_output_tokens is not None and self.retry_output_tokens < self.max_output_tokens:
            raise ValueError("retry_output_tokens must be at least max_output_tokens")
        return self


class ProviderToolProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:/-]+$")
    options: ProviderToolProbeOptions | None = None


class BatchSummary(BaseModel):
    batch_id: str
    created_at: str
    updated_at: str
    status: str
    provider: str
    model: str
    split: str
    seed_start: int
    seed_count: int
    attempts: int
    total_runs: int
    completed_runs: int
    failed_runs: int
    cancelled_runs: int
    aggregate_results: dict[str, Any]
    environment_commit: str
    application_commit: str


class Page(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class APIError(BaseModel):
    error: dict[str, str]
