"""Canonical digest helpers and immutable Talon artifact manifests."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def content_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class NormalizationStats(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal["talon.normalization/2.0"] = "talon.normalization/2.0"
    fitted_partition: Literal["train"] = "train"
    feature_schema_version: str
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    normalization_mask: tuple[bool, ...]
    sample_count: int = Field(ge=1)


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["talon.private-dataset-manifest/3.0"] = "talon.private-dataset-manifest/3.0"
    dataset_id: str = Field(pattern=r"^dataset_[a-f0-9]{24}$")
    dataset_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    generator_partition: Literal["train", "validation", "evaluation"]
    seed_domain_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    scenario_families: tuple[str, ...]
    seeds: tuple[int, ...]
    scenario_instance_digests: tuple[str, ...]
    trajectory_count: int = Field(ge=1)
    observation_schema_version: str
    action_schema_version: str
    scenario_generator_version: str
    dataset_generator_version: Literal["talon.dataset-generator/3.0"] = "talon.dataset-generator/3.0"
    feature_schema_version: str
    feature_order_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    action_vocabulary: tuple[str, ...]
    normalization: NormalizationStats | None = None


class TrainingManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "talon.private-training-manifest/2.0"
    training_run_id: str
    dataset_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    dataset_digest_verification: Literal["recomputed"] = "recomputed"
    generator_partition: Literal["train"] = "train"
    training_instance_digests: tuple[str, ...]
    seed_domain_digest: str
    scenario_generator_commit: str
    environment_commit: str
    observation_schema_version: str
    action_schema_version: Literal["talon.action/3.0"]
    policy_gate_version: str
    verifier_version: str
    architecture: Literal["gru", "decision_transformer"]
    parameter_count: int = Field(ge=1)
    random_seed: int = Field(ge=0)
    optimiser: str
    learning_rate: float = Field(gt=0)
    batch_size: int = Field(ge=1)
    epochs: int = Field(ge=1)
    checkpoint_digest: str
    hardware: str
    software_versions: dict[str, str]


class EvaluationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "talon.private-evaluation-manifest/2.0"
    evaluation_id: str
    model_checkpoint_digest: str
    evaluation_instance_digests: tuple[str, ...]
    environment_commit: str
    verifier_commit: str
    verifier_version: str
    observation_schema_version: str
    action_schema_version: Literal["talon.action/3.0"]
    maximum_steps: int = Field(ge=8, le=64)
    timeout_seconds: int = Field(ge=1, le=300)
    deterministic: bool = True
    result_digest: str


def write_immutable_json(path: Path, payload: BaseModel | dict[str, Any]) -> None:
    """Atomically create an immutable JSON artifact without replacing a file."""

    value = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise FileExistsError(path)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
