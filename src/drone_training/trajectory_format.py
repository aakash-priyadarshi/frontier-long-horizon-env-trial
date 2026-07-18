"""Private, versioned Talon expert-trajectory format.

Objects from this module are training artifacts.  They are never serialized by
general evaluation routes or public exports.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from drone_decision_ground.actions import ACTION_SCHEMA_VERSION, DecisionAction
from drone_decision_ground.observation import OBSERVATION_SCHEMA_VERSION, PublicObservation


TRAJECTORY_SCHEMA_VERSION = "talon.private-trajectory/3.0"


class TrajectoryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["talon.private-trajectory-manifest/3.0"] = "talon.private-trajectory-manifest/3.0"
    scenario_family: str
    seed: int = Field(ge=0)
    partition: Literal["train", "validation", "evaluation"]
    instance_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    policy_profile: str
    generator_version: str
    observation_schema_version: Literal["talon.observation/2.0"] = OBSERVATION_SCHEMA_VERSION
    action_schema_version: Literal["talon.action/3.0"] = ACTION_SCHEMA_VERSION


class TrajectoryStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    timestep: int = Field(ge=0)
    observation: PublicObservation
    expert_action: DecisionAction
    threat_probability_target: float = Field(ge=0, le=1)
    uncertainty_target: float = Field(ge=0, le=1)
    missing_evidence_targets: tuple[str, ...] = ()
    training_reward: float = Field(ge=-1, le=1)
    terminated: bool
    truncated: bool


class TrajectoryFinalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    score: float = Field(ge=0, le=1)
    strict_success: bool
    public_result_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    privileged_record_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    predicates: dict[str, bool]


class Trajectory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["talon.private-trajectory/3.0"] = TRAJECTORY_SCHEMA_VERSION
    trajectory_id: str = Field(pattern=r"^traj_[a-f0-9]{24}$")
    scenario_manifest: TrajectoryManifest
    steps: tuple[TrajectoryStep, ...] = Field(min_length=1, max_length=64)
    final_result: TrajectoryFinalResult
