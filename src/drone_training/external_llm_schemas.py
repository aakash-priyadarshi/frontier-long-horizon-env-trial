"""Schemas for first-class external-LLM / scripted-external TALON evaluations."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


PROMPT_VERSION = "talon-llm-policy/1.0"
PROVIDER_ADAPTER_VERSION = "frontier.openai-compatible/1.0"
EXTERNAL_POLICY_SCHEMA_VERSION = "talon.external-llm-policy/1.0"
MAX_DECISION_SUMMARY_CHARS = 240
MAX_RESPONSE_BYTES = 4_096
MAX_EVIDENCE_REFS = 8


class ExternalLLMEvaluationCreate(BaseModel):
    """Additive product request for external or scripted-external evaluations."""

    model_config = ConfigDict(extra="forbid")

    policy_kind: Literal["external_llm", "scripted_external_baseline"]
    provider: Literal["openai_compatible", "scripted_external"]
    model: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:/-]+$")
    prompt_version: Literal["talon-llm-policy/1.0"] = PROMPT_VERSION
    temperature: float = Field(default=0.0, ge=0.0, le=0.0)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_output_tokens: int = Field(default=300, ge=32, le=1_024)
    attempts_per_scenario: int = Field(default=1, ge=1, le=1)
    scenario_partition: Literal["evaluation"] = "evaluation"
    seed_start: int = Field(default=0, ge=0, le=2_147_483_647)
    seed_count: int = Field(default=1, ge=1, le=20)

    @model_validator(mode="after")
    def provider_matches_policy(self) -> Self:
        if self.policy_kind == "external_llm" and self.provider != "openai_compatible":
            raise ValueError("external_llm requires openai_compatible provider in V1")
        if self.policy_kind == "scripted_external_baseline" and self.provider != "scripted_external":
            raise ValueError("scripted_external_baseline requires scripted_external provider")
        if self.provider == "scripted_external" and self.model not in {
            "scripted-valid",
            "scripted-malformed",
            "valid",
            "malformed",
            "scripted_valid",
            "scripted_malformed",
        }:
            raise ValueError("scripted_external model must be scripted-valid or scripted-malformed")
        return self


class ExternalLLMResponseContract(BaseModel):
    """Strict JSON object required from the external model."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    action: str = Field(min_length=1, max_length=64)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=MAX_EVIDENCE_REFS)
    decision_summary: str = Field(min_length=1, max_length=MAX_DECISION_SUMMARY_CHARS)
