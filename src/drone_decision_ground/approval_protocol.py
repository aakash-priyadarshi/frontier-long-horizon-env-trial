"""Narrow public protocol for privileged simulated approval verification."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from .actions import DecisionAction


class ApprovalCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: bool
    reason_code: str
    consumed: bool = False


class ApprovalVerifier(Protocol):
    def consume(
        self,
        *,
        approval_id: str | None,
        episode_id: str,
        track_id: str,
        requested_action: DecisionAction,
        authority_profile: str,
        authority_profile_version: str,
        state_revision: int,
        now_ms: int,
    ) -> ApprovalCheck: ...
