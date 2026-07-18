"""Atomic, digest-bound Talon policy checkpoint persistence."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

try:
    import torch
    from torch import nn
except ImportError as exc:  # pragma: no cover - dependency guard
    raise ImportError("Talon checkpoints require the optional 'talon' dependency") from exc

from .decision_transformer import DecisionTransformerPolicy
from .features import ACTIONS, FEATURE_DIM, FEATURE_SCHEMA_VERSION
from .gru_policy import GRUPolicy
from .manifests import NormalizationStats


CHECKPOINT_FORMAT_VERSION = "talon.checkpoint/2.0"


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _validated_payload(path: Path) -> dict[str, Any]:
    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as exc:
        raise ValueError("checkpoint is incomplete or invalid") from exc
    if not isinstance(payload, dict) or payload.get("format_version") != CHECKPOINT_FORMAT_VERSION:
        raise ValueError("unsupported checkpoint format")
    return payload


def save_checkpoint(
    path: Path,
    *,
    model: nn.Module,
    architecture: str,
    dataset_digest: str,
    context_length: int,
    normalization: NormalizationStats,
    training_instance_digests: tuple[str, ...],
    seed_domain_digest: str,
    return_conditioning_target: float,
) -> str:
    if (
        not dataset_digest.startswith("sha256:")
        or len(dataset_digest) != 71
        or any(character not in "0123456789abcdef" for character in dataset_digest[7:])
    ):
        raise ValueError("verified dataset digest is invalid")
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": CHECKPOINT_FORMAT_VERSION,
        "architecture": architecture,
        "model_config": dict(getattr(model, "config")),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_dim": FEATURE_DIM,
        "actions": [action.value for action in ACTIONS],
        "dataset_digest": dataset_digest,
        "training_instance_digests": list(training_instance_digests),
        "seed_domain_digest": seed_domain_digest,
        "normalization": normalization.model_dump(mode="json"),
        "context_length": context_length,
        "return_conditioning_target": float(return_conditioning_target),
        "state_dict": model.state_dict(),
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            torch.save(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        _validated_payload(temporary)
        temporary_digest = file_digest(temporary)
        # A hard-link publish is atomic and fails rather than replacing an
        # existing immutable checkpoint.
        os.link(temporary, path)
        if file_digest(path) != temporary_digest:
            path.unlink(missing_ok=True)
            raise OSError("checkpoint digest changed during atomic publication")
        temporary.unlink()
        path.chmod(0o444)
        return temporary_digest
    finally:
        if temporary.exists():
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            temporary.unlink(missing_ok=True)


def load_checkpoint(path: Path, *, expected_digest: str | None = None) -> tuple[nn.Module, dict[str, Any]]:
    if not path.is_file():
        raise ValueError("checkpoint was not found")
    actual_digest = file_digest(path)
    if expected_digest is not None and actual_digest != expected_digest:
        raise ValueError("checkpoint digest mismatch")
    payload = _validated_payload(path)
    if payload.get("feature_dim") != FEATURE_DIM or payload.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise ValueError("checkpoint observation feature schema is incompatible")
    if payload.get("actions") != [action.value for action in ACTIONS]:
        raise ValueError("checkpoint action schema is incompatible")
    normalization = NormalizationStats.model_validate(payload.get("normalization"))
    target_return = payload.get("return_conditioning_target")
    if not isinstance(target_return, (int, float)) or not -1.0 <= float(target_return) <= 1.0:
        raise ValueError("checkpoint return-conditioning target is invalid")
    if (
        len(normalization.mean) != FEATURE_DIM
        or len(normalization.scale) != FEATURE_DIM
        or len(normalization.normalization_mask) != FEATURE_DIM
    ):
        raise ValueError("checkpoint normalization is incompatible")
    dataset_digest = payload.get("dataset_digest")
    if (
        not isinstance(dataset_digest, str)
        or not dataset_digest.startswith("sha256:")
        or len(dataset_digest) != 71
        or any(character not in "0123456789abcdef" for character in dataset_digest[7:])
    ):
        raise ValueError("checkpoint dataset binding is invalid")
    digests = payload.get("training_instance_digests")
    if not isinstance(digests, list) or not digests or any(
        not isinstance(value, str) or not value.startswith("sha256:") for value in digests
    ):
        raise ValueError("checkpoint training-instance binding is invalid")
    architecture = payload.get("architecture")
    config = payload.get("model_config")
    if not isinstance(config, dict):
        raise ValueError("checkpoint model configuration is invalid")
    if architecture == "gru":
        model: nn.Module = GRUPolicy(**config)
    elif architecture == "decision_transformer":
        model = DecisionTransformerPolicy(**config)
    else:
        raise ValueError("unknown checkpoint architecture")
    try:
        model.load_state_dict(payload["state_dict"], strict=True)
    except Exception as exc:
        raise ValueError("checkpoint weights do not match metadata") from exc
    model.eval()
    metadata = {key: value for key, value in payload.items() if key != "state_dict"}
    metadata["normalization"] = normalization.model_dump(mode="json")
    metadata["checkpoint_digest"] = actual_digest
    return model, metadata


def inspect_checkpoint(path: Path) -> dict[str, Any]:
    model, metadata = load_checkpoint(path)
    metadata["parameter_count"] = sum(parameter.numel() for parameter in model.parameters())
    return metadata
