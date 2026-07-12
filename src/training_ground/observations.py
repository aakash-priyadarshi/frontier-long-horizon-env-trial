"""Observation building from public gateway responses."""

from __future__ import annotations

from typing import Any


def sanitize_release_status(status: dict[str, Any]) -> dict[str, Any]:
    """Return a public-only observation from a release.status response.

    The release.status response already omits secrets, but we ensure the
    observation is a bounded dict containing only the contract surface.
    """
    keys = (
        "session_id",
        "tick",
        "intake",
        "active_revision",
        "active_source_root",
        "active_config_root",
        "candidate_root",
        "attempt_budget",
        "public_canary",
        "incident",
        "tool_inventory",
        "roots",
    )
    return {k: status[k] for k in keys if k in status}


def error_observation(last_tool: str, error: str) -> dict[str, Any]:
    return {
        "error": error,
        "last_tool": last_tool,
        "incident": "open",
        "public_canary": "green_once",
    }


def is_terminated(status: dict[str, Any]) -> bool:
    return status.get("incident") == "closed" and status.get("public_canary") == "pass"
