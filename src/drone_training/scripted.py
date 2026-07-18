"""Deterministic Talon controls that use only the public policy boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from drone_decision_ground.actions import DecisionAction, DecisionRecommendation
from drone_decision_ground.authority import AuthorityLevel
from drone_decision_ground.environment import TalonDecisionEnv
from drone_decision_ground.observation import (
    ApprovalPublicStatus,
    EvidenceKind,
    EvidenceStatus,
    ObjectClass,
    PublicObservation,
)
from drone_decision_ground.scenarios import ScenarioConfig
from drone_decision_verifier.hidden_scenarios import build_environment


class ScriptedPolicy(Protocol):
    policy_id: str

    def reset(self) -> None: ...

    def recommend(self, observation: PublicObservation) -> DecisionRecommendation: ...


def recommendation(action: DecisionAction, observation: PublicObservation) -> DecisionRecommendation:
    low_confidence = observation.classification_confidence < 0.65
    threat = min(1.0, max(0.0, observation.approach_rate_mps / 12.0))
    return DecisionRecommendation(
        recommended_action=action,
        target_track_id=observation.track_id,
        valid_until_ms=observation.timestamp_ms + 1_000,
        action_confidence=0.72 if low_confidence else 0.92,
        threat_probability=threat,
        uncertainty=0.4 if low_confidence else 0.12,
        missing_evidence=("additional_sensor_confirmation",) if low_confidence else (),
        reason_codes=("public_evidence_policy",),
    )


def _evidence(observation: PublicObservation, kind: EvidenceKind):
    return next((item for item in observation.evidence if item.kind is kind), None)


def _fresh(observation: PublicObservation, kind: EvidenceKind, *, horizon_ms: int = 0) -> bool:
    item = _evidence(observation, kind)
    return bool(
        item
        and item.status is EvidenceStatus.AVAILABLE
        and item.completed_at_ms is not None
        and item.completed_at_ms <= observation.timestamp_ms
        and item.valid_until_ms is not None
        and item.valid_until_ms >= observation.timestamp_ms + horizon_ms
    )


_REQUEST_ACTION = {
    EvidenceKind.SENSOR_CONFIRMATION: DecisionAction.REQUEST_SENSOR_CONFIRMATION,
    EvidenceKind.COMMAND_LINK: DecisionAction.REQUEST_COMMAND_LINK_VERIFICATION,
    EvidenceKind.FLIGHT_AUTHORISATION: DecisionAction.CHECK_AUTHORISED_FLIGHT_DATABASE,
    EvidenceKind.REMOTE_ID: DecisionAction.REQUEST_REMOTE_ID_VERIFICATION,
}


@dataclass
class _EvidenceGatheringPolicy:
    """A public, adaptive state machine with no scenario-family lookup."""

    policy_id: str
    evidence_order: tuple[EvidenceKind, ...]
    _escalation_stage: int = field(default=0, init=False)
    _wait_toggle: bool = field(default=False, init=False)

    def reset(self) -> None:
        self._escalation_stage = 0
        self._wait_toggle = False

    def _next_evidence_action(self, observation: PublicObservation) -> DecisionAction | None:
        pending = set(observation.pending_evidence)
        for kind in self.evidence_order:
            item = _evidence(observation, kind)
            if kind in pending:
                continue
            if item is None or item.status is EvidenceStatus.STALE:
                return _REQUEST_ACTION[kind]
        return None

    def _decision(self, observation: PublicObservation) -> DecisionAction:
        if observation.track_stale:
            return DecisionAction.INCREASE_TRACK_PRIORITY

        request = self._next_evidence_action(observation)
        if request is not None:
            return request

        sensor = _evidence(observation, EvidenceKind.SENSOR_CONFIRMATION)
        authority = _evidence(observation, EvidenceKind.FLIGHT_AUTHORISATION)
        remote = _evidence(observation, EvidenceKind.REMOTE_ID)
        command_link = _evidence(observation, EvidenceKind.COMMAND_LINK)

        if command_link and command_link.status in {
            EvidenceStatus.FAILED,
            EvidenceStatus.UNAVAILABLE,
        }:
            return DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE
        if (
            EvidenceKind.COMMAND_LINK in self.evidence_order
            and not _fresh(observation, EvidenceKind.COMMAND_LINK)
        ):
            return DecisionAction.CONTINUE_OBSERVATION

        # An unresolved classification conflict is a safe abstention.  The
        # policy cannot infer which hidden scenario produced it.
        if sensor and sensor.status is EvidenceStatus.FAILED:
            return DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE
        if not _fresh(observation, EvidenceKind.SENSOR_CONFIRMATION):
            return DecisionAction.CONTINUE_OBSERVATION
        if _fresh(observation, EvidenceKind.SENSOR_CONFIRMATION) and (
            observation.sensor_agreement < 0.55
            or observation.classification_confidence < 0.65
        ):
            return DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE
        if observation.object_class in {ObjectClass.BIRD, ObjectClass.ENVIRONMENTAL_RETURN}:
            return DecisionAction.STAND_DOWN

        if authority and authority.status is EvidenceStatus.FAILED:
            return DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE
        if not _fresh(observation, EvidenceKind.FLIGHT_AUTHORISATION):
            return DecisionAction.CONTINUE_OBSERVATION
        if observation.authorised_flight_match or observation.emergency_services_match:
            if observation.emergency_services_match:
                return DecisionAction.STAND_DOWN
            if not _fresh(observation, EvidenceKind.REMOTE_ID):
                if remote and remote.status is EvidenceStatus.FAILED:
                    return DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE
                return DecisionAction.CONTINUE_OBSERVATION
            return DecisionAction.STAND_DOWN

        if observation.possible_crewed_aircraft or observation.object_class in {
            ObjectClass.HELICOPTER,
            ObjectClass.CREWED_AIRCRAFT,
        }:
            return DecisionAction.NOTIFY_RELEVANT_AUTHORITY

        if remote and remote.status is EvidenceStatus.FAILED:
            return DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE
        if not _fresh(observation, EvidenceKind.REMOTE_ID):
            return DecisionAction.CONTINUE_OBSERVATION

        # A crowd plus revoked/monitoring authority is an explicit stand-down.
        # Before revocation, waiting is safer than attempting a response.
        if observation.people_nearby:
            if observation.authority_level is AuthorityLevel.MONITORING_ONLY:
                return DecisionAction.STAND_DOWN
            self._wait_toggle = not self._wait_toggle
            return (
                DecisionAction.INCREASE_TRACK_PRIORITY
                if self._wait_toggle
                else DecisionAction.CONTINUE_OBSERVATION
            )

        credible = observation.identity_conflict or observation.approach_rate_mps >= 5.0
        if not credible:
            return DecisionAction.NOTIFY_RELEVANT_AUTHORITY

        # Refresh every gate-required item before each consequential phase.
        for kind in (
            EvidenceKind.SENSOR_CONFIRMATION,
            EvidenceKind.FLIGHT_AUTHORISATION,
            EvidenceKind.REMOTE_ID,
        ):
            if not _fresh(observation, kind, horizon_ms=1_000):
                return _REQUEST_ACTION[kind]

        if self._escalation_stage == 0:
            self._escalation_stage = 1
            return DecisionAction.ALERT_SECURITY_OPERATOR
        if self._escalation_stage == 1:
            self._escalation_stage = 2
            return DecisionAction.ESCALATE_TO_INCIDENT_COMMAND
        if observation.approval_status is ApprovalPublicStatus.AVAILABLE:
            return DecisionAction.RECOMMEND_AUTHORISED_MITIGATION
        self._escalation_stage = 3
        return DecisionAction.REQUEST_RESPONSE_AUTHORISATION

    def recommend(self, observation: PublicObservation) -> DecisionRecommendation:
        return recommendation(self._decision(observation), observation)


@dataclass
class SafeScriptedPolicy(_EvidenceGatheringPolicy):
    """Sensor-first positive control."""

    policy_id: str = "scripted-safe-valid"
    evidence_order: tuple[EvidenceKind, ...] = (
        EvidenceKind.SENSOR_CONFIRMATION,
        EvidenceKind.FLIGHT_AUTHORISATION,
        EvidenceKind.REMOTE_ID,
        EvidenceKind.COMMAND_LINK,
    )


@dataclass
class AuthorityFirstSafePolicy(_EvidenceGatheringPolicy):
    """Structurally distinct registry-first positive control."""

    policy_id: str = "scripted-safe-authority-first"
    evidence_order: tuple[EvidenceKind, ...] = (
        EvidenceKind.FLIGHT_AUTHORISATION,
        EvidenceKind.REMOTE_ID,
        EvidenceKind.SENSOR_CONFIRMATION,
        EvidenceKind.COMMAND_LINK,
    )


@dataclass
class OverEscalationPolicy:
    policy_id: str = "scripted-over-escalation"

    def reset(self) -> None:
        pass

    def recommend(self, observation: PublicObservation) -> DecisionRecommendation:
        return recommendation(DecisionAction.REQUEST_RESPONSE_AUTHORISATION, observation)


@dataclass
class UnderEscalationPolicy:
    policy_id: str = "scripted-under-escalation"

    def reset(self) -> None:
        pass

    def recommend(self, observation: PublicObservation) -> DecisionRecommendation:
        return recommendation(DecisionAction.CONTINUE_OBSERVATION, observation)


@dataclass
class NoAuthorityCheckPolicy(SafeScriptedPolicy):
    policy_id: str = "scripted-no-authority-check"

    def recommend(self, observation: PublicObservation) -> DecisionRecommendation:
        if observation.state_revision == 1:
            return recommendation(DecisionAction.ALERT_SECURITY_OPERATOR, observation)
        return super().recommend(observation)


@dataclass
class StaleTrackPolicy(SafeScriptedPolicy):
    policy_id: str = "scripted-stale-track"

    def recommend(self, observation: PublicObservation) -> DecisionRecommendation:
        if observation.track_stale:
            return recommendation(DecisionAction.REQUEST_RESPONSE_AUTHORISATION, observation)
        return super().recommend(observation)


@dataclass
class PublicPlausibleWrongHiddenPolicy(SafeScriptedPolicy):
    policy_id: str = "scripted-correct-public-wrong-hidden"

    def recommend(self, observation: PublicObservation) -> DecisionRecommendation:
        if all(kind not in observation.pending_evidence for kind in self.evidence_order) and all(
            _evidence(observation, kind) is not None for kind in self.evidence_order
        ):
            return recommendation(DecisionAction.STAND_DOWN, observation)
        return super().recommend(observation)


@dataclass
class NoCommandLinkCheckPolicy(SafeScriptedPolicy):
    """Negative control that deliberately skips the dedicated link instrument."""

    policy_id: str = "scripted-no-command-link-check"
    evidence_order: tuple[EvidenceKind, ...] = (
        EvidenceKind.SENSOR_CONFIRMATION,
        EvidenceKind.FLIGHT_AUTHORISATION,
        EvidenceKind.REMOTE_ID,
    )


SCRIPTED_POLICIES: dict[str, type[ScriptedPolicy]] = {
    "scripted-safe-valid": SafeScriptedPolicy,
    "scripted-safe-authority-first": AuthorityFirstSafePolicy,
    "scripted-over-escalation": OverEscalationPolicy,
    "scripted-under-escalation": UnderEscalationPolicy,
    "scripted-no-authority-check": NoAuthorityCheckPolicy,
    "scripted-stale-track": StaleTrackPolicy,
    "scripted-correct-public-wrong-hidden": PublicPlausibleWrongHiddenPolicy,
    "scripted-no-command-link-check": NoCommandLinkCheckPolicy,
}


def run_scripted(
    policy: ScriptedPolicy,
    config: ScenarioConfig,
    *,
    seed: int,
    environment: TalonDecisionEnv | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    env = environment or build_environment(config)
    policy.reset()
    raw_observation, _ = env.reset(seed=seed, options={"scenario_config": config})
    while True:
        observation = PublicObservation.model_validate(raw_observation)
        raw_observation, _, terminated, truncated, _ = env.step(policy.recommend(observation))
        if terminated or truncated:
            break
    return env.grade(), env.transcript()
