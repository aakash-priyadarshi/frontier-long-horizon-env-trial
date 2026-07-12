"""APEX-SWE integration adapter that wraps the training_ground core."""

from __future__ import annotations

from .adapter import run_apex_trial, write_apex_result

__all__ = ["run_apex_trial", "write_apex_result"]
