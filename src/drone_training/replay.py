"""Immutable, human-readable Talon evaluation replay records.

Replays are deliberately split into a public policy-visible document and a
post-termination privileged companion.  Neither view contains model chain of
thought.  Public exports are rebuilt through an allowlist rather than by
subtracting known-private fields.
"""

from __future__ import annotations

import hmac
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from drone_decision_ground.actions import DecisionAction
from drone_decision_ground.observation import PublicObservation
from drone_decision_ground.policy_gate import GateDecision

from .manifests import content_digest


PUBLIC_REPLAY_SCHEMA_VERSION = "talon.public-episode-replay/1.0"
PRIVILEGED_REPLAY_SCHEMA_VERSION = "talon.private-episode-replay/1.0"
REPLAY_STEP_SCHEMA_VERSION = "talon.public-replay-step/1.0"


class ReplayActionScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    action: DecisionAction
    operational_q: float
    safety_q: float = Field(ge=0, le=1)
    publicly_valid: bool
    below_safety_threshold: bool


class ReplayApprovalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str = Field(max_length=40)
    approval_id: str | None = Field(default=None, pattern=r"^apr_[a-f0-9]{24}$")
    expires_at_ms: int | None = Field(default=None, ge=0)
    consumed: bool = False


class PublicReplayStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal["talon.public-replay-step/1.0"] = REPLAY_STEP_SCHEMA_VERSION
    sequence: int = Field(ge=1)
    simulated_time_ms: int = Field(ge=0)
    observation: PublicObservation
    evidence_pending: tuple[str, ...]
    evidence_completed: tuple[str, ...]
    raw_action: DecisionAction
    action_confidence: float = Field(ge=0, le=1)
    abstained: bool
    top_action_scores: tuple[ReplayActionScore, ...] = Field(default=(), max_length=5)
    gate: GateDecision
    effective_action: DecisionAction
    approval: ReplayApprovalEvent
    terminated: bool
    truncated: bool


class PublicReplayMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    strict_success: bool
    score: float = Field(ge=0, le=1)
    safety_violation_count: int = Field(ge=0)
    action_count: int = Field(ge=0)
    abstention_rate: float = Field(ge=0, le=1)
    gate_intervention_rate: float = Field(ge=0, le=1)
    approval_correctness: float = Field(ge=0, le=1)
    evidence_efficiency: float = Field(ge=0, le=1)
    expected_calibration_error: float = Field(ge=0, le=1)
    failed_categories: tuple[str, ...]


class PublicEpisodeReplay(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["talon.public-episode-replay/1.0"] = PUBLIC_REPLAY_SCHEMA_VERSION
    replay_id: str = Field(pattern=r"^replay_[a-f0-9]{24}$")
    replay_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    evaluation_id: str
    episode_id: str = Field(pattern=r"^ep_[a-f0-9]{24}$")
    checkpoint_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    environment_version: str
    verifier_version: str
    terminal: Literal[True] = True
    metrics: PublicReplayMetrics
    steps: tuple[PublicReplayStep, ...] = Field(min_length=1)

    @field_validator("steps")
    @classmethod
    def ordered_steps(cls, value: tuple[PublicReplayStep, ...]) -> tuple[PublicReplayStep, ...]:
        if [item.sequence for item in value] != list(range(1, len(value) + 1)):
            raise ValueError("replay steps are not strictly ordered")
        if not (value[-1].terminated or value[-1].truncated):
            raise ValueError("replay does not terminate")
        return value


class PrivilegedReplayStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    operational_reward: float = Field(ge=-1, le=1)
    safety_cost: float = Field(ge=0, le=1)
    expert_action: DecisionAction | None = None


class PrivilegedEpisodeReplay(BaseModel):
    """Private verifier companion; storage only, never a general API response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["talon.private-episode-replay/1.0"] = PRIVILEGED_REPLAY_SCHEMA_VERSION
    replay_id: str = Field(pattern=r"^replay_[a-f0-9]{24}$")
    public_replay_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    privileged_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    hidden_scenario_type: str
    paired_member_identity: str | None = None
    true_intent: str
    safety_outcome: str
    verifier_predicates: dict[str, bool]
    steps: tuple[PrivilegedReplayStep, ...]


def _public_digest_input(replay: PublicEpisodeReplay) -> dict[str, Any]:
    value = replay.model_dump(mode="json")
    value.pop("replay_digest")
    return value


def recompute_public_replay_digest(replay: PublicEpisodeReplay) -> str:
    return content_digest(_public_digest_input(replay))


def verify_public_replay(replay: PublicEpisodeReplay) -> PublicEpisodeReplay:
    if not hmac.compare_digest(replay.replay_digest, recompute_public_replay_digest(replay)):
        raise ValueError("public replay digest mismatch")
    if any(item.observation.episode_id != replay.episode_id for item in replay.steps):
        raise ValueError("replay episode binding is inconsistent")
    return replay


def parse_public_replay_json(raw: str) -> PublicEpisodeReplay:
    try:
        replay = PublicEpisodeReplay.model_validate_json(raw)
    except ValidationError as exc:
        raise ValueError("public replay schema is invalid") from exc
    return verify_public_replay(replay)


def _completed_evidence(observation: PublicObservation) -> tuple[str, ...]:
    return tuple(
        item.kind.value
        for item in observation.evidence
        if item.completed_at_ms is not None and item.completed_at_ms <= observation.timestamp_ms
    )


def _step_from_timeline(value: dict[str, Any], diagnostic: dict[str, Any] | None) -> PublicReplayStep:
    observation = PublicObservation.model_validate(value["observation"])
    recommendation = value["recommendation"]
    gate = GateDecision.model_validate(value["gate"])
    scores: tuple[ReplayActionScore, ...] = ()
    if diagnostic is not None:
        safe_scores = diagnostic.get("top_action_scores", [])
        scores = tuple(ReplayActionScore.model_validate(item) for item in safe_scores[:5])
    return PublicReplayStep(
        sequence=int(value["sequence"]),
        simulated_time_ms=observation.timestamp_ms,
        observation=observation,
        evidence_pending=tuple(item.value for item in observation.pending_evidence),
        evidence_completed=_completed_evidence(observation),
        raw_action=DecisionAction(recommendation["recommended_action"]),
        action_confidence=float(recommendation["action_confidence"]),
        abstained=DecisionAction(recommendation["recommended_action"]) is DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE,
        top_action_scores=scores,
        gate=gate,
        effective_action=gate.effective_action,
        approval=ReplayApprovalEvent(
            status=observation.approval_status.value,
            approval_id=observation.approval_id,
            expires_at_ms=observation.approval_expires_at_ms,
            consumed=gate.approval_consumed,
        ),
        terminated=bool(value["terminated"]),
        truncated=bool(value["truncated"]),
    )


def build_public_replay(public_episode: dict[str, Any], *, decision_diagnostics: list[dict[str, Any]] | None = None) -> PublicEpisodeReplay:
    """Build an allowlisted immutable replay after strict grading has completed."""

    result = dict(public_episode["result"])
    timeline = list(public_episode["timeline"])
    if not timeline or not (timeline[-1].get("terminated") or timeline[-1].get("truncated")):
        raise ValueError("active episodes cannot produce a replay")
    diagnostics = decision_diagnostics or []
    steps = tuple(
        _step_from_timeline(value, diagnostics[index] if index < len(diagnostics) else None)
        for index, value in enumerate(timeline)
    )
    action_count = len(steps)
    evidence_requests = sum(1 for item in steps if item.raw_action.value.startswith(("REQUEST_", "CHECK_")))
    accepted_approvals = sum(1 for item in steps if item.gate.approval_consumed and item.gate.accepted)
    approval_attempts = sum(1 for item in steps if item.gate.human_approval_required)
    metrics = PublicReplayMetrics(
        strict_success=bool(result["strict_success"]),
        score=float(result["score"]),
        safety_violation_count=int(result["safety_violation_count"]),
        action_count=action_count,
        abstention_rate=sum(1 for item in steps if item.abstained) / action_count,
        gate_intervention_rate=sum(1 for item in steps if not item.gate.accepted) / action_count,
        approval_correctness=(accepted_approvals / approval_attempts if approval_attempts else 1.0),
        evidence_efficiency=max(0.0, 1.0 - evidence_requests / action_count),
        expected_calibration_error=float(result.get("expected_calibration_error", 0.0)),
        failed_categories=tuple(result.get("failed_categories", [])),
    )
    identity = content_digest({
        "evaluation_id": public_episode["evaluation_id"],
        "episode_id": result["episode_id"],
        "result_digest": result["result_digest"],
        "steps": [item.model_dump(mode="json") for item in steps],
    })
    provisional = PublicEpisodeReplay(
        replay_id="replay_" + identity.split(":", 1)[1][:24],
        replay_digest="sha256:" + "0" * 64,
        evaluation_id=str(public_episode["evaluation_id"]),
        episode_id=str(result["episode_id"]),
        checkpoint_digest=str(public_episode["checkpoint_digest"]),
        environment_version=str(public_episode["environment_version"]),
        verifier_version=str(public_episode["verifier_version"]),
        metrics=metrics,
        steps=steps,
    )
    return verify_public_replay(provisional.model_copy(update={"replay_digest": recompute_public_replay_digest(provisional)}))


def build_privileged_replay(
    public_replay: PublicEpisodeReplay,
    *,
    privileged_record: dict[str, Any],
    private_step_targets: list[dict[str, Any]],
) -> PrivilegedEpisodeReplay:
    """Build the private post-termination companion from privileged host data."""

    verify_public_replay(public_replay)
    context = dict(privileged_record.get("verifier_context", {}))
    predicates = dict(privileged_record.get("predicates", {}))
    raw_steps = tuple(
        PrivilegedReplayStep(
            sequence=index + 1,
            operational_reward=float(item.get("operational_reward", 0.0)),
            safety_cost=float(item.get("safety_cost", 0.0)),
            expert_action=DecisionAction(item["expert_action"]) if item.get("expert_action") else None,
        )
        for index, item in enumerate(private_step_targets)
    )
    base = {
        "replay_id": public_replay.replay_id,
        "public_replay_digest": public_replay.replay_digest,
        "hidden_scenario_type": str(context.get("family_key", context.get("scenario_family", "private"))),
        "paired_member_identity": context.get("pair_member"),
        "true_intent": str(context.get("threat_level", context.get("true_intent", "private"))),
        "safety_outcome": "safe" if int(public_replay.metrics.safety_violation_count) == 0 else "violation",
        "verifier_predicates": predicates,
    }
    digest_input = {**base, "steps": [item.model_dump(mode="json") for item in raw_steps]}
    return PrivilegedEpisodeReplay(
        **base,
        steps=raw_steps,
        privileged_digest=content_digest(digest_input),
    )


def public_replay_export(replay: PublicEpisodeReplay) -> dict[str, Any]:
    """Explicit public export allowlist; no privileged companion is accepted."""

    verified = verify_public_replay(replay)
    return {
        "schema_version": verified.schema_version,
        "replay_id": verified.replay_id,
        "replay_digest": verified.replay_digest,
        "evaluation_id": verified.evaluation_id,
        "episode_id": verified.episode_id,
        "checkpoint_digest": verified.checkpoint_digest,
        "environment_version": verified.environment_version,
        "verifier_version": verified.verifier_version,
        "terminal": True,
        "metrics": verified.metrics.model_dump(mode="json"),
        "steps": [item.model_dump(mode="json") for item in verified.steps],
    }
