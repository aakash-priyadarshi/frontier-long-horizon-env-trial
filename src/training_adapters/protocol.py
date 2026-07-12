"""Shared adapter protocol for evaluated-agent tool calls.

The wire format matches the existing JSON-lines gateway:

    request:  {"id": str, "tool": str, "arguments": object}
    response: {"id": str, "result": ...} | {"id": str, "error": {"code": str, "message": str}}

Only the twelve inventory tools are agent-legal. Control tools such as
``system.close`` and ``system.leak_probe`` remain harness-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

PROTOCOL_VERSION = "1.0.0"

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

HARNESS_ONLY_TOOLS: tuple[str, ...] = (
    "system.close",
    "system.leak_probe",
)


@dataclass(frozen=True)
class AdapterRequest:
    """One evaluated-agent tool invocation."""

    id: str
    tool: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "protocol_version": PROTOCOL_VERSION,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AdapterRequest:
        return cls(
            id=str(payload.get("id", "")),
            tool=str(payload.get("tool", "")),
            arguments=dict(payload.get("arguments") or {}),
        )


@dataclass(frozen=True)
class AdapterResponse:
    """Sanitized tool response suitable for training and external harnesses."""

    id: str
    ok: bool
    result: Any = None
    error_code: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.ok:
            return {"id": self.id, "result": self.result, "protocol_version": PROTOCOL_VERSION}
        return {
            "id": self.id,
            "error": {"code": self.error_code or "tool_error", "message": self.error_message or "tool error"},
            "protocol_version": PROTOCOL_VERSION,
        }
