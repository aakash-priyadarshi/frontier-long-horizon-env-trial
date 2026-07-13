"""Ordered persisted event definitions and SSE encoding."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvaluationEvent:
    id: int
    scope_type: str
    scope_id: str
    event_type: str
    created_at: str
    data: dict[str, Any]

    def sse(self) -> str:
        return (
            f"id: {self.id}\n"
            f"event: {self.event_type}\n"
            f"data: {json.dumps(self.data, sort_keys=True, separators=(',', ':'))}\n\n"
        )
