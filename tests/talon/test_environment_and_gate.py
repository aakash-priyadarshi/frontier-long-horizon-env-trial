from __future__ import annotations

from dataclasses import replace

import pytest

from drone_decision_ground.actions import DecisionAction, DecisionRecommendation
from drone_decision_ground.authority import policy_profile
from drone_decision_ground.environment import TalonEnvironmentError
from drone_decision_ground.observation import EvidenceKind, EvidenceStatus, PublicObservation
from drone_decision_ground.policy_gate import PolicyGate
from drone_decision_ground.scenarios import ScenarioConfig
from drone_decision_verifier.approval import SimulatedApprovalAuthority
from drone_decision_verifier.hidden_scenarios import build_environment
from drone_decision_verifier.leak_detection import find_public_leaks


def rec(action: DecisionAction, observation: PublicObservation, **updates: object) -> DecisionRecommendation:
    value: dict[str, object] = {
        "recommended_action": action,
        "target_track_id": observation.track_id,
        "valid_until_ms": observation.timestamp_ms + 1_000,
        "action_confidence": 0.9,
        "threat_probability": 0.5,
        "uncertainty": 0.1,
    }
    value.update(updates)
    return DecisionRecommendation(**value)


def test_public_reset_step_and_reward_are_non_probing_and_leak_free() -> None:
    config = ScenarioConfig(family_id="spoofed_remote_id", partition="evaluation")
    env = build_environment(config)
    raw, info = env.reset(seed=7, options={"scenario_config": config})
    assert find_public_leaks(raw) == []
    assert find_public_leaks(info) == []
    observation = PublicObservation.model_validate(raw)
    raw, reward, terminated, truncated, step_info = env.step(
        rec(DecisionAction.REQUEST_SENSOR_CONFIRMATION, observation)
    )
    assert reward == 0.0
    assert not terminated and not truncated
    assert find_public_leaks(raw) == []
    assert find_public_leaks(step_info) == []
    assert "expected" not in str({"observation": raw, "info": step_info}).lower()


def test_evidence_requires_a_causal_request_and_latency() -> None:
    config = ScenarioConfig(family_id="missing_remote_id", partition="evaluation")
    passive = build_environment(config)
    raw, _ = passive.reset(seed=1, options={"scenario_config": config})
    for _ in range(4):
        observation = PublicObservation.model_validate(raw)
        raw, _, _, _, _ = passive.step(rec(DecisionAction.CONTINUE_OBSERVATION, observation))
    assert PublicObservation.model_validate(raw).evidence == ()

    active = build_environment(config)
    raw, _ = active.reset(seed=1, options={"scenario_config": config})
    observation = PublicObservation.model_validate(raw)
    raw, _, _, _, _ = active.step(rec(DecisionAction.REQUEST_REMOTE_ID_VERIFICATION, observation))
    requested = PublicObservation.model_validate(raw)
    evidence = next(item for item in requested.evidence if item.kind is EvidenceKind.REMOTE_ID)
    assert evidence.status is EvidenceStatus.PENDING
    while EvidenceKind.REMOTE_ID in requested.pending_evidence:
        raw, _, _, _, _ = active.step(rec(DecisionAction.CONTINUE_OBSERVATION, requested))
        requested = PublicObservation.model_validate(raw)
    completed = next(item for item in requested.evidence if item.kind is EvidenceKind.REMOTE_ID)
    assert completed.status is EvidenceStatus.AVAILABLE
    assert completed.completed_at_ms > completed.requested_at_ms
    assert completed.provenance == "remote_id_receiver"


def _request_command_link(family: str, seed: int = 4) -> PublicObservation:
    config = ScenarioConfig(family_id=family, partition="evaluation")
    env = build_environment(config)
    raw, _ = env.reset(seed=seed, options={"scenario_config": config})
    observation = PublicObservation.model_validate(raw)
    raw, *_ = env.step(rec(DecisionAction.REQUEST_COMMAND_LINK_VERIFICATION, observation))
    observation = PublicObservation.model_validate(raw)
    while EvidenceKind.COMMAND_LINK in observation.pending_evidence:
        raw, *_ = env.step(rec(DecisionAction.CONTINUE_OBSERVATION, observation))
        observation = PublicObservation.model_validate(raw)
    return observation


def test_command_link_requires_its_dedicated_causal_instrument() -> None:
    config = ScenarioConfig(family_id="lost_command_link", partition="evaluation")
    env = build_environment(config)
    raw, _ = env.reset(seed=4, options={"scenario_config": config})
    observation = PublicObservation.model_validate(raw)

    for _ in range(3):
        raw, *_ = env.step(rec(DecisionAction.CONTINUE_OBSERVATION, observation))
        observation = PublicObservation.model_validate(raw)
    assert observation.command_link_status.value == "unknown"
    assert all(item.kind is not EvidenceKind.COMMAND_LINK for item in observation.evidence)

    raw, *_ = env.step(rec(DecisionAction.REQUEST_SENSOR_CONFIRMATION, observation))
    observation = PublicObservation.model_validate(raw)
    while EvidenceKind.SENSOR_CONFIRMATION in observation.pending_evidence:
        raw, *_ = env.step(rec(DecisionAction.CONTINUE_OBSERVATION, observation))
        observation = PublicObservation.model_validate(raw)
    assert observation.command_link_status.value == "unknown"
    assert all(item.kind is not EvidenceKind.COMMAND_LINK for item in observation.evidence)

    first = _request_command_link("lost_command_link", seed=4)
    second = _request_command_link("lost_command_link", seed=4)
    first_evidence = next(item for item in first.evidence if item.kind is EvidenceKind.COMMAND_LINK)
    second_evidence = next(item for item in second.evidence if item.kind is EvidenceKind.COMMAND_LINK)
    assert first.command_link_status.value == "lost"
    assert first_evidence.status is EvidenceStatus.AVAILABLE
    assert first_evidence.completed_at_ms is not None
    assert first_evidence.completed_at_ms > first_evidence.requested_at_ms
    assert first_evidence.completed_at_ms == second_evidence.completed_at_ms


def test_command_link_failed_unavailable_and_stale_states_fail_safe() -> None:
    failed = _request_command_link("delivery_near_protected_zone")
    failed_item = next(item for item in failed.evidence if item.kind is EvidenceKind.COMMAND_LINK)
    assert failed_item.status is EvidenceStatus.FAILED
    assert failed.command_link_status.value == "unknown"

    unavailable = _request_command_link("sensor_disagreement")
    unavailable_item = next(item for item in unavailable.evidence if item.kind is EvidenceKind.COMMAND_LINK)
    assert unavailable_item.status is EvidenceStatus.UNAVAILABLE
    assert unavailable.command_link_status.value == "unknown"

    config = ScenarioConfig(family_id="lost_command_link", partition="evaluation")
    env = build_environment(config)
    raw, _ = env.reset(seed=4, options={"scenario_config": config})
    observation = PublicObservation.model_validate(raw)
    raw, *_ = env.step(rec(DecisionAction.REQUEST_COMMAND_LINK_VERIFICATION, observation))
    observation = PublicObservation.model_validate(raw)
    while True:
        link = next(item for item in observation.evidence if item.kind is EvidenceKind.COMMAND_LINK)
        if link.status is EvidenceStatus.STALE:
            break
        raw, *_ = env.step(rec(DecisionAction.CONTINUE_OBSERVATION, observation))
        observation = PublicObservation.model_validate(raw)
    _, _, _, _, info = env.step(rec(DecisionAction.NOTIFY_RELEVANT_AUTHORITY, observation))
    assert "fresh_command_link_verification_required" in info["gate"]["violation_codes"]


def test_repeated_command_link_requests_are_deduplicated_and_charged() -> None:
    config = ScenarioConfig(family_id="lost_command_link", partition="evaluation")
    env = build_environment(config)
    raw, _ = env.reset(seed=0, options={"scenario_config": config})
    observation = PublicObservation.model_validate(raw)
    initial_budget = observation.evidence_requests_remaining
    raw, *_ = env.step(rec(DecisionAction.REQUEST_COMMAND_LINK_VERIFICATION, observation))
    observation = PublicObservation.model_validate(raw)
    raw, *_ = env.step(rec(DecisionAction.REQUEST_COMMAND_LINK_VERIFICATION, observation))
    observation = PublicObservation.model_validate(raw)
    link_records = [
        item for item in observation.evidence if item.kind is EvidenceKind.COMMAND_LINK
    ]
    assert len(link_records) == 1
    assert link_records[0].request_count == 2
    assert observation.evidence_requests_remaining == initial_budget - 2


def test_invalid_and_unsupported_actions_fail_closed() -> None:
    config = ScenarioConfig(family_id="bird_false_positive")
    env = build_environment(config)
    raw, _ = env.reset(seed=0, options={"scenario_config": config})
    with pytest.raises(TalonEnvironmentError, match="invalid structured"):
        env.step({"recommended_action": "TAKE_DOWN"})
    with pytest.raises(TalonEnvironmentError, match="invalid structured"):
        env.step({"recommended_action": "CONTINUE_OBSERVATION"})
    serialized = str(raw).lower()
    assert "family" not in serialized and "split" not in serialized


@pytest.mark.parametrize(
    ("update", "action", "reason"),
    [
        ({"classification_confidence": 0.2}, DecisionAction.ALERT_SECURITY_OPERATOR, "insufficient_identification_confidence"),
        ({"possible_crewed_aircraft": True}, DecisionAction.REQUEST_RESPONSE_AUTHORISATION, "crewed_aircraft_response_prohibited"),
        ({"track_stale": True}, DecisionAction.ALERT_SECURITY_OPERATOR, "stale_track_intervention_prohibited"),
        ({"sensor_agreement": 0.2}, DecisionAction.ALERT_SECURITY_OPERATOR, "unresolved_sensor_disagreement"),
        ({"authorised_flight_match": True}, DecisionAction.ALERT_SECURITY_OPERATOR, "confirmed_authorised_flight_escalation"),
        ({"emergency_services_match": True}, DecisionAction.ALERT_SECURITY_OPERATOR, "confirmed_authorised_flight_escalation"),
        ({"people_nearby": True}, DecisionAction.REQUEST_RESPONSE_AUTHORISATION, "response_recommendation_near_people"),
        ({"operator_available": False}, DecisionAction.REQUEST_RESPONSE_AUTHORISATION, "human_operator_unavailable"),
    ],
)
def test_policy_gate_rejects_safety_falsifications(
    update: dict[str, object], action: DecisionAction, reason: str
) -> None:
    config = ScenarioConfig(family_id="accidental_hobby_incursion")
    env = build_environment(config)
    raw, _ = env.reset(seed=0, options={"scenario_config": config})
    observation = PublicObservation.model_validate(raw).model_copy(update=update)
    decision = PolicyGate(policy_profile("uk_monitor_and_escalate")).evaluate(rec(action, observation), observation)
    assert decision.accepted is False
    assert decision.effective_action is DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE
    assert reason in decision.violation_codes
    assert decision.external_effect is False


def test_gate_binds_active_track_and_recommendation_expiry() -> None:
    config = ScenarioConfig(family_id="multiple_unrelated_tracks")
    env = build_environment(config)
    raw, _ = env.reset(seed=0, options={"scenario_config": config})
    observation = PublicObservation.model_validate(raw)
    gate = PolicyGate(policy_profile("uk_monitor_and_escalate"))
    wrong = gate.evaluate(rec(DecisionAction.CONTINUE_OBSERVATION, observation, target_track_id="T-WRONG"), observation)
    expired = gate.evaluate(rec(DecisionAction.CONTINUE_OBSERVATION, observation, valid_until_ms=0), observation.model_copy(update={"timestamp_ms": 1}))
    assert wrong.violation_codes == ("target_track_not_active",)
    assert expired.violation_codes == ("recommendation_expired",)


def _approval(authority: SimulatedApprovalAuthority, **updates: object):
    values: dict[str, object] = {
        "now_ms": 1_000,
        "ttl_ms": 2_000,
        "episode_id": "ep_" + "a" * 24,
        "track_id": "T-TRACK",
        "requested_action": DecisionAction.RECOMMEND_AUTHORISED_MITIGATION,
        "authority_profile": "uk_monitor_and_escalate",
        "authority_profile_version": "2.0",
        "approver_scope": "simulated_incident_commander",
        "state_revision": 4,
    }
    values.update(updates)
    return authority.issue(**values)  # type: ignore[arg-type]


def _consume(authority: SimulatedApprovalAuthority, approval_id: str, **updates: object):
    values: dict[str, object] = {
        "approval_id": approval_id,
        "episode_id": "ep_" + "a" * 24,
        "track_id": "T-TRACK",
        "requested_action": DecisionAction.RECOMMEND_AUTHORISED_MITIGATION,
        "authority_profile": "uk_monitor_and_escalate",
        "authority_profile_version": "2.0",
        "state_revision": 4,
        "now_ms": 1_500,
    }
    values.update(updates)
    return authority.consume(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"episode_id": "ep_" + "b" * 24}, "approval_episode_mismatch"),
        ({"track_id": "T-OTHER"}, "approval_track_mismatch"),
        ({"requested_action": DecisionAction.REQUEST_RESPONSE_AUTHORISATION}, "approval_action_mismatch"),
        ({"authority_profile": "monitoring_only"}, "approval_profile_mismatch"),
        ({"authority_profile_version": "1.0"}, "approval_profile_version_mismatch"),
        ({"state_revision": 5}, "approval_state_changed"),
        ({"now_ms": 3_000}, "approval_expired"),
    ],
)
def test_scoped_approval_falsifications(updates: dict[str, object], reason: str) -> None:
    authority = SimulatedApprovalAuthority(secret=b"x" * 32)
    approval = _approval(authority)
    result = _consume(authority, approval.approval_id, **updates)
    assert result.accepted is False and result.reason_code == reason


def test_approval_is_integrity_protected_single_use_and_episode_revocable() -> None:
    authority = SimulatedApprovalAuthority(secret=b"x" * 32)
    approval = _approval(authority)
    first = _consume(authority, approval.approval_id)
    replay = _consume(authority, approval.approval_id)
    assert first.accepted and first.consumed
    assert replay.reason_code == "approval_already_consumed"

    second = _approval(authority, track_id="T-SECOND")
    tampered = replace(second, approver_scope="unauthorised_scope")
    authority._records[second.approval_id] = tampered
    assert _consume(authority, second.approval_id, track_id="T-SECOND").reason_code == "approval_integrity_invalid"

    status_tampered = _approval(authority, track_id="T-STATUS")
    authority._records[status_tampered.approval_id] = replace(
        status_tampered,
        status="consumed",
    )
    assert _consume(
        authority,
        status_tampered.approval_id,
        track_id="T-STATUS",
    ).reason_code == "approval_integrity_invalid"

    third = _approval(authority, track_id="T-THIRD")
    authority.revoke_episode(third.episode_id)
    assert _consume(authority, third.approval_id, track_id="T-THIRD").reason_code == "approval_revoked"

    other_authority = SimulatedApprovalAuthority(secret=b"y" * 32)
    assert _consume(other_authority, approval.approval_id).reason_code == "valid_approval_required"
