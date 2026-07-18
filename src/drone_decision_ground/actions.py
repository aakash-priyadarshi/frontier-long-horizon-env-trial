"""Versioned, abstract Talon decision-support recommendations."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


ACTION_SCHEMA_VERSION = "talon.action/3.0"


class DecisionAction(str, Enum):
    CONTINUE_OBSERVATION = "CONTINUE_OBSERVATION"
    INCREASE_TRACK_PRIORITY = "INCREASE_TRACK_PRIORITY"
    REQUEST_SENSOR_CONFIRMATION = "REQUEST_SENSOR_CONFIRMATION"
    REQUEST_COMMAND_LINK_VERIFICATION = "REQUEST_COMMAND_LINK_VERIFICATION"
    CHECK_AUTHORISED_FLIGHT_DATABASE = "CHECK_AUTHORISED_FLIGHT_DATABASE"
    REQUEST_REMOTE_ID_VERIFICATION = "REQUEST_REMOTE_ID_VERIFICATION"
    ALERT_SECURITY_OPERATOR = "ALERT_SECURITY_OPERATOR"
    ESCALATE_TO_INCIDENT_COMMAND = "ESCALATE_TO_INCIDENT_COMMAND"
    NOTIFY_RELEVANT_AUTHORITY = "NOTIFY_RELEVANT_AUTHORITY"
    REQUEST_RESPONSE_AUTHORISATION = "REQUEST_RESPONSE_AUTHORISATION"
    RECOMMEND_AUTHORISED_MITIGATION = "RECOMMEND_AUTHORISED_MITIGATION"
    STAND_DOWN = "STAND_DOWN"
    ABSTAIN_INSUFFICIENT_EVIDENCE = "ABSTAIN_INSUFFICIENT_EVIDENCE"


RESPONSE_RECOMMENDATIONS = frozenset(
    {
        DecisionAction.REQUEST_RESPONSE_AUTHORISATION,
        DecisionAction.RECOMMEND_AUTHORISED_MITIGATION,
    }
)

CONSEQUENTIAL_ACTIONS = frozenset(
    {
        DecisionAction.ALERT_SECURITY_OPERATOR,
        DecisionAction.ESCALATE_TO_INCIDENT_COMMAND,
        DecisionAction.NOTIFY_RELEVANT_AUTHORITY,
        *RESPONSE_RECOMMENDATIONS,
    }
)

EVIDENCE_ACTIONS = frozenset(
    {
        DecisionAction.CONTINUE_OBSERVATION,
        DecisionAction.INCREASE_TRACK_PRIORITY,
        DecisionAction.REQUEST_SENSOR_CONFIRMATION,
        DecisionAction.REQUEST_COMMAND_LINK_VERIFICATION,
        DecisionAction.CHECK_AUTHORISED_FLIGHT_DATABASE,
        DecisionAction.REQUEST_REMOTE_ID_VERIFICATION,
        DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE,
    }
)


class DecisionRecommendation(BaseModel):
    """Bounded model output with an explicit active-track and freshness binding."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: str = Field(default=ACTION_SCHEMA_VERSION, pattern=r"^talon\.action/3\.0$")
    recommended_action: DecisionAction
    target_track_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    valid_until_ms: int = Field(ge=0)
    action_confidence: float = Field(ge=0, le=1)
    threat_probability: float = Field(ge=0, le=1)
    uncertainty: float = Field(ge=0, le=1)
    missing_evidence: tuple[str, ...] = Field(default=(), max_length=8)
    reason_codes: tuple[str, ...] = Field(default=(), max_length=12)

    @field_validator("missing_evidence", "reason_codes")
    @classmethod
    def validate_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("codes must be unique")
        for value in values:
            if not value or len(value) > 80 or not value.replace("_", "").isalnum():
                raise ValueError("codes must be bounded snake_case identifiers")
        return values


def parse_recommendation(
    value: DecisionRecommendation | DecisionAction | str | dict[str, Any],
    *,
    default_track_id: str | None = None,
    now_ms: int = 0,
) -> DecisionRecommendation:
    if isinstance(value, DecisionRecommendation):
        return value
    if isinstance(value, (DecisionAction, str)):
        if default_track_id is None:
            raise ValueError("a target track is required")
        return DecisionRecommendation(
            recommended_action=DecisionAction(value),
            target_track_id=default_track_id,
            valid_until_ms=now_ms + 1_000,
            action_confidence=1.0,
            threat_probability=0.5,
            uncertainty=0.5,
        )
    if not isinstance(value, dict):
        raise TypeError("recommendation must be an action ID or structured object")
    return DecisionRecommendation.model_validate(value)
