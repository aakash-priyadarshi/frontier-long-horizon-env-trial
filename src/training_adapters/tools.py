"""Strict twelve-tool filtering for evaluated-agent actions."""

from __future__ import annotations

from typing import Any, Mapping

from .protocol import ALLOWED_TOOLS, HARNESS_ONLY_TOOLS, AdapterRequest


class ToolFilterError(ValueError):
    """Raised when a tool name is outside the evaluated-agent inventory."""

    def __init__(self, tool: str, *, code: str = "unknown_tool") -> None:
        self.tool = tool
        self.code = code
        super().__init__(f"tool not permitted: {tool}")


class ToolFilter:
    """Allow only the twelve agent-visible tools unless harness mode is enabled."""

    def __init__(self, *, allow_harness_tools: bool = False) -> None:
        allowed = set(ALLOWED_TOOLS)
        if allow_harness_tools:
            allowed.update(HARNESS_ONLY_TOOLS)
        self._allowed = frozenset(allowed)

    @property
    def allowed_tools(self) -> frozenset[str]:
        return self._allowed

    def check(self, tool: str) -> str:
        if tool not in self._allowed:
            raise ToolFilterError(tool)
        return tool

    def filter_request(self, request: AdapterRequest | Mapping[str, Any]) -> AdapterRequest:
        if isinstance(request, AdapterRequest):
            payload = request
        else:
            payload = AdapterRequest.from_dict(request)
        self.check(payload.tool)
        if not isinstance(payload.arguments, Mapping):
            raise ToolFilterError(payload.tool, code="invalid_arguments")
        return payload
