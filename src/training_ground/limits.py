"""Action, byte, and fake-clock limit enforcement."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_ACTION_LIMIT: int = 128
DEFAULT_BYTE_LIMIT: int = 2_000_000
DEFAULT_FAKE_CLOCK_LIMIT: int = 2000


@dataclass(frozen=True)
class Limits:
    action_limit: int = DEFAULT_ACTION_LIMIT
    byte_limit: int = DEFAULT_BYTE_LIMIT
    fake_clock_limit: int = DEFAULT_FAKE_CLOCK_LIMIT

    def check(
        self,
        action_count: int,
        total_bytes: int,
        tick: int,
    ) -> tuple[bool, str | None]:
        if action_count > self.action_limit:
            return True, f"action limit {self.action_limit} exceeded"
        if total_bytes > self.byte_limit:
            return True, f"byte limit {self.byte_limit} exceeded"
        if tick > self.fake_clock_limit:
            return True, f"fake-clock limit {self.fake_clock_limit} exceeded"
        return False, None

    def to_dict(self) -> dict[str, int]:
        return {
            "action_limit": self.action_limit,
            "byte_limit": self.byte_limit,
            "fake_clock_limit": self.fake_clock_limit,
        }
