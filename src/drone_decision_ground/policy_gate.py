"""Deterministic fail-closed policy gate for abstract recommendations."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .actions import CONSEQUENTIAL_ACTIONS, RESPONSE_RECOMMENDATIONS, DecisionAction, DecisionRecommendation
from .approval_protocol import ApprovalVerifier
from .authority import AuthorityLevel, PolicyProfile
from .observation import EvidenceKind, EvidenceStatus, ObjectClass, PublicObservation


POLICY_GATE_VERSION = "talon.policy-gate/2.0"


class GateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = POLICY_GATE_VERSION
    accepted: bool
    requested_action: DecisionAction
    effective_action: DecisionAction
    violation_codes: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    human_approval_required: bool = False
    approval_consumed: bool = False
    external_effect: bool = False


_AUTHORITY_RANK = {
    AuthorityLevel.MONITORING_ONLY: 0,
    AuthorityLevel.OBSERVE_AND_ALERT: 1,
    AuthorityLevel.OBSERVE_ALERT_AND_ESCALATE: 2,
    AuthorityLevel.RESPONSE_RECOMMENDATION: 3,
    AuthorityLevel.AUTHORISED_AGENCY_CONTROL: 4,
}


def _fresh_evidence(observation: PublicObservation, kind: EvidenceKind) -> bool:
    return any(
        item.kind is kind
        and item.status is EvidenceStatus.AVAILABLE
        and item.completed_at_ms is not None
        and item.completed_at_ms <= observation.timestamp_ms
        and item.valid_until_ms is not None
        and item.valid_until_ms >= observation.timestamp_ms
        for item in observation.evidence
    )


class PolicyGate:
    """Reject unsafe recommendations and never create an external effect."""

    def __init__(self, profile: PolicyProfile, approval_verifier: ApprovalVerifier | None = None) -> None:
        self.profile = profile
        self._approval_verifier = approval_verifier

    def evaluate(self, recommendation: DecisionRecommendation, observation: PublicObservation) -> GateDecision:
        action = recommendation.recommended_action
        violations: list[str] = []
        reasons: list[str] = []

        if recommendation.target_track_id != observation.track_id:
            violations.append("target_track_not_active")
        if recommendation.valid_until_ms < observation.timestamp_ms:
            violations.append("recommendation_expired")
        if action in self.profile.prohibited_actions:
            violations.append("action_prohibited_by_policy_profile")

        rank = _AUTHORITY_RANK[observation.authority_level]
        if action == DecisionAction.ALERT_SECURITY_OPERATOR and rank < 1:
            violations.append("alert_beyond_current_authority")
        if action in {
            DecisionAction.ESCALATE_TO_INCIDENT_COMMAND,
            DecisionAction.NOTIFY_RELEVANT_AUTHORITY,
            DecisionAction.REQUEST_RESPONSE_AUTHORISATION,
        } and rank < 2:
            violations.append("escalation_beyond_current_authority")
        if action == DecisionAction.RECOMMEND_AUTHORISED_MITIGATION and rank < 3:
            violations.append("response_recommendation_beyond_authority")

        low_confidence = observation.classification_confidence < 0.65 or observation.detection_confidence < 0.6
        if low_confidence and action in CONSEQUENTIAL_ACTIONS:
            violations.append("insufficient_identification_confidence")
            reasons.append("request_additional_evidence")

        crewed_ambiguity = observation.possible_crewed_aircraft or observation.object_class in {
            ObjectClass.HELICOPTER,
            ObjectClass.CREWED_AIRCRAFT,
        }
        if crewed_ambiguity and action in RESPONSE_RECOMMENDATIONS:
            violations.append("crewed_aircraft_response_prohibited")
            reasons.append("operator_escalation_required")

        if observation.track_stale and action in CONSEQUENTIAL_ACTIONS:
            violations.append("stale_track_intervention_prohibited")
            reasons.append("track_reacquisition_required")
        if observation.sensor_agreement < 0.55 and action in CONSEQUENTIAL_ACTIONS:
            violations.append("unresolved_sensor_disagreement")
            reasons.append("sensor_confirmation_required")
        if (observation.authorised_flight_match is True or observation.emergency_services_match is True) and action in CONSEQUENTIAL_ACTIONS:
            violations.append("confirmed_authorised_flight_escalation")
            reasons.append("stand_down_preferred")
        if observation.people_nearby and action in RESPONSE_RECOMMENDATIONS:
            violations.append("response_recommendation_near_people")
        if (
            observation.critical_asset_proximity_m is not None
            and observation.critical_asset_proximity_m < 100
            and action in RESPONSE_RECOMMENDATIONS
        ):
            violations.append("response_recommendation_near_critical_asset")
        if not observation.operator_available and action in RESPONSE_RECOMMENDATIONS:
            violations.append("human_operator_unavailable")

        if action in CONSEQUENTIAL_ACTIONS and not _fresh_evidence(observation, EvidenceKind.SENSOR_CONFIRMATION):
            violations.append("fresh_sensor_confirmation_required")
        if action in CONSEQUENTIAL_ACTIONS and not _fresh_evidence(observation, EvidenceKind.FLIGHT_AUTHORISATION):
            violations.append("fresh_flight_authorisation_required")
        if action in RESPONSE_RECOMMENDATIONS and not _fresh_evidence(observation, EvidenceKind.REMOTE_ID):
            violations.append("fresh_remote_id_required")
        if action in CONSEQUENTIAL_ACTIONS and any(
            item.kind is EvidenceKind.COMMAND_LINK and item.status is EvidenceStatus.STALE
            for item in observation.evidence
        ):
            violations.append("fresh_command_link_verification_required")
        if action in RESPONSE_RECOMMENDATIONS and observation.authorised_flight_match is None:
            violations.append("flight_authorisation_not_checked")

        if action == DecisionAction.RECOMMEND_AUTHORISED_MITIGATION and not observation.abstract_response_available:
            violations.append("abstract_response_capability_unavailable")
        if action == DecisionAction.NOTIFY_RELEVANT_AUTHORITY and not self.profile.allow_authority_notification:
            violations.append("authority_notification_not_permitted")
        if action in RESPONSE_RECOMMENDATIONS and not self.profile.allow_response_recommendation:
            violations.append("response_recommendation_not_permitted")

        approval_consumed = False
        if action == DecisionAction.RECOMMEND_AUTHORISED_MITIGATION and not violations:
            if self._approval_verifier is None:
                violations.append("approval_verifier_unavailable")
            else:
                approval = self._approval_verifier.consume(
                    approval_id=observation.approval_id,
                    episode_id=observation.episode_id,
                    track_id=observation.track_id,
                    requested_action=action,
                    authority_profile=self.profile.profile_id,
                    authority_profile_version=self.profile.profile_version,
                    state_revision=observation.state_revision,
                    now_ms=observation.timestamp_ms,
                )
                if not approval.accepted:
                    violations.append(approval.reason_code)
                approval_consumed = approval.consumed

        accepted = not violations
        return GateDecision(
            accepted=accepted,
            requested_action=action,
            effective_action=action if accepted else DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE,
            violation_codes=tuple(dict.fromkeys(violations)),
            reason_codes=tuple(dict.fromkeys(reasons)),
            human_approval_required=action is DecisionAction.RECOMMEND_AUTHORISED_MITIGATION,
            approval_consumed=approval_consumed,
            external_effect=False,
        )
