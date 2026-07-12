"""Public persistence protocol used by the service stages."""

from __future__ import annotations

from typing import Protocol


class Store(Protocol):
    def prepare(self, command: dict[str, str]) -> dict[str, str]: ...

    def get_event_id(self, command_key: str, occurrence_id: str) -> str | None: ...

    def get_command_registration(
        self, command_key: str, occurrence_id: str
    ) -> dict[str, str] | None: ...

    def append(self, command: dict[str, str]) -> str: ...

    def register(self, command: dict[str, str], event_id: str) -> None: ...

    def load(self, event_id: str) -> dict[str, str]: ...

    def effect_exists(self, event_id: str) -> str | None: ...

    def effect_by_key(self, event_id: str, logical_effect_key: str) -> str | None: ...

    def settle(self, event: dict[str, str]) -> str: ...

    def intent_create(
        self,
        event_id: str,
        command_key: str,
        occurrence_id: str,
        logical_effect_key: str = "settlement",
    ) -> str: ...

    def intent_complete(self, intent_id: str, effect_id: str) -> None: ...

    def get_intent(
        self, event_id: str, logical_effect_key: str = "settlement"
    ) -> dict[str, str] | None: ...

    def mark_event(
        self, event_id: str, mark_key: str, mark_state: str = "marked"
    ) -> None: ...

    def advance(self, sequence: int) -> None: ...
