"""Integer-only deterministic clock."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakeClock:
    tick: int

    def advance(self, transitions: int = 1) -> int:
        if transitions < 1:
            raise ValueError("transitions must be a positive integer")
        self.tick += transitions
        return self.tick

