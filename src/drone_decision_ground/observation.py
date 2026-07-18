"""Strict public observation schemas for the Talon policy boundary."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .actions import DecisionAction
from .authority import AuthorityLevel


OBSERVATION_SCHEMA_VERSION = "talon.observation/2.0"


class ObjectClass(str, Enum):
    UNKNOWN_AERIAL_OBJECT = "unknown_aerial_object"
    MULTIROTOR_DRONE = "multirotor_drone"
    FIXED_WING_DRONE = "fixed_wing_drone"
    HELICOPTER = "helicopter"
    CREWED_AIRCRAFT = "crewed_aircraft"
    BIRD = "bird"
    ENVIRONMENTAL_RETURN = "environmental_return"


class RemoteIdStatus(str, Enum):
    UNKNOWN = "unknown"
    VALID = "valid"
    MISSING = "missing"
    INCONSISTENT = "inconsistent"
    UNAVAILABLE = "unavailable"


class AirspaceStatus(str, Enum):
    OPEN = "open"
    CONTROLLED = "controlled"
    RESTRICTED = "restricted"
    TEMPORARILY_RESTRICTED = "temporarily_restricted"


class WeatherVisibility(str, Enum):
    GOOD = "good"
    MODERATE = "moderate"
    POOR = "poor"
    EXTREME = "extreme"


class EvidenceKind(str, Enum):
    SENSOR_CONFIRMATION = "sensor_confirmation"
    REMOTE_ID = "remote_id"
    FLIGHT_AUTHORISATION = "flight_authorisation"
    TRACK_REACQUISITION = "track_reacquisition"
    COMMAND_LINK = "command_link"


class EvidenceStatus(str, Enum):
    PENDING = "pending"
    AVAILABLE = "available"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    STALE = "stale"


class CommandLinkStatus(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    LOST = "lost"
    NOT_APPLICABLE = "not_applicable"


class ApprovalPublicStatus(str, Enum):
    NONE = "none"
    REQUESTED = "requested"
    AVAILABLE = "available"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    REVOKED = "revoked"


class PublicEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    kind: EvidenceKind
    status: EvidenceStatus
    requested_at_ms: int = Field(ge=0)
    completed_at_ms: int | None = Field(default=None, ge=0)
    valid_until_ms: int | None = Field(default=None, ge=0)
    provenance: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_]+$")
    request_count: int = Field(ge=1, le=16)


class RelatedTrack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    track_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    object_class: ObjectClass
    distance_m: float = Field(ge=0, le=200_000)
    approach_rate_mps: float = Field(ge=-500, le=500)
    track_quality: float = Field(ge=0, le=1)
    track_stale: bool = False


class PublicObservation(BaseModel):
    """Everything available to a learned policy at one simulated timestep."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: str = Field(default=OBSERVATION_SCHEMA_VERSION, pattern=r"^talon\.observation/2\.0$")
    episode_id: str = Field(pattern=r"^ep_[a-f0-9]{24}$")
    timestamp_ms: int = Field(ge=0)
    state_revision: int = Field(ge=0)
    track_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    object_class: ObjectClass
    detection_confidence: float = Field(ge=0, le=1)
    classification_confidence: float = Field(ge=0, le=1)
    distance_m: float = Field(ge=0, le=200_000)
    altitude_m: float = Field(ge=-100, le=30_000)
    speed_mps: float = Field(ge=0, le=500)
    heading_deg: float = Field(ge=0, lt=360)
    approach_rate_mps: float = Field(ge=-500, le=500)
    track_age_s: float = Field(ge=0, le=86_400)
    missed_frames: int = Field(ge=0, le=10_000)
    track_quality: float = Field(ge=0, le=1)
    track_stale: bool = False
    identity_conflict: bool = False
    possible_crewed_aircraft: bool = False
    sensor_agreement: float = Field(ge=0, le=1)
    sensor_sources: tuple[str, ...] = Field(default=("camera",), min_length=1, max_length=8)
    remote_id_status: RemoteIdStatus = RemoteIdStatus.UNKNOWN
    authorised_flight_match: bool | None = None
    emergency_services_match: bool | None = None
    command_link_status: CommandLinkStatus = CommandLinkStatus.UNKNOWN
    protected_zone: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    airspace_status: AirspaceStatus
    people_nearby: bool
    critical_asset_proximity_m: float | None = Field(default=None, ge=0, le=200_000)
    weather_visibility: WeatherVisibility
    operator_available: bool
    authority_level: AuthorityLevel
    abstract_response_available: bool = True
    evidence: tuple[PublicEvidence, ...] = Field(default=(), max_length=8)
    pending_evidence: tuple[EvidenceKind, ...] = Field(default=(), max_length=5)
    evidence_requests_remaining: int = Field(default=8, ge=0, le=16)
    related_tracks: tuple[RelatedTrack, ...] = Field(default=(), max_length=7)
    approval_status: ApprovalPublicStatus = ApprovalPublicStatus.NONE
    approval_id: str | None = Field(default=None, pattern=r"^apr_[a-f0-9]{24}$")
    approval_expires_at_ms: int | None = Field(default=None, ge=0)
    approval_scope_digest: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    previous_action: DecisionAction | None = None

    @field_validator("sensor_sources")
    @classmethod
    def validate_sources(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("sensor sources must be unique")
        if any(not value or len(value) > 40 or not value.replace("_", "").isalnum() for value in values):
            raise ValueError("sensor sources must be bounded identifiers")
        return values

    @field_validator("pending_evidence")
    @classmethod
    def validate_pending(cls, values: tuple[EvidenceKind, ...]) -> tuple[EvidenceKind, ...]:
        if len(set(values)) != len(values):
            raise ValueError("pending evidence kinds must be unique")
        return values

    @field_validator("related_tracks")
    @classmethod
    def validate_related_tracks(cls, values: tuple[RelatedTrack, ...]) -> tuple[RelatedTrack, ...]:
        ids = [value.track_id for value in values]
        if len(ids) != len(set(ids)):
            raise ValueError("related track identifiers must be unique")
        return values

    def public_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class ObservationWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = OBSERVATION_SCHEMA_VERSION
    observations: tuple[PublicObservation, ...] = Field(min_length=1, max_length=64)

    @field_validator("observations")
    @classmethod
    def chronological(cls, values: tuple[PublicObservation, ...]) -> tuple[PublicObservation, ...]:
        timestamps = [item.timestamp_ms for item in values]
        if timestamps != sorted(timestamps):
            raise ValueError("observation window must be chronological")
        return values
