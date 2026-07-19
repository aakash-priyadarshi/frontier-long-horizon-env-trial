"""Trusted checkpoint bindings and private-root artifact identity enforcement.

Product evaluation and orchestration prefer a structured binding over a bare
digest string. The binding carries an operator-independent provenance source and
a logical artifact identity under the private root — never a raw absolute path
as the sole trust anchor.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


CHECKPOINT_ARTIFACT_NAME = "checkpoint.pt"


class BindingSource(str, Enum):
    IMMUTABLE_DB_RECORD = "immutable_db_record"
    VERIFIED_MANIFEST = "verified_manifest"
    CLI_OPERATOR_SUPPLIED = "cli_operator_supplied"


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(item in "0123456789abcdef" for item in value[7:])
    )


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def logical_checkpoint_identity(training_run_id: str) -> str:
    if not training_run_id or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for character in training_run_id
    ):
        raise ValueError("invalid training run identifier for artifact identity")
    if ".." in training_run_id or "/" in training_run_id or "\\" in training_run_id:
        raise ValueError("invalid training run identifier for artifact identity")
    return f"{training_run_id}/{CHECKPOINT_ARTIFACT_NAME}"


@dataclass(frozen=True)
class TrustedCheckpointBinding:
    """Provenance-bound checkpoint reference for product evaluation paths."""

    training_run_id: str
    trusted_digest: str
    artifact_identity: str
    binding_source: BindingSource
    offline_dataset_digest: str | None = None
    source_dataset_digest: str | None = None
    checkpoint_id: str | None = None

    def __post_init__(self) -> None:
        if not self.training_run_id:
            raise ValueError("training_run_id is required")
        if not _valid_sha256(self.trusted_digest):
            raise ValueError("trusted checkpoint digest is missing or malformed")
        expected = logical_checkpoint_identity(self.training_run_id)
        if self.artifact_identity != expected:
            raise ValueError("artifact identity does not match training run")
        if self.checkpoint_id is not None and self.checkpoint_id != self.training_run_id:
            raise ValueError("checkpoint_id must match training_run_id")
        if self.offline_dataset_digest is not None and not _valid_sha256(self.offline_dataset_digest):
            raise ValueError("offline dataset digest is missing or malformed")
        if self.source_dataset_digest is not None and not _valid_sha256(self.source_dataset_digest):
            raise ValueError("source dataset digest is missing or malformed")
        if not isinstance(self.binding_source, BindingSource):
            raise ValueError("binding_source is invalid")

    @property
    def effective_checkpoint_id(self) -> str:
        return self.checkpoint_id or self.training_run_id

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "checkpoint_id": self.effective_checkpoint_id,
            "training_run_id": self.training_run_id,
            "artifact_identity": self.artifact_identity,
            "trusted_digest": self.trusted_digest,
            "binding_source": self.binding_source.value,
        }
        if self.offline_dataset_digest is not None:
            payload["offline_dataset_digest"] = self.offline_dataset_digest
        if self.source_dataset_digest is not None:
            payload["source_dataset_digest"] = self.source_dataset_digest
        return payload

    @classmethod
    def from_completed_training(
        cls,
        record: Mapping[str, Any],
        *,
        binding_source: BindingSource = BindingSource.IMMUTABLE_DB_RECORD,
    ) -> "TrustedCheckpointBinding":
        if record.get("kind") != "training" or record.get("status") != "completed":
            raise ValueError("trusted binding requires a completed training record")
        if record.get("checkpoint_unavailable") is True:
            raise ValueError("training checkpoint is marked unavailable")
        run_id = str(record.get("record_id") or record.get("model_id") or "")
        digest = record.get("checkpoint_digest")
        identity = record.get("artifact_identity") or logical_checkpoint_identity(run_id)
        offline_raw = record.get("offline_dataset_digest")
        source_raw = record.get("dataset_digest")
        offline_digest = str(offline_raw) if offline_raw else None
        source_digest = str(source_raw) if source_raw else None
        requires_dataset_bindings = (
            record.get("architecture") == "cql_gru"
            or record.get("algorithm") == "discrete_cql"
            or offline_digest is not None
        )
        if requires_dataset_bindings:
            if offline_digest is None or not _valid_sha256(offline_digest):
                raise ValueError("offline dataset digest is missing or malformed")
            if source_digest is None or not _valid_sha256(source_digest):
                raise ValueError("source dataset digest is missing or malformed")
        elif source_digest is not None and not _valid_sha256(source_digest):
            source_digest = None
        return cls(
            training_run_id=run_id,
            checkpoint_id=run_id,
            trusted_digest=str(digest),
            artifact_identity=str(identity),
            binding_source=binding_source,
            offline_dataset_digest=offline_digest,
            source_dataset_digest=source_digest if _valid_sha256(source_digest) else None,
        )

    @classmethod
    def cli_operator_supplied(
        cls,
        *,
        training_run_id: str,
        trusted_digest: str,
        offline_dataset_digest: str | None = None,
        source_dataset_digest: str | None = None,
    ) -> "TrustedCheckpointBinding":
        return cls(
            training_run_id=training_run_id,
            checkpoint_id=training_run_id,
            trusted_digest=trusted_digest,
            artifact_identity=logical_checkpoint_identity(training_run_id),
            binding_source=BindingSource.CLI_OPERATOR_SUPPLIED,
            offline_dataset_digest=offline_dataset_digest,
            source_dataset_digest=source_dataset_digest,
        )


def _reject_traversal_components(identity: str) -> None:
    normalised = identity.replace("\\", "/")
    parts = [part for part in normalised.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("artifact identity path traversal rejected")
    if normalised.startswith("/") or (len(normalised) >= 2 and normalised[1] == ":"):
        raise ValueError("artifact identity must be a relative logical path")


def _path_is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _reject_symlink_escape(path: Path, root: Path) -> None:
    """Reject symlink escape where practical (including Windows junctions when resolved)."""

    root_resolved = root.resolve()
    current = path
    # Walk parents; resolve each symlink and require it stay under root.
    while True:
        if current.is_symlink():
            target = current.resolve()
            if not _path_is_within(root_resolved, target):
                raise ValueError("artifact symlink escape rejected")
        if current == root_resolved or current.parent == current:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent


def resolve_bound_checkpoint(
    private_root: Path,
    binding: TrustedCheckpointBinding,
    *,
    require_digest_match: bool = True,
) -> Path:
    """Resolve a binding to a checkpoint file under the approved private root.

    Enforces:
    - logical identity only (no absolute path as sole trust);
    - no ``..`` / drive-root traversal;
    - resolved path stays under ``private_root``;
    - path matches the bound training run directory;
    - optional trusted digest match on file bytes.
    """

    if not isinstance(binding, TrustedCheckpointBinding):
        raise TypeError("TrustedCheckpointBinding is required")
    _reject_traversal_components(binding.artifact_identity)
    root = private_root.resolve()
    if not root.is_dir():
        raise ValueError("private artifact root is missing")
    relative = Path(*binding.artifact_identity.replace("\\", "/").split("/"))
    candidate = (private_root / relative)
    # Reject before resolve if any component tries to escape via string form.
    if ".." in candidate.parts:
        raise ValueError("artifact identity path traversal rejected")
    resolved = candidate.resolve()
    if not _path_is_within(root, resolved):
        raise ValueError("checkpoint path is outside the private artifact root")
    expected_parent = (private_root / binding.training_run_id).resolve()
    if resolved.parent != expected_parent:
        raise ValueError("checkpoint path-record mismatch")
    if resolved.name != CHECKPOINT_ARTIFACT_NAME:
        raise ValueError("checkpoint path-record mismatch")
    _reject_symlink_escape(candidate if candidate.exists() else resolved, root)
    if not resolved.is_file():
        raise ValueError("bound checkpoint was not found")
    # Re-check after existence: Windows may resolve through reparse points.
    if not _path_is_within(root, resolved.resolve()):
        raise ValueError("checkpoint path is outside the private artifact root")
    if require_digest_match:
        actual = file_digest(resolved)
        if not hmac.compare_digest(actual, binding.trusted_digest):
            raise ValueError("offline checkpoint digest mismatch")
    return resolved


def require_dataset_bindings(binding: TrustedCheckpointBinding) -> tuple[str, str]:
    """Require both offline and source dataset digests on a product evaluation binding."""

    if not isinstance(binding, TrustedCheckpointBinding):
        raise TypeError("TrustedCheckpointBinding is required")
    offline = binding.offline_dataset_digest
    source = binding.source_dataset_digest
    if offline is None or not _valid_sha256(offline):
        raise ValueError("offline dataset digest is missing or malformed")
    if source is None or not _valid_sha256(source):
        raise ValueError("source dataset digest is missing or malformed")
    return offline, source


def assert_product_checkpoint_usable(
    private_root: Path,
    record: Mapping[str, Any],
) -> TrustedCheckpointBinding:
    """Build a DB binding and fail closed if the artifact is missing or unavailable."""

    binding = TrustedCheckpointBinding.from_completed_training(record)
    resolve_bound_checkpoint(private_root, binding, require_digest_match=True)
    return binding
