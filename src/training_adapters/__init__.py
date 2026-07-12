"""Training and interoperability adapters for the incident-service environment.

This package wraps the process-separated agent gateway for Gymnasium rollouts and
APEX-SWE task packaging. It does not expose privileged substrate objects.
"""

from __future__ import annotations

from .protocol import (
    ALLOWED_TOOLS,
    AdapterRequest,
    AdapterResponse,
    PROTOCOL_VERSION,
)
from .sanitize import sanitize_payload
from .tools import ToolFilter, ToolFilterError

__all__ = [
    "ALLOWED_TOOLS",
    "AdapterRequest",
    "AdapterResponse",
    "PROTOCOL_VERSION",
    "ToolFilter",
    "ToolFilterError",
    "sanitize_payload",
]
