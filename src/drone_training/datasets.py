"""Deterministic private expert datasets with disjoint generator partitions."""

from __future__ import annotations

import hmac
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from drone_decision_ground.actions import ACTION_SCHEMA_VERSION
from drone_decision_ground.observation import OBSERVATION_SCHEMA_VERSION, PublicObservation
from drone_decision_ground.scenarios import ScenarioConfig
from drone_decision_verifier.hidden_scenarios import (
    HIDDEN_FAMILY_KEYS,
    HIDDEN_SCENARIO_VERSION,
    build_environment,
    scenario_instance_digest,
)

from .features import ACTIONS, FEATURE_DIM, FEATURE_ORDER, FEATURE_SCHEMA_VERSION, encode_observation, fit_normalization
from .manifests import DatasetManifest, content_digest
from .scripted import SafeScriptedPolicy
from .trajectory_format import Trajectory, TrajectoryFinalResult, TrajectoryManifest, TrajectoryStep


DATASET_SCHEMA_VERSION = "talon.private-dataset/3.0"
DATASET_GENERATOR_VERSION = "talon.dataset-generator/3.0"


class TrajectoryDataset(BaseModel):
    """Private training artifact; never return this object from a public route."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["talon.private-dataset/3.0"] = DATASET_SCHEMA_VERSION
    manifest: DatasetManifest
    trajectories: tuple[Trajectory, ...] = Field(min_length=1)


def feature_order_digest() -> str:
    return content_digest(
        {"feature_schema_version": FEATURE_SCHEMA_VERSION, "ordered_features": FEATURE_ORDER}
    )


def canonical_dataset_digest_input(dataset: TrajectoryDataset) -> dict[str, Any]:
    """Return the single canonical digest input; only the stored digest is omitted."""

    manifest = dataset.manifest.model_dump(mode="json")
    manifest.pop("dataset_digest")
    return {
        "schema_version": dataset.schema_version,
        "manifest": manifest,
        "trajectories": [item.model_dump(mode="json") for item in dataset.trajectories],
    }


def recompute_dataset_digest(dataset: TrajectoryDataset) -> str:
    return content_digest(canonical_dataset_digest_input(dataset))


def verify_dataset_integrity(dataset: TrajectoryDataset) -> TrajectoryDataset:
    """Authenticate every private dataset before it can affect preprocessing or weights."""

    recomputed = recompute_dataset_digest(dataset)
    if not hmac.compare_digest(dataset.manifest.dataset_digest, recomputed):
        raise ValueError("dataset digest mismatch")

    manifest = dataset.manifest
    trajectories = dataset.trajectories
    if manifest.dataset_generator_version != DATASET_GENERATOR_VERSION:
        raise ValueError("dataset generator version is incompatible")
    if manifest.feature_schema_version != FEATURE_SCHEMA_VERSION:
        raise ValueError("dataset feature schema is incompatible")
    if not hmac.compare_digest(manifest.feature_order_digest, feature_order_digest()):
        raise ValueError("dataset feature ordering is incompatible")
    if manifest.action_vocabulary != tuple(action.value for action in ACTIONS):
        raise ValueError("dataset action vocabulary is incompatible")
    if manifest.observation_schema_version != OBSERVATION_SCHEMA_VERSION:
        raise ValueError("dataset observation schema is incompatible")
    if manifest.action_schema_version != ACTION_SCHEMA_VERSION:
        raise ValueError("dataset action schema is incompatible")
    if manifest.scenario_generator_version != HIDDEN_SCENARIO_VERSION:
        raise ValueError("dataset scenario generator is incompatible")
    if manifest.trajectory_count != len(trajectories):
        raise ValueError("dataset trajectory count is inconsistent")

    partitions = {item.scenario_manifest.partition for item in trajectories}
    if partitions != {manifest.generator_partition}:
        raise ValueError("dataset trajectory partition is inconsistent")
    families = tuple(sorted({item.scenario_manifest.scenario_family for item in trajectories}))
    seeds = tuple(sorted({item.scenario_manifest.seed for item in trajectories}))
    if families != manifest.scenario_families or seeds != manifest.seeds:
        raise ValueError("dataset scenario domain is inconsistent")
    instances = tuple(sorted(item.scenario_manifest.instance_digest for item in trajectories))
    if instances != manifest.scenario_instance_digests or len(set(instances)) != len(instances):
        raise ValueError("dataset instance binding is inconsistent")
    expected_seed_domain = content_digest(
        {
            "generator": HIDDEN_SCENARIO_VERSION,
            "partition": manifest.generator_partition,
            "seeds": manifest.seeds,
        }
    )
    if not hmac.compare_digest(manifest.seed_domain_digest, expected_seed_domain):
        raise ValueError("dataset seed domain is inconsistent")

    for trajectory in trajectories:
        scenario = trajectory.scenario_manifest
        expected_instance = scenario_instance_digest(
            ScenarioConfig(family_id=scenario.scenario_family, partition=scenario.partition),
            scenario.seed,
        )
        if not hmac.compare_digest(scenario.instance_digest, expected_instance):
            raise ValueError("dataset scenario instance digest is inconsistent")
        if scenario.generator_version != HIDDEN_SCENARIO_VERSION:
            raise ValueError("trajectory generator version is incompatible")
        if [step.timestep for step in trajectory.steps] != list(range(len(trajectory.steps))):
            raise ValueError("trajectory timesteps are inconsistent")
        if not (trajectory.steps[-1].terminated or trajectory.steps[-1].truncated):
            raise ValueError("trajectory lacks a terminal step")
        if any(step.terminated or step.truncated for step in trajectory.steps[:-1]):
            raise ValueError("trajectory contains an early terminal marker")

    normalization = manifest.normalization
    if manifest.generator_partition == "train":
        if normalization is None:
            raise ValueError("training dataset lacks normalization")
        sample_count = sum(len(item.steps) for item in trajectories)
        if normalization.sample_count != sample_count:
            raise ValueError("normalization sample count is inconsistent")
        if (
            normalization.feature_schema_version != FEATURE_SCHEMA_VERSION
            or len(normalization.mean) != FEATURE_DIM
            or len(normalization.scale) != FEATURE_DIM
            or len(normalization.normalization_mask) != FEATURE_DIM
        ):
            raise ValueError("normalization schema is incompatible")
    elif normalization is not None:
        raise ValueError("non-training dataset contains normalization statistics")
    return dataset


def load_dataset(path: Path) -> TrajectoryDataset:
    """Strictly parse and authenticate a private dataset from disk."""

    if not path.is_file():
        raise ValueError("dataset was not found")
    try:
        dataset = TrajectoryDataset.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise ValueError("dataset schema is invalid") from exc
    return verify_dataset_integrity(dataset)


def generate_expert_trajectory(config: ScenarioConfig, *, seed: int) -> Trajectory:
    env = build_environment(config)
    policy = SafeScriptedPolicy()
    policy.reset()
    raw_observation, _ = env.reset(seed=seed, options={"scenario_config": config})
    provisional: list[dict[str, Any]] = []
    while True:
        observation = PublicObservation.model_validate(raw_observation)
        expert = policy.recommend(observation)
        raw_observation, _, terminated, truncated, _ = env.step(expert)
        provisional.append(
            {
                "timestep": len(provisional),
                "observation": observation,
                "expert_action": expert.recommended_action,
                "threat_probability_target": expert.threat_probability,
                "uncertainty_target": expert.uncertainty,
                "missing_evidence_targets": expert.missing_evidence,
                "training_reward": 0.0,
                "terminated": terminated,
                "truncated": truncated,
            }
        )
        if terminated or truncated:
            break

    public_result = env.grade()
    privileged = env.privileged_record()
    # The offline training reward is deliberately delayed to terminal.  It is a
    # private safe-outcome target, never the environment's public step reward.
    provisional[-1]["training_reward"] = max(
        -1.0,
        float(public_result["score"]) - min(len(provisional) * 0.005, 0.25),
    )
    steps = tuple(TrajectoryStep(**item) for item in provisional)
    instance_digest = scenario_instance_digest(config, seed)
    trajectory_id = "traj_" + content_digest(
        {
            "instance_digest": instance_digest,
            "policy": policy.policy_id,
            "actions": [step.expert_action.value for step in steps],
        }
    ).split(":", 1)[1][:24]
    return Trajectory(
        trajectory_id=trajectory_id,
        scenario_manifest=TrajectoryManifest(
            scenario_family=config.family_id,
            seed=seed,
            partition=config.partition,
            instance_digest=instance_digest,
            policy_profile=config.policy_profile,
            generator_version=HIDDEN_SCENARIO_VERSION,
        ),
        steps=steps,
        final_result=TrajectoryFinalResult(
            score=public_result["score"],
            strict_success=public_result["strict_success"],
            public_result_digest=public_result["result_digest"],
            privileged_record_digest=privileged["record_digest"],
            predicates=privileged["predicates"],
        ),
    )


def generate_dataset(
    *,
    partition: str | None = None,
    split: str | None = None,
    seeds: Iterable[int],
    families: Iterable[str] | None = None,
) -> TrajectoryDataset:
    # ``split`` is accepted only as a transition shim for the private CLI.  Public
    # schemas use the unambiguous partition names.
    raw_partition = partition or split
    aliases = {"dev": "validation", "eval": "evaluation"}
    resolved_partition = aliases.get(str(raw_partition), raw_partition)
    if resolved_partition not in {"train", "validation", "evaluation"}:
        raise ValueError("invalid generator partition")
    selected = tuple(sorted(families or HIDDEN_FAMILY_KEYS))
    selected_seeds = tuple(sorted(set(seeds)))
    if not selected_seeds or any(seed < 0 for seed in selected_seeds):
        raise ValueError("at least one non-negative seed is required")
    if set(selected) - set(HIDDEN_FAMILY_KEYS):
        raise ValueError("unknown privileged scenario family")

    trajectories = tuple(
        generate_expert_trajectory(
            ScenarioConfig(family_id=family, partition=resolved_partition),  # type: ignore[arg-type]
            seed=seed,
        )
        for family in selected
        for seed in selected_seeds
    )
    instance_digests = tuple(
        sorted(trajectory.scenario_manifest.instance_digest for trajectory in trajectories)
    )
    seed_domain_digest = content_digest(
        {
            "generator": HIDDEN_SCENARIO_VERSION,
            "partition": resolved_partition,
            "seeds": selected_seeds,
        }
    )
    normalization = None
    if resolved_partition == "train":
        matrix = np.stack(
            [encode_observation(step.observation) for trajectory in trajectories for step in trajectory.steps]
        )
        normalization = fit_normalization(matrix)
    content = [trajectory.model_dump(mode="json") for trajectory in trajectories]
    identity_digest = content_digest(
        {
            "schema_version": DATASET_SCHEMA_VERSION,
            "partition": resolved_partition,
            "seed_domain_digest": seed_domain_digest,
            "instance_digests": instance_digests,
            "normalization": normalization.model_dump(mode="json") if normalization else None,
            "trajectories": content,
        }
    )
    dataset_id = "dataset_" + identity_digest.split(":", 1)[1][:24]
    manifest = DatasetManifest(
        dataset_id=dataset_id,
        dataset_digest="sha256:" + "0" * 64,
        generator_partition=resolved_partition,  # type: ignore[arg-type]
        seed_domain_digest=seed_domain_digest,
        scenario_families=selected,
        seeds=selected_seeds,
        scenario_instance_digests=instance_digests,
        trajectory_count=len(trajectories),
        observation_schema_version=OBSERVATION_SCHEMA_VERSION,
        action_schema_version=ACTION_SCHEMA_VERSION,
        scenario_generator_version=HIDDEN_SCENARIO_VERSION,
        dataset_generator_version=DATASET_GENERATOR_VERSION,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        feature_order_digest=feature_order_digest(),
        action_vocabulary=tuple(action.value for action in ACTIONS),
        normalization=normalization,
    )
    provisional = TrajectoryDataset(
        manifest=manifest,
        trajectories=trajectories,
    )
    digest = recompute_dataset_digest(provisional)
    completed = provisional.model_copy(
        update={"manifest": manifest.model_copy(update={"dataset_digest": digest})}
    )
    return verify_dataset_integrity(completed)
