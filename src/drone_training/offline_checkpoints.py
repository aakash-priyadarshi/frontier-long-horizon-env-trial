"""Atomic, digest-bound checkpoints for the Talon discrete CQL policy.

Trusted digests are supplied by the caller from an immutable training record (or
an equivalent out-of-band source). Digests embedded inside the checkpoint file
are never used as the trust anchor.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

import torch

from drone_decision_ground.environment import ENVIRONMENT_VERSION
from drone_decision_verifier.scoring import VERIFIER_VERSION

from .features import ACTIONS, FEATURE_DIM, FEATURE_SCHEMA_VERSION
from .manifests import NormalizationStats
from .offline_rl import CQL_ALGORITHM_VERSION, CQLConfig, ConservativeQNetwork, OfflineRLDataset, verify_offline_dataset_integrity


OFFLINE_CHECKPOINT_FORMAT_VERSION = "talon.offline-rl-checkpoint/2.0"
_LEGACY_OFFLINE_CHECKPOINT_FORMAT_VERSION = "talon.offline-rl-checkpoint/1.0"


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(item in "0123456789abcdef" for item in value[7:])
    )


def _require_expected_digest(expected_digest: object) -> str:
    if not _valid_sha256(expected_digest):
        raise ValueError("offline checkpoint digest is missing or malformed")
    return str(expected_digest)


def _compare_digest(actual: str, expected: str) -> None:
    if not hmac.compare_digest(actual, expected):
        raise ValueError("offline checkpoint digest mismatch")


def _payload(path: Path) -> dict[str, Any]:
    try:
        value = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as exc:
        raise ValueError("offline checkpoint is incomplete or invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("unsupported offline checkpoint format")
    format_version = value.get("format_version")
    if format_version == _LEGACY_OFFLINE_CHECKPOINT_FORMAT_VERSION:
        raise ValueError("unsupported offline checkpoint format")
    if format_version != OFFLINE_CHECKPOINT_FORMAT_VERSION:
        raise ValueError("unsupported offline checkpoint format")
    return value


def save_offline_checkpoint(
    path: Path,
    *,
    model: ConservativeQNetwork,
    target: ConservativeQNetwork,
    dataset: OfflineRLDataset,
    config: CQLConfig,
    training_history: dict[str, list[float]],
    training_updates: int | None = None,
    should_abort: Callable[[], bool] | None = None,
    _test_barrier: Callable[[str], None] | None = None,
) -> str:
    """Atomically publish an offline checkpoint.

    Private testing may pass ``_test_barrier(phase)`` for race injection. Phases:
    ``after_temp_write``, ``before_publish``, ``after_publish``. Not a public API.
    ``should_abort`` is re-checked after temp validation and before the hard-link
    publish; when true the partial is discarded and ``InterruptedError`` is raised.
    """

    verified = verify_offline_dataset_integrity(dataset)
    config.validate()
    if path.exists():
        raise FileExistsError("offline checkpoint already exists")
    if set(model.state_dict()) != set(target.state_dict()):
        raise ValueError("online and target network architectures are incompatible")
    updates = training_updates
    if updates is None:
        # Prefer an explicit count; otherwise derive from logged epoch metrics.
        updates = sum(len(values) for values in training_history.values()) // max(1, len(training_history)) if training_history else 0
    payload = {
        "format_version": OFFLINE_CHECKPOINT_FORMAT_VERSION,
        "algorithm_version": CQL_ALGORITHM_VERSION,
        "architecture": "cql_gru",
        "model_config": dict(model.config),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_dim": FEATURE_DIM,
        "actions": [item.value for item in ACTIONS],
        "offline_dataset_digest": verified.manifest.dataset_digest,
        "source_dataset_digest": verified.manifest.source_dataset_digest,
        "dataset_digest_verification": "recomputed",
        "training_instance_digests": list(verified.manifest.instance_digests),
        "seed_domain_digest": verified.manifest.seed_domain_digest,
        "environment_version": ENVIRONMENT_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "normalization": verified.manifest.normalization.model_dump(mode="json"),
        "context_length": config.context_length,
        "safety_threshold": config.safety_threshold,
        "training_config": config.__dict__,
        "training_updates": int(updates),
        "final_training_metrics": {key: value[-1] for key, value in training_history.items() if value},
        "online_state_dict": model.state_dict(),
        "target_state_dict": target.state_dict(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            torch.save(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        _payload(temporary)
        expected = _digest(temporary)
        if _test_barrier is not None:
            _test_barrier("after_temp_write")
        if should_abort is not None and should_abort():
            raise InterruptedError("offline checkpoint publish aborted before link")
        if _test_barrier is not None:
            _test_barrier("before_publish")
        if should_abort is not None and should_abort():
            raise InterruptedError("offline checkpoint publish aborted before link")
        os.link(temporary, path)
        if not hmac.compare_digest(_digest(path), expected):
            path.unlink(missing_ok=True)
            raise OSError("offline checkpoint changed during atomic publication")
        temporary.unlink()
        path.chmod(0o444)
        if _test_barrier is not None:
            _test_barrier("after_publish")
        return expected
    finally:
        if temporary.exists():
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            temporary.unlink(missing_ok=True)


def load_offline_checkpoint(
    path: Path,
    *,
    expected_digest: str,
    expected_offline_dataset_digest: str | None = None,
    expected_source_dataset_digest: str | None = None,
    expected_actions: list[str] | tuple[str, ...] | None = None,
    expected_algorithm_version: str | None = None,
    expected_feature_schema_version: str | None = None,
    expected_gamma: float | None = None,
    expected_cql_alpha: float | None = None,
    expected_safety_threshold: float | None = None,
) -> tuple[ConservativeQNetwork, ConservativeQNetwork, dict[str, Any]]:
    trusted = _require_expected_digest(expected_digest)
    if not path.is_file():
        raise ValueError("offline checkpoint was not found")
    # Digest of file bytes is the only trust anchor; reject before deserialising.
    actual = _digest(path)
    _compare_digest(actual, trusted)
    payload = _payload(path)
    if payload.get("algorithm_version") != CQL_ALGORITHM_VERSION or payload.get("architecture") != "cql_gru":
        raise ValueError("offline checkpoint algorithm is incompatible")
    if payload.get("feature_schema_version") != FEATURE_SCHEMA_VERSION or payload.get("feature_dim") != FEATURE_DIM:
        raise ValueError("offline checkpoint feature schema is incompatible")
    if payload.get("actions") != [item.value for item in ACTIONS]:
        raise ValueError("offline checkpoint action schema is incompatible")
    if payload.get("environment_version") != ENVIRONMENT_VERSION:
        raise ValueError("offline checkpoint environment compatibility is incompatible")
    if payload.get("verifier_version") != VERIFIER_VERSION:
        raise ValueError("offline checkpoint verifier compatibility is incompatible")
    for key in ("offline_dataset_digest", "source_dataset_digest", "seed_domain_digest"):
        if not _valid_sha256(payload.get(key)):
            raise ValueError("offline checkpoint dataset binding is invalid")
    if payload.get("dataset_digest_verification") != "recomputed":
        raise ValueError("offline checkpoint lacks authoritative dataset verification")
    training_config = payload.get("training_config")
    if not isinstance(training_config, dict):
        raise ValueError("offline checkpoint training configuration is invalid")
    if expected_offline_dataset_digest is not None:
        if not _valid_sha256(expected_offline_dataset_digest) or not hmac.compare_digest(
            str(payload["offline_dataset_digest"]), expected_offline_dataset_digest
        ):
            raise ValueError("offline checkpoint offline-dataset binding mismatch")
    if expected_source_dataset_digest is not None:
        if not _valid_sha256(expected_source_dataset_digest) or not hmac.compare_digest(
            str(payload["source_dataset_digest"]), expected_source_dataset_digest
        ):
            raise ValueError("offline checkpoint source-dataset binding mismatch")
    if expected_actions is not None and list(payload.get("actions") or []) != list(expected_actions):
        raise ValueError("offline checkpoint action schema is incompatible")
    if expected_algorithm_version is not None and payload.get("algorithm_version") != expected_algorithm_version:
        raise ValueError("offline checkpoint algorithm is incompatible")
    if expected_feature_schema_version is not None and payload.get("feature_schema_version") != expected_feature_schema_version:
        raise ValueError("offline checkpoint feature schema is incompatible")
    if expected_gamma is not None and float(training_config.get("gamma", float("nan"))) != float(expected_gamma):
        raise ValueError("offline checkpoint training configuration mismatch")
    if expected_cql_alpha is not None and float(training_config.get("cql_alpha", float("nan"))) != float(expected_cql_alpha):
        raise ValueError("offline checkpoint training configuration mismatch")
    if expected_safety_threshold is not None:
        stored_threshold = payload.get("safety_threshold", training_config.get("safety_threshold"))
        if float(stored_threshold) != float(expected_safety_threshold):
            raise ValueError("offline checkpoint training configuration mismatch")
    normalization = NormalizationStats.model_validate(payload.get("normalization"))
    if len(normalization.mean) != FEATURE_DIM or len(normalization.scale) != FEATURE_DIM or len(normalization.normalization_mask) != FEATURE_DIM:
        raise ValueError("offline checkpoint normalization is incompatible")
    model_config = payload.get("model_config")
    if not isinstance(model_config, dict):
        raise ValueError("offline checkpoint model configuration is invalid")
    online_weights = payload.get("online_state_dict")
    target_weights = payload.get("target_state_dict")
    if not isinstance(online_weights, dict) or not isinstance(target_weights, dict):
        raise ValueError("offline checkpoint weights do not match metadata")
    model = ConservativeQNetwork(**model_config)
    target = ConservativeQNetwork(**model_config)
    try:
        model.load_state_dict(online_weights, strict=True)
        target.load_state_dict(target_weights, strict=True)
    except Exception as exc:
        raise ValueError("offline checkpoint weights do not match metadata") from exc
    model.eval()
    target.eval()
    metadata = {
        key: value
        for key, value in payload.items()
        if key not in {"online_state_dict", "target_state_dict", "state_dict"}
    }
    metadata["normalization"] = normalization.model_dump(mode="json")
    # Report the verified file digest; never promote an embedded trust claim.
    metadata["checkpoint_digest"] = actual
    return model, target, metadata


def inspect_offline_checkpoint(
    path: Path,
    *,
    expected_digest: str,
    expected_offline_dataset_digest: str | None = None,
    expected_source_dataset_digest: str | None = None,
) -> dict[str, Any]:
    model, target, metadata = load_offline_checkpoint(
        path,
        expected_digest=expected_digest,
        expected_offline_dataset_digest=expected_offline_dataset_digest,
        expected_source_dataset_digest=expected_source_dataset_digest,
    )
    metadata["parameter_count"] = sum(item.numel() for item in model.parameters())
    metadata["target_parameter_count"] = sum(item.numel() for item in target.parameters())
    return metadata
