"""Public-only prompt projection for external TALON LLM policies."""

from __future__ import annotations

from typing import Any

from drone_decision_ground.actions import DecisionAction
from drone_decision_ground.observation import PublicObservation

from .external_llm_schemas import PROMPT_VERSION
from .features import ACTIONS
from .manifests import content_digest
from .offline_rl import public_action_mask


ACTION_DESCRIPTIONS: dict[str, str] = {
    DecisionAction.CONTINUE_OBSERVATION.value: "Continue passive observation without escalation.",
    DecisionAction.INCREASE_TRACK_PRIORITY.value: "Raise tracking priority for the active track.",
    DecisionAction.REQUEST_SENSOR_CONFIRMATION.value: "Request additional sensor confirmation.",
    DecisionAction.REQUEST_COMMAND_LINK_VERIFICATION.value: "Request command-link verification.",
    DecisionAction.CHECK_AUTHORISED_FLIGHT_DATABASE.value: "Check authorised-flight database match.",
    DecisionAction.REQUEST_REMOTE_ID_VERIFICATION.value: "Request Remote ID verification.",
    DecisionAction.ALERT_SECURITY_OPERATOR.value: "Alert a security operator for review.",
    DecisionAction.ESCALATE_TO_INCIDENT_COMMAND.value: "Escalate to incident command for review.",
    DecisionAction.NOTIFY_RELEVANT_AUTHORITY.value: "Notify a relevant authority for review.",
    DecisionAction.REQUEST_RESPONSE_AUTHORISATION.value: "Request scoped human response authorisation.",
    DecisionAction.RECOMMEND_AUTHORISED_MITIGATION.value: "Recommend an authorised mitigation after approval.",
    DecisionAction.STAND_DOWN.value: "Stand down the active recommendation path.",
    DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE.value: "Abstain when public evidence is insufficient.",
}


def allowed_evidence_refs(observation: PublicObservation) -> tuple[str, ...]:
    refs: list[str] = []
    for item in observation.evidence:
        refs.append(item.kind.value)
        refs.append(item.provenance)
    for kind in observation.pending_evidence:
        refs.append(kind.value)
    # Stable unique order
    seen: set[str] = set()
    ordered: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            ordered.append(ref)
    return tuple(ordered)


def project_public_observation(observation: PublicObservation) -> dict[str, Any]:
    """Build an explicit public projection; never pass privileged objects through."""

    return {
        "episode_id": observation.episode_id,
        "timestamp_ms": observation.timestamp_ms,
        "state_revision": observation.state_revision,
        "track_id": observation.track_id,
        "object_class": observation.object_class.value,
        "detection_confidence": observation.detection_confidence,
        "classification_confidence": observation.classification_confidence,
        "distance_m": observation.distance_m,
        "altitude_m": observation.altitude_m,
        "speed_mps": observation.speed_mps,
        "heading_deg": observation.heading_deg,
        "approach_rate_mps": observation.approach_rate_mps,
        "track_age_s": observation.track_age_s,
        "missed_frames": observation.missed_frames,
        "track_quality": observation.track_quality,
        "track_stale": observation.track_stale,
        "identity_conflict": observation.identity_conflict,
        "possible_crewed_aircraft": observation.possible_crewed_aircraft,
        "sensor_agreement": observation.sensor_agreement,
        "sensor_sources": list(observation.sensor_sources),
        "remote_id_status": observation.remote_id_status.value,
        "authorised_flight_match": observation.authorised_flight_match,
        "emergency_services_match": observation.emergency_services_match,
        "command_link_status": observation.command_link_status.value,
        "protected_zone": observation.protected_zone,
        "airspace_status": observation.airspace_status.value,
        "people_nearby": observation.people_nearby,
        "critical_asset_proximity_m": observation.critical_asset_proximity_m,
        "weather_visibility": observation.weather_visibility.value,
        "operator_available": observation.operator_available,
        "authority_level": observation.authority_level.value,
        "abstract_response_available": observation.abstract_response_available,
        "evidence": [
            {
                "kind": item.kind.value,
                "status": item.status.value,
                "provenance": item.provenance,
                "request_count": item.request_count,
                "requested_at_ms": item.requested_at_ms,
                "completed_at_ms": item.completed_at_ms,
                "valid_until_ms": item.valid_until_ms,
            }
            for item in observation.evidence
        ],
        "pending_evidence": [item.value for item in observation.pending_evidence],
        "evidence_requests_remaining": observation.evidence_requests_remaining,
        "related_tracks": [
            {
                "track_id": item.track_id,
                "object_class": item.object_class.value,
                "distance_m": item.distance_m,
                "approach_rate_mps": item.approach_rate_mps,
                "track_quality": item.track_quality,
                "track_stale": item.track_stale,
            }
            for item in observation.related_tracks
        ],
        "approval_status": observation.approval_status.value,
        "approval_available": observation.approval_status.value == "available",
        "previous_action": observation.previous_action.value if observation.previous_action else None,
    }


def build_public_prompt_bundle(
    observation: PublicObservation,
    *,
    history: tuple[PublicObservation, ...],
    profile_id: str,
    prompt_version: str = PROMPT_VERSION,
) -> dict[str, Any]:
    mask = public_action_mask(observation, profile_id=profile_id)
    allowed_actions = [action.value for action, enabled in zip(ACTIONS, mask) if enabled]
    evidence_refs = list(allowed_evidence_refs(observation))
    projected_history = [project_public_observation(item) for item in history]
    current = project_public_observation(observation)
    bundle = {
        "prompt_version": prompt_version,
        "simulation_only": True,
        "decision_support_only": True,
        "external_effect": False,
        "human_approval_mandatory": True,
        "instructions": [
            "This is simulation-only aerial-track decision support.",
            "Recommend exactly one abstract action from the currently allowed list.",
            "You cannot perform physical actions or external effects.",
            "Abstain when public evidence is insufficient.",
            "Return exactly one plain JSON object and nothing else.",
            "Do not include chain of thought or hidden reasoning.",
        ],
        "response_schema": {
            "action": "one allowed abstract action name",
            "confidence": "finite float in [0,1]",
            "evidence_refs": "subset of supplied public evidence identifiers",
            "decision_summary": "short plain-text justification",
        },
        "all_abstract_actions": [action.value for action in ACTIONS],
        "action_descriptions": {key: ACTION_DESCRIPTIONS[key] for key in allowed_actions},
        "allowed_actions": allowed_actions,
        "allowed_evidence_refs": evidence_refs,
        "observation_history": projected_history,
        "current_observation": current,
    }
    bundle["prompt_input_digest"] = content_digest(
        {
            "prompt_version": prompt_version,
            "allowed_actions": allowed_actions,
            "allowed_evidence_refs": evidence_refs,
            "observation_history": projected_history,
            "current_observation": current,
        }
    )
    return bundle


def render_prompt_text(bundle: dict[str, Any]) -> str:
    lines = [
        "SYSTEM: SkyGuard / TALON simulation-only decision support.",
        "You must not claim physical control or external effects.",
        "Human approval remains mandatory for consequential recommendations.",
        "",
        "Allowed actions now:",
    ]
    for action in bundle["allowed_actions"]:
        lines.append(f"- {action}: {bundle['action_descriptions'].get(action, '')}")
    lines.append("")
    lines.append("Allowed public evidence references:")
    if bundle["allowed_evidence_refs"]:
        for ref in bundle["allowed_evidence_refs"]:
            lines.append(f"- {ref}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("Bounded public observation history (JSON):")
    import json

    lines.append(json.dumps(bundle["observation_history"], sort_keys=True, separators=(",", ":")))
    lines.append("")
    lines.append("Current public observation (JSON):")
    lines.append(json.dumps(bundle["current_observation"], sort_keys=True, separators=(",", ":")))
    lines.append("")
    lines.append(
        'Respond with exactly one JSON object: '
        '{"action":"...","confidence":0.0,"evidence_refs":[],"decision_summary":"..."}'
    )
    return "\n".join(lines)
