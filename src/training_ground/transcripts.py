"""Append-only transcript recording."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Transcript:
    """Append-only transcript for one episode."""

    version: str
    instance_id: str
    split: str
    seed: int
    entries: list[dict[str, Any]] = field(default_factory=list)

    def _add(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)

    def add_step(
        self,
        *,
        sequence: int,
        tick: int,
        tool: str,
        arguments_digest: str,
        success_code: str,
        result_digest: str,
        reward_delta: float,
        terminated: bool,
        truncated: bool,
        cumulative_action_count: int,
        request_bytes: int,
        response_bytes: int,
    ) -> None:
        self._add(
            {
                "kind": "step",
                "sequence": sequence,
                "fake_tick": tick,
                "tool": tool,
                "canonical_arguments_digest": arguments_digest,
                "success_error_code": success_code,
                "bounded_public_result_digest": result_digest,
                "reward_delta": reward_delta,
                "terminated": terminated,
                "truncated": truncated,
                "cumulative_action_count": cumulative_action_count,
                "request_bytes": request_bytes,
                "response_bytes": response_bytes,
            }
        )

    def add_meta(self, key: str, value: Any) -> None:
        self._add({"kind": "meta", "key": key, "value": value})

    def digest(self) -> str:
        payload = json.dumps(self.entries, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def to_list(self) -> list[dict[str, Any]]:
        header = {
            "kind": "meta",
            "environment_version": self.version,
            "instance_id": self.instance_id,
            "split": self.split,
            "seed": self.seed,
            "transcript_digest": self.digest(),
        }
        return [header, *self.entries]


def canonical_arguments_digest(arguments: dict[str, Any]) -> str:
    payload = json.dumps(arguments, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def bounded_result_digest(result: Any) -> str:
    payload = json.dumps(result, default=str, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
