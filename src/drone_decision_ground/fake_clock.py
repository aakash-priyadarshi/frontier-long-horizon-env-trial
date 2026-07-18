"""Deterministic simulation clock with no wall-clock dependency."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakeClock:
    now_ms: int = 0

    def reset(self, value_ms: int = 0) -> int:
        if value_ms < 0:
            raise ValueError("clock cannot start before zero")
        self.now_ms = value_ms
        return self.now_ms

    def advance(self, delta_ms: int) -> int:
        if delta_ms <= 0:
            raise ValueError("clock advance must be positive")
        self.now_ms += delta_ms
        return self.now_ms
