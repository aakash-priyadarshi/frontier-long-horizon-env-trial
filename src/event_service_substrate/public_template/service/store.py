"""Public persistence protocol used by the service stages."""

from __future__ import annotations

from typing import Protocol


class Store(Protocol):
    def append(self, command: dict[str, str]) -> str: ...

    def register(self, command: dict[str, str], event_id: str) -> None: ...

    def load(self, event_id: str) -> dict[str, str]: ...

    def settle(self, event: dict[str, str]) -> str: ...

    def advance(self, sequence: int) -> None: ...

