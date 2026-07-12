"""Environment protocol and shared types for the training ground."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


ENVIRONMENT_VERSION: str = "final-1.0.0"
MANIFEST_SCHEMA_VERSION: str = "1.0.0"


@runtime_checkable
class EnvironmentProtocol(Protocol):
    """Shared interface implemented by both the core and Gymnasium wrappers."""

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]: ...

    def step(
        self,
        action: dict[str, Any],
    ) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]: ...

    def grade(self) -> dict[str, Any]: ...

    def transcript(self) -> list[dict[str, Any]]: ...

    def close(self) -> None: ...


class EnvironmentError(Exception):
    """Raised for environment contract violations."""

    def __init__(self, message: str, *, code: str = "environment_error") -> None:
        super().__init__(message)
        self.code = code
