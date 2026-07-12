"""Episode loader and environment factory."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from .episode import IncidentEnv
from .manifests import Manifest, build_manifest


def load_environment(
    split: str = "train",
    seed: int = 0,
    *,
    options: dict[str, Any] | None = None,
    work_dir: Path | str | None = None,
) -> IncidentEnv:
    """Load a deterministic training or evaluation environment."""
    options = options or {}
    manifest = build_manifest(split, seed)
    profile = options.get("profile")
    if profile is not None:
        manifest = replace(manifest, profile=profile)
    max_steps = options.get("max_steps")
    return IncidentEnv(manifest, work_dir=work_dir, max_steps=max_steps)


def load_environment_from_manifest(
    manifest: Manifest,
    *,
    options: dict[str, Any] | None = None,
    work_dir: Path | str | None = None,
) -> IncidentEnv:
    options = options or {}
    return IncidentEnv(manifest, work_dir=work_dir, max_steps=options.get("max_steps"))
