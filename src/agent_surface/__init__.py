"""Agent-visible interaction surface and deterministic runtime harness.

The ``agent_surface`` package is the harness that implements the Milestone 2
bounded tool interface. It is not part of the agent's editable workspace.
"""

from .errors import ToolError
from .session import AgentSession

__all__ = ["AgentSession", "ToolError"]
