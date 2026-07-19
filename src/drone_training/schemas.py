"""Strict public requests for local Talon jobs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed_start: int = Field(default=0, ge=0, le=2_147_483_647)
    seed_count: int = Field(default=1, ge=1, le=100)
    timeout_seconds: int = Field(default=60, ge=1, le=900)


class TrainingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(pattern=r"^dataset_[a-f0-9]{24}$")
    architecture: Literal["gru", "decision_transformer"]
    epochs: int = Field(default=20, ge=1, le=500)
    learning_rate: float = Field(default=1e-3, gt=0, le=1)
    batch_size: int = Field(default=32, ge=1, le=4096)
    context_length: int = Field(default=20, ge=1, le=64)
    random_seed: int = Field(default=0, ge=0, le=2_147_483_647)
    timeout_seconds: int = Field(default=300, ge=1, le=3_600)


class OfflineRLTrainingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(pattern=r"^dataset_[a-f0-9]{24}$")
    context_length: int = Field(default=20, ge=1, le=64)
    hidden_dim: int = Field(default=256, ge=8, le=2_048)
    layers: int = Field(default=2, ge=1, le=12)
    dropout: float = Field(default=0.1, ge=0, lt=1)
    gamma: float = Field(default=0.99, ge=0, le=1)
    cql_alpha: float = Field(default=1.0, ge=0, le=100)
    safety_threshold: float = Field(default=0.05, ge=0, le=1)
    learning_rate: float = Field(default=3e-4, gt=0, le=1)
    batch_size: int = Field(default=128, ge=1, le=4_096)
    epochs: int = Field(default=50, ge=1, le=500)
    target_update_interval: int = Field(default=500, ge=1, le=1_000_000)
    gradient_clip: float = Field(default=1.0, gt=0, le=100)
    random_seed: int = Field(default=0, ge=0, le=2_147_483_647)
    timeout_seconds: int = Field(default=900, ge=1, le=7_200)


class EvaluationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    training_run_id: str = Field(pattern=r"^talon_(?:train|cql)_[a-f0-9]{32}$")
    seed_start: int = Field(default=0, ge=0, le=2_147_483_647)
    seed_count: int = Field(default=1, ge=1, le=20)
    timeout_seconds: int = Field(default=120, ge=1, le=1_800)


class ApprovalDemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["valid", "replay"]


class ComparisonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluation_ids: tuple[str, ...] = Field(min_length=2, max_length=8)
