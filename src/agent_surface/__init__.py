"""Agent-visible interaction surface and deterministic runtime harness.

The ``agent_surface`` package provides the process-separated JSON tool gateway
that is the evaluated agent's only supported interface. The internal
AgentSession is not exported as part of the agent-facing API.
"""

from __future__ import annotations

from typing import Any

from .errors import ToolError

__all__ = ["ToolClient", "ToolError", "ToolGateway"]


def __getattr__(name: str) -> Any:
    if name == "ToolClient" or name == "ToolGateway":
        from .gateway import ToolClient, ToolGateway

        return ToolClient if name == "ToolClient" else ToolGateway
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
