"""Bounded, neutral errors returned by the agent tool surface."""

from __future__ import annotations


class ToolError(Exception):
    """A tool input, precondition, or boundary violation.

    Messages are neutral and do not reveal privileged causal information.
    """
