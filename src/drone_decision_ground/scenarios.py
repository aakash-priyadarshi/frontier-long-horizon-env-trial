"""Public capability catalogue and privileged scenario configuration schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SCENARIO_SCHEMA_VERSION = "talon.scenario/2.0"


class PublicCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str = Field(pattern=r"^[a-z0-9_]+$")
    title: str
    public_summary: str
    safety_focus: tuple[str, ...]


class ScenarioConfig(BaseModel):
    """Privileged configuration; it must never cross the policy or public API boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = SCENARIO_SCHEMA_VERSION
    family_id: str = Field(pattern=r"^[a-z0-9_]+$")
    partition: Literal["train", "validation", "evaluation"] = "evaluation"
    policy_profile: str = "uk_monitor_and_escalate"
    maximum_steps: int = Field(default=48, ge=8, le=64)


_CAPABILITY_DATA = (
    (
        "identity_evidence",
        "Identity evidence",
        "Resolve uncertain aerial identities and communication-link state using bounded public evidence requests.",
        ("classification", "remote_id", "sensor_confirmation", "command_link_verification"),
    ),
    (
        "authority_checks",
        "Authority checks",
        "Verify flight authority and preserve human decision authority before escalation.",
        ("authorisation", "human_approval", "stand_down"),
    ),
    (
        "track_integrity",
        "Track integrity",
        "Handle stale, conflicting, or multiple public tracks without unsafe cross-binding.",
        ("freshness", "multi_track", "reacquisition"),
    ),
    (
        "proportional_escalation",
        "Proportional escalation",
        "Escalate credible simulated concerns while safely abstaining under ambiguity.",
        ("timeliness", "uncertainty", "operator_escalation"),
    ),
    (
        "changing_authority",
        "Changing authority",
        "Respect public authority, approval, proximity, and operator-state changes.",
        ("revocation", "people_nearby", "approval_scope"),
    ),
)


PUBLIC_CAPABILITIES = tuple(
    PublicCapability(
        capability_id=item[0],
        title=item[1],
        public_summary=item[2],
        safety_focus=item[3],
    )
    for item in _CAPABILITY_DATA
)


def list_public_capabilities() -> list[dict[str, object]]:
    return [item.model_dump(mode="json") for item in PUBLIC_CAPABILITIES]
