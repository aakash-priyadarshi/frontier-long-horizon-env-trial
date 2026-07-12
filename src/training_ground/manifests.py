"""Deterministic task manifests and split namespaces."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .authority import profile_for_seed
from .limits import Limits
from .protocol import ENVIRONMENT_VERSION, MANIFEST_SCHEMA_VERSION


SPLIT_OFFSETS: dict[str, int] = {
    "train": 0,
    "dev": 1_000_000_000,
    "eval": 2_000_000_000,
}


@dataclass(frozen=True)
class Manifest:
    """Public instance metadata. The privileged profile is not serializable."""

    instance_id: str
    split: str
    seed: int
    public_task_digest: str
    limits: Limits = field(default_factory=Limits)
    version: str = ENVIRONMENT_VERSION
    schema_version: str = MANIFEST_SCHEMA_VERSION
    profile: int = field(default=0, repr=False, compare=False)

    def public(self) -> dict[str, Any]:
        return {
            "environment_version": self.version,
            "manifest_schema": self.schema_version,
            "public_instance_id": self.instance_id,
            "split": self.split,
            "seed": self.seed,
            "public_task_digest": self.public_task_digest,
            "limits": self.limits.to_dict(),
        }


def build_manifest(split: str, seed: int) -> Manifest:
    """Build a deterministic, pair-blind manifest and the private profile."""
    if split not in SPLIT_OFFSETS:
        raise ValueError(f"unknown split {split}")
    effective_seed = seed + SPLIT_OFFSETS[split]
    instance_id = "instance-" + hashlib.sha256(
        f"{ENVIRONMENT_VERSION}-{split}-{effective_seed}".encode("utf-8")
    ).hexdigest()[:24]
    public_task_digest = "task-" + hashlib.sha256(
        f"Q-41-{split}-{effective_seed}".encode("utf-8")
    ).hexdigest()[:32]
    profile = profile_for_seed(split, effective_seed)
    return Manifest(
        instance_id=instance_id,
        split=split,
        seed=seed,
        public_task_digest=public_task_digest,
        limits=Limits(),
        profile=profile,
    )


def list_instance_ids(split: str, count: int) -> list[str]:
    return [build_manifest(split, seed).instance_id for seed in range(count)]
