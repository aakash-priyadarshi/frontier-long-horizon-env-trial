"""Reconstruct candidate artifacts from the session directory."""

from __future__ import annotations

from pathlib import Path

from event_service_substrate.canonical import tree_root
from event_service_substrate.instance import CODE_FILES


def active_workspace(session_dir: Path) -> Path:
    return session_dir / "active"


def candidate_workspace(session_dir: Path) -> Path:
    return session_dir / "candidate"


def initial_workspace(session_dir: Path) -> Path:
    return session_dir / "initial"


def workspace_root(workspace: Path) -> str | None:
    if not workspace.is_dir():
        return None
    try:
        return tree_root(workspace, CODE_FILES)
    except Exception:
        return None


def config_root(workspace: Path) -> str | None:
    from event_service_substrate.canonical import digest

    settings = workspace / "service" / "settings.toml"
    if not settings.is_file():
        return None
    return digest("config-v1", settings.read_bytes())


def candidate_is_deployed(active_root: str | None, candidate_root: str | None) -> bool:
    return active_root is not None and candidate_root is not None and active_root == candidate_root
