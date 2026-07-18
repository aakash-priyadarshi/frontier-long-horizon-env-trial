"""Explicit authority and jurisdiction profiles for Talon simulations."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from .actions import DecisionAction


AUTHORITY_SCHEMA_VERSION = "talon.authority/2.0"


class AuthorityLevel(str, Enum):
    MONITORING_ONLY = "monitoring_only"
    OBSERVE_AND_ALERT = "observe_and_alert"
    OBSERVE_ALERT_AND_ESCALATE = "observe_alert_and_escalate"
    RESPONSE_RECOMMENDATION = "response_recommendation"
    AUTHORISED_AGENCY_CONTROL = "authorised_agency_control"


class HumanAuthorisationStatus(str, Enum):
    """Legacy display states; never accepted as proof of approval."""

    NOT_REQUESTED = "not_requested"
    REQUESTED = "requested"
    REVOKED = "revoked"


class PolicyProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = AUTHORITY_SCHEMA_VERSION
    profile_id: str
    jurisdiction: str
    profile_version: str = "2.0"
    human_approval_mandatory: bool = True
    allow_authority_notification: bool = True
    allow_response_recommendation: bool = True
    prohibited_actions: frozenset[DecisionAction] = frozenset()


POLICY_PROFILES: dict[str, PolicyProfile] = {
    "uk_monitor_and_escalate": PolicyProfile(
        profile_id="uk_monitor_and_escalate",
        jurisdiction="GB",
    ),
    "monitoring_only": PolicyProfile(
        profile_id="monitoring_only",
        jurisdiction="SIM",
        allow_authority_notification=False,
        allow_response_recommendation=False,
        prohibited_actions=frozenset(
            {
                DecisionAction.NOTIFY_RELEVANT_AUTHORITY,
                DecisionAction.REQUEST_RESPONSE_AUTHORISATION,
                DecisionAction.RECOMMEND_AUTHORISED_MITIGATION,
            }
        ),
    ),
}


def policy_profile(profile_id: str) -> PolicyProfile:
    try:
        return POLICY_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError("unknown policy profile") from exc
