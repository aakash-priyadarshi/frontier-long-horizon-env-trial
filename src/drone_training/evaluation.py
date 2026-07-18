"""Frozen-weight, overlap-safe Talon checkpoint evaluation."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np

try:
    import torch
    from torch import nn
except ImportError as exc:  # pragma: no cover - dependency guard
    raise ImportError("Talon evaluation requires the optional 'talon' dependency") from exc

from drone_decision_ground.actions import ACTION_SCHEMA_VERSION, DecisionAction, DecisionRecommendation
from drone_decision_ground.observation import PublicObservation
from drone_decision_ground.scenarios import ScenarioConfig
from drone_decision_verifier.hidden_scenarios import build_environment, scenario_instance_digest
from drone_decision_verifier.scoring import VERIFIER_VERSION

from .checkpoints import load_checkpoint
from .features import (
    ACTION_PADDING_INDEX,
    FEATURE_DIM,
    MISSING_EVIDENCE_CODES,
    action_from_index,
    action_index,
    apply_normalization,
    encode_observation,
)
from .manifests import EvaluationManifest, NormalizationStats, content_digest


class FrozenModelPolicy:
    def __init__(self, model: nn.Module, metadata: dict[str, Any], *, desired_return: float | None = None) -> None:
        self.model = model
        self.model.eval()
        self.metadata = metadata
        self.architecture = str(metadata["architecture"])
        self.context_length = int(metadata["context_length"])
        self.normalization = NormalizationStats.model_validate(metadata["normalization"])
        self.desired_return = float(
            metadata["return_conditioning_target"] if desired_return is None else desired_return
        )
        self._states: list[np.ndarray] = []
        self._previous_actions: list[int] = []
        self._returns: list[float] = []
        self._last_action: DecisionAction | None = None

    def reset(self) -> None:
        self._states = []
        self._previous_actions = []
        self._returns = []
        self._last_action = None

    def recommend(self, observation: PublicObservation) -> DecisionRecommendation:
        self._states.append(apply_normalization(encode_observation(observation), self.normalization))
        self._previous_actions.append(
            ACTION_PADDING_INDEX if self._last_action is None else action_index(self._last_action)
        )
        # Evaluated public rewards are intentionally zero/non-probing, so the
        # desired safe terminal return remains unchanged through the episode.
        self._returns.append(self.desired_return)
        selected_states = self._states[-self.context_length :]
        selected_actions = self._previous_actions[-self.context_length :]
        selected_returns = self._returns[-self.context_length :]
        length = len(selected_states)
        states = np.zeros((1, self.context_length, FEATURE_DIM), dtype=np.float32)
        actions = np.full((1, self.context_length), ACTION_PADDING_INDEX, dtype=np.int64)
        mask = np.zeros((1, self.context_length), dtype=np.bool_)
        returns = np.zeros((1, self.context_length), dtype=np.float32)
        states[0, :length] = selected_states
        actions[0, :length] = selected_actions
        mask[0, :length] = True
        returns[0, :length] = selected_returns
        with torch.inference_mode():
            if self.architecture == "gru":
                output = self.model(torch.from_numpy(states), torch.from_numpy(actions), torch.from_numpy(mask))
            else:
                output = self.model(
                    torch.from_numpy(states),
                    torch.from_numpy(actions),
                    torch.from_numpy(returns),
                    torch.from_numpy(mask),
                )
        probabilities = torch.softmax(output["action_logits"], dim=-1)[0]
        index = int(probabilities.argmax())
        selected = action_from_index(index)
        evidence_probabilities = torch.sigmoid(output["missing_evidence"])[0]
        missing_evidence = tuple(
            code
            for code, probability in zip(MISSING_EVIDENCE_CODES, evidence_probabilities)
            if float(probability) >= 0.5
        )
        self._last_action = selected
        return DecisionRecommendation(
            recommended_action=selected,
            target_track_id=observation.track_id,
            valid_until_ms=observation.timestamp_ms + 1_000,
            action_confidence=float(probabilities[index]),
            threat_probability=float(output["threat_probability"][0]),
            uncertainty=float(output["uncertainty"][0]),
            missing_evidence=missing_evidence,
            reason_codes=("frozen_learned_policy",),
        )


def evaluate_checkpoint(
    checkpoint: Path,
    *,
    family: str,
    seed: int,
    partition: str | None = None,
    split: str | None = None,
    expected_checkpoint_digest: str | None = None,
    environment_commit: str = "unknown",
    verifier_commit: str = "unknown",
    timeout_seconds: int = 30,
    policy_client: Any | None = None,
    step_callback: Any | None = None,
) -> dict[str, Any]:
    resolved_partition = partition or {"dev": "validation", "eval": "evaluation"}.get(str(split), split) or "evaluation"
    if resolved_partition not in {"validation", "evaluation"}:
        raise ValueError("frozen evaluation requires validation or evaluation partition")
    config = ScenarioConfig(family_id=family, partition=resolved_partition)  # type: ignore[arg-type]
    instance_digest = scenario_instance_digest(config, seed)
    _, metadata = load_checkpoint(checkpoint, expected_digest=expected_checkpoint_digest)
    if instance_digest in set(metadata["training_instance_digests"]):
        raise ValueError("evaluation instance overlaps checkpoint training instances")

    owned_policy = policy_client is None
    if policy_client is None:
        from .policy_isolation import IsolatedPolicyClient

        policy_client = IsolatedPolicyClient(
            checkpoint,
            expected_digest=str(metadata["checkpoint_digest"]),
            timeout_seconds=min(float(timeout_seconds), 10.0),
        )
    policy_client.reset()
    env = build_environment(config)
    raw_observation, _ = env.reset(seed=seed, options={"scenario_config": config})
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("evaluation exceeded its execution deadline")
            recommendation = policy_client.recommend(PublicObservation.model_validate(raw_observation))
            raw_observation, _, terminated, truncated, _ = env.step(recommendation)
            if step_callback is not None:
                step_callback(env.transcript()[-1])
            if terminated or truncated:
                break
    finally:
        if owned_policy:
            policy_client.close()
    result = env.grade()
    privileged_result = env.privileged_record()
    timeline = env.transcript()
    evaluation_id = "talon_eval_" + content_digest(
        {"checkpoint": metadata["checkpoint_digest"], "instance": instance_digest}
    ).split(":", 1)[1][:24]
    manifest = EvaluationManifest(
        evaluation_id=evaluation_id,
        model_checkpoint_digest=metadata["checkpoint_digest"],
        evaluation_instance_digests=(instance_digest,),
        environment_commit=environment_commit,
        verifier_commit=verifier_commit,
        verifier_version=VERIFIER_VERSION,
        observation_schema_version="talon.observation/2.0",
        action_schema_version=ACTION_SCHEMA_VERSION,
        maximum_steps=config.maximum_steps,
        timeout_seconds=timeout_seconds,
        result_digest=result["result_digest"],
    )
    return {
        "public": {
            "schema_version": "talon.public-evaluation-episode/2.0",
            "evaluation_id": evaluation_id,
            "checkpoint_digest": metadata["checkpoint_digest"],
            "environment_version": "talon.environment/2.0",
            "verifier_version": VERIFIER_VERSION,
            "result": result,
            "timeline": timeline,
        },
        "private": {
            "schema_version": "talon.private-evaluation-episode/2.0",
            "manifest": manifest.model_dump(mode="json"),
            "privileged_result": privileged_result,
        },
    }
