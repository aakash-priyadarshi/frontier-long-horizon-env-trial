"""Privileged authentication capability for snapshot and recovery provenance."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any

from .canonical import canonical_json


@dataclass(frozen=True, slots=True)
class RecoveryAuthority:
    """Local HMAC capability supplied by privileged fixture-building code."""

    key: bytes = field(repr=False)
    scope: str = field(repr=False)
    actor_scope: str = "recovery-operator-v1"

    def __post_init__(self) -> None:
        if len(self.key) < 32:
            raise ValueError("authority keys must contain at least 32 bytes")
        if not self.scope:
            raise ValueError("authority scope must be non-empty")
        if not self.actor_scope:
            raise ValueError("actor scope must be non-empty")

    def _tag(self, domain: str, fields: dict[str, Any]) -> str:
        message = domain.encode("utf-8") + b"\x00" + canonical_json(
            {"authority_scope": self.scope, **fields}
        )
        return hmac.new(self.key, message, hashlib.sha256).hexdigest()

    def snapshot_tag(
        self,
        *,
        snapshot_id: str,
        state_root: str,
        payload: str,
        created_tick: int,
    ) -> str:
        return self._tag(
            "snapshot-auth-v1",
            {
                "snapshot_id": snapshot_id,
                "state_root": state_root,
                "payload": payload,
                "created_tick": created_tick,
            },
        )

    def snapshot_tag_is_valid(
        self,
        *,
        snapshot_id: str,
        state_root: str,
        payload: str,
        created_tick: int,
        auth_tag: str,
    ) -> bool:
        expected = self.snapshot_tag(
            snapshot_id=snapshot_id,
            state_root=state_root,
            payload=payload,
            created_tick=created_tick,
        )
        return hmac.compare_digest(expected, auth_tag)

    def recovery_tag(self, fields: dict[str, Any]) -> str:
        return self._tag("recovery-proof-v1", fields)

    def recovery_tag_is_valid(self, fields: dict[str, Any], auth_tag: str) -> bool:
        return hmac.compare_digest(self.recovery_tag(fields), auth_tag)
