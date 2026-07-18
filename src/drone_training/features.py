"""Stable, mask-aware vector encoding for public Talon observations."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from drone_decision_ground.actions import DecisionAction
from drone_decision_ground.authority import AuthorityLevel
from drone_decision_ground.observation import (
    OBSERVATION_SCHEMA_VERSION,
    AirspaceStatus,
    ApprovalPublicStatus,
    CommandLinkStatus,
    EvidenceKind,
    EvidenceStatus,
    ObjectClass,
    PublicObservation,
    RemoteIdStatus,
    WeatherVisibility,
)

from .manifests import NormalizationStats


FEATURE_SCHEMA_VERSION = "talon.features/3.0"
ACTIONS = tuple(DecisionAction)
ACTION_TO_INDEX = {action: index for index, action in enumerate(ACTIONS)}
ACTION_PADDING_INDEX = len(ACTIONS)

MISSING_EVIDENCE_CODES = (
    "additional_sensor_confirmation",
    "authorised_flight_match",
    "remote_id_match",
    "track_reacquisition",
    "operator_availability",
    "command_link_status",
)
MISSING_EVIDENCE_TO_INDEX = {code: index for index, code in enumerate(MISSING_EVIDENCE_CODES)}

OBJECT_CLASSES = tuple(ObjectClass)
REMOTE_ID_STATUSES = tuple(RemoteIdStatus)
AIRSPACE_STATUSES = tuple(AirspaceStatus)
VISIBILITY_STATES = tuple(WeatherVisibility)
AUTHORITY_LEVELS = tuple(AuthorityLevel)
COMMAND_LINK_STATES = tuple(CommandLinkStatus)
APPROVAL_STATES = tuple(ApprovalPublicStatus)
EVIDENCE_KINDS = tuple(EvidenceKind)
EVIDENCE_STATES = tuple(EvidenceStatus)


def feature_order() -> tuple[str, ...]:
    """Return the canonical scalar feature ordering bound into private datasets."""

    names = [
        "detection_confidence", "classification_confidence", "distance_m_scaled",
        "altitude_m_scaled", "speed_mps_scaled", "heading_deg_scaled",
        "approach_rate_mps_scaled", "track_age_s_scaled", "missed_frames_scaled",
        "track_quality", "sensor_agreement", "critical_asset_proximity_m_scaled",
        "critical_asset_proximity_present", "sensor_source_count_scaled",
        "evidence_requests_remaining_scaled", "related_track_count_scaled",
        "nearest_related_distance_scaled", "max_related_approach_scaled",
        "min_related_quality", "related_stale_fraction", "track_stale",
        "identity_conflict", "possible_crewed_aircraft", "people_nearby",
        "operator_available", "abstract_response_available",
        "authorised_flight_true", "authorised_flight_false", "authorised_flight_present",
        "emergency_services_true", "emergency_services_false", "emergency_services_present",
    ]
    for prefix, vocabulary in (
        ("object_class", OBJECT_CLASSES),
        ("remote_id", REMOTE_ID_STATUSES),
        ("airspace", AIRSPACE_STATUSES),
        ("visibility", VISIBILITY_STATES),
        ("authority", AUTHORITY_LEVELS),
        ("command_link", COMMAND_LINK_STATES),
        ("approval", APPROVAL_STATES),
    ):
        names.extend(f"{prefix}:{item.value}" for item in vocabulary)
    for kind in EVIDENCE_KINDS:
        names.append(f"evidence:{kind.value}:present")
        names.extend(f"evidence:{kind.value}:status:{status.value}" for status in EVIDENCE_STATES)
        names.extend((f"evidence:{kind.value}:age", f"evidence:{kind.value}:request_count"))
    names.append("previous_action:none")
    names.extend(f"previous_action:{action.value}" for action in ACTIONS)
    names.extend(f"related_object_fraction:{item.value}" for item in OBJECT_CLASSES)
    return tuple(names)


def _one_hot(value: object, values: Sequence[object]) -> list[float]:
    if value not in values:
        raise ValueError("categorical value is outside the feature vocabulary")
    return [1.0 if value == item else 0.0 for item in values]


def _nullable_boolean(value: bool | None) -> list[float]:
    return [1.0 if value is True else 0.0, 1.0 if value is False else 0.0, 1.0 if value is not None else 0.0]


def encode_observation(observation: PublicObservation) -> np.ndarray:
    if observation.schema_version != OBSERVATION_SCHEMA_VERSION:
        raise ValueError("observation schema version is incompatible with feature encoder")

    critical_present = observation.critical_asset_proximity_m is not None
    critical_value = observation.critical_asset_proximity_m if critical_present else 0.0
    related = observation.related_tracks
    nearest_related = min((item.distance_m for item in related), default=0.0)
    max_related_approach = max((item.approach_rate_mps for item in related), default=0.0)
    min_related_quality = min((item.track_quality for item in related), default=0.0)

    vector: list[float] = [
        observation.detection_confidence,
        observation.classification_confidence,
        min(observation.distance_m / 200_000.0, 1.0),
        min(max(observation.altitude_m + 100.0, 0.0) / 30_100.0, 1.0),
        min(observation.speed_mps / 500.0, 1.0),
        observation.heading_deg / 360.0,
        max(-1.0, min(1.0, observation.approach_rate_mps / 500.0)),
        min(observation.track_age_s / 86_400.0, 1.0),
        min(observation.missed_frames / 10_000.0, 1.0),
        observation.track_quality,
        observation.sensor_agreement,
        min(critical_value / 200_000.0, 1.0),
        1.0 if critical_present else 0.0,
        min(len(observation.sensor_sources) / 8.0, 1.0),
        min(observation.evidence_requests_remaining / 16.0, 1.0),
        min(len(related) / 7.0, 1.0),
        min(nearest_related / 200_000.0, 1.0),
        max(-1.0, min(1.0, max_related_approach / 500.0)),
        min_related_quality,
        min(sum(1 for item in related if item.track_stale) / 7.0, 1.0),
        float(observation.track_stale),
        float(observation.identity_conflict),
        float(observation.possible_crewed_aircraft),
        float(observation.people_nearby),
        float(observation.operator_available),
        float(observation.abstract_response_available),
        *_nullable_boolean(observation.authorised_flight_match),
        *_nullable_boolean(observation.emergency_services_match),
        *_one_hot(observation.object_class, OBJECT_CLASSES),
        *_one_hot(observation.remote_id_status, REMOTE_ID_STATUSES),
        *_one_hot(observation.airspace_status, AIRSPACE_STATUSES),
        *_one_hot(observation.weather_visibility, VISIBILITY_STATES),
        *_one_hot(observation.authority_level, AUTHORITY_LEVELS),
        *_one_hot(observation.command_link_status, COMMAND_LINK_STATES),
        *_one_hot(observation.approval_status, APPROVAL_STATES),
    ]

    evidence_by_kind = {item.kind: item for item in observation.evidence}
    for kind in EVIDENCE_KINDS:
        item = evidence_by_kind.get(kind)
        vector.append(1.0 if item is not None else 0.0)
        vector.extend(
            _one_hot(item.status, EVIDENCE_STATES)
            if item is not None
            else [0.0] * len(EVIDENCE_STATES)
        )
        vector.append(
            min(max(observation.timestamp_ms - item.requested_at_ms, 0) / 60_000.0, 1.0)
            if item is not None
            else 0.0
        )
        vector.append(min(item.request_count / 16.0, 1.0) if item is not None else 0.0)

    previous = observation.previous_action
    vector.extend([1.0 if previous is None else 0.0])
    vector.extend([1.0 if previous is action else 0.0 for action in ACTIONS])
    vector.extend(
        min(sum(1 for item in related if item.object_class is object_class) / 7.0, 1.0)
        for object_class in OBJECT_CLASSES
    )
    encoded = np.asarray(vector, dtype=np.float32)
    if not np.isfinite(encoded).all():
        raise ValueError("feature vector must contain only finite values")
    return encoded


def fit_normalization(vectors: np.ndarray) -> NormalizationStats:
    if vectors.ndim != 2 or vectors.shape[0] < 1 or vectors.shape[1] != FEATURE_DIM:
        raise ValueError("normalization requires a non-empty feature matrix")
    if not np.isfinite(vectors).all():
        raise ValueError("normalization input must be finite")
    mean = vectors.mean(axis=0, dtype=np.float64)
    scale = vectors.std(axis=0, dtype=np.float64)
    normalization_mask = scale >= 1e-8
    scale[~normalization_mask] = 1.0
    return NormalizationStats(
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        mean=tuple(float(value) for value in mean),
        scale=tuple(float(value) for value in scale),
        normalization_mask=tuple(bool(value) for value in normalization_mask),
        sample_count=int(vectors.shape[0]),
    )


def apply_normalization(vector: np.ndarray, stats: NormalizationStats) -> np.ndarray:
    if stats.feature_schema_version != FEATURE_SCHEMA_VERSION:
        raise ValueError("normalization feature schema is incompatible")
    if (
        len(stats.mean) != FEATURE_DIM
        or len(stats.scale) != FEATURE_DIM
        or len(stats.normalization_mask) != FEATURE_DIM
    ):
        raise ValueError("normalization dimensions are incompatible")
    normalized = (vector - np.asarray(stats.mean, dtype=np.float32)) / np.asarray(stats.scale, dtype=np.float32)
    return np.where(np.asarray(stats.normalization_mask, dtype=np.bool_), normalized, 0.0).astype(np.float32)


def action_index(action: DecisionAction) -> int:
    return ACTION_TO_INDEX[action]


def action_from_index(index: int) -> DecisionAction:
    if index < 0 or index >= len(ACTIONS):
        raise ValueError("invalid action index")
    return ACTIONS[index]


def missing_evidence_targets(codes: Sequence[str]) -> np.ndarray:
    targets = np.zeros((len(MISSING_EVIDENCE_CODES),), dtype=np.float32)
    for code in codes:
        index = MISSING_EVIDENCE_TO_INDEX.get(code)
        if index is not None:
            targets[index] = 1.0
    return targets


# A schema-valid sentinel gives a deterministic feature dimension while covering
# nullable and exactly-zero inputs without truthiness fallbacks.
_SENTINEL = PublicObservation(
    episode_id="ep_" + "0" * 24,
    timestamp_ms=0,
    state_revision=0,
    track_id="feature-shape",
    object_class=ObjectClass.UNKNOWN_AERIAL_OBJECT,
    detection_confidence=0,
    classification_confidence=0,
    distance_m=0,
    altitude_m=0,
    speed_mps=0,
    heading_deg=0,
    approach_rate_mps=0,
    track_age_s=0,
    missed_frames=0,
    track_quality=0,
    sensor_agreement=0,
    protected_zone="none",
    airspace_status=AirspaceStatus.OPEN,
    people_nearby=False,
    weather_visibility=WeatherVisibility.GOOD,
    operator_available=True,
    authority_level=AuthorityLevel.MONITORING_ONLY,
)
FEATURE_DIM = int(encode_observation(_SENTINEL).shape[0])
FEATURE_ORDER = feature_order()
if len(FEATURE_ORDER) != FEATURE_DIM:
    raise RuntimeError("feature ordering descriptor does not match encoded feature dimension")
