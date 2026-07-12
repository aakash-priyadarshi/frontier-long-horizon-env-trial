"""Action validation and dispatch for the twelve bounded environment tools."""

from __future__ import annotations

from typing import Any

from agent_surface.errors import ToolError
from agent_surface.gateway import ToolClient

from .protocol import EnvironmentError

ALLOWED_TOOLS: tuple[str, ...] = (
    "release.status",
    "workspace.read",
    "workspace.edit",
    "telemetry.logs",
    "telemetry.trace",
    "state.inspect",
    "runtime.run",
    "recovery.pause",
    "recovery.restore",
    "release.rollback",
    "release.deploy",
    "recovery.resume",
)

_ALLOWED_ACTION_KEYS = frozenset({"tool", "arguments"})


def validate_action(action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Validate the action shape and return the normalized tool/arguments."""
    if not isinstance(action, dict):
        raise EnvironmentError("action must be a dict", code="invalid_action")
    extra = set(action.keys()) - _ALLOWED_ACTION_KEYS
    if extra:
        raise EnvironmentError(
            f"action contains unsupported fields: {sorted(extra)}",
            code="invalid_action",
        )
    tool = action.get("tool")
    if not isinstance(tool, str):
        raise EnvironmentError("action must contain a string 'tool' field", code="invalid_action")
    if tool not in ALLOWED_TOOLS:
        raise EnvironmentError(f"tool {tool!r} is not in the allowed inventory", code="unknown_tool")
    if "arguments" not in action:
        arguments: Any = {}
    else:
        arguments = action["arguments"]
    if not isinstance(arguments, dict):
        raise EnvironmentError("action 'arguments' must be a dict", code="invalid_arguments")
    return tool, arguments


def _client_method(client: ToolClient, tool: str) -> Any:
    name = tool.replace(".", "_")
    method = getattr(client, name, None)
    if method is None:
        raise EnvironmentError(f"tool {tool} is not supported by this client")
    return method


def dispatch_action(client: ToolClient, tool: str, arguments: dict[str, Any]) -> Any:
    """Dispatch a validated tool call to the process-separated gateway client."""
    method = _client_method(client, tool)
    try:
        return method(**arguments)
    except ToolError as exc:
        raise EnvironmentError(f"{tool}: {exc.code}: {exc}", code=exc.code) from exc


def is_allowed_tool(tool: str) -> bool:
    return tool in ALLOWED_TOOLS


def action_bytes(action: dict[str, Any]) -> int:
    """Return a deterministic byte count for an action."""
    import json

    return len(json.dumps(action, sort_keys=True, ensure_ascii=True).encode("utf-8"))


def result_bytes(result: Any) -> int:
    """Return a deterministic byte count for a result."""
    import json

    return len(json.dumps(result, default=str, sort_keys=True, ensure_ascii=True).encode("utf-8"))
