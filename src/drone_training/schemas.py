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


class EvaluationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    training_run_id: str = Field(pattern=r"^talon_train_[a-f0-9]{32}$")
    seed_start: int = Field(default=0, ge=0, le=2_147_483_647)
    seed_count: int = Field(default=1, ge=1, le=20)
    timeout_seconds: int = Field(default=120, ge=1, le=1_800)


class ApprovalDemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["valid", "replay"]
