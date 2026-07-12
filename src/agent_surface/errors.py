"""Bounded, neutral errors returned by the agent tool surface."""

from __future__ import annotations


class ToolError(Exception):
    """A tool input, precondition, or boundary violation.

    Messages are neutral and do not reveal privileged causal information.
    The ``code`` field gives a stable, machine-readable error category.
    """

    def __init__(self, message: str, code: str = "tool_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self) -> str:  # noqa: D105
        return self.message

    def __repr__(self) -> str:  # noqa: D105
        return f"ToolError({self.message!r}, code={self.code!r})"
