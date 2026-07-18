from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from drone_decision_verifier.leak_detection import find_public_leaks
from drone_training.datasets import generate_dataset, load_dataset, recompute_dataset_digest
from drone_training.features import FEATURE_DIM, apply_normalization, encode_observation


def test_private_dataset_is_deterministic_and_digest_bound() -> None:
    first = generate_dataset(partition="train", seeds=[3], families=["missing_remote_id"])
    second = generate_dataset(partition="train", seeds=[3], families=["missing_remote_id"])
    assert first == second
    assert first.manifest.dataset_digest == second.manifest.dataset_digest
    assert first.manifest.scenario_instance_digests == second.manifest.scenario_instance_digests
    assert first.trajectories[0].final_result.strict_success is True
    assert first.trajectories[0].steps[-1].training_reward < 1.0
    assert recompute_dataset_digest(first) == first.manifest.dataset_digest


def test_every_integrity_relevant_dataset_mutation_is_rejected(tmp_path: Path) -> None:
    dataset = generate_dataset(
        partition="train",
        seeds=[3],
        families=["bird_false_positive", "missing_remote_id"],
    )
    original = dataset.model_dump(mode="json")

    def changed(path: str, mutate: object) -> None:
        payload = copy.deepcopy(original)
        mutate(payload)  # type: ignore[operator]
        target = tmp_path / f"{path}.json"
        target.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            load_dataset(target)

    changed("normalization-mean", lambda value: value["manifest"]["normalization"]["mean"].__setitem__(0, value["manifest"]["normalization"]["mean"][0] + 0.01))
    changed("normalization-scale", lambda value: value["manifest"]["normalization"]["scale"].__setitem__(0, value["manifest"]["normalization"]["scale"][0] + 0.01))
    changed("normalization-mask", lambda value: value["manifest"]["normalization"]["normalization_mask"].__setitem__(0, not value["manifest"]["normalization"]["normalization_mask"][0]))
    changed("observation", lambda value: value["trajectories"][0]["steps"][0]["observation"].__setitem__("distance_m", value["trajectories"][0]["steps"][0]["observation"]["distance_m"] + 1.0))
    changed("expert-action", lambda value: value["trajectories"][0]["steps"][0].__setitem__("expert_action", "CONTINUE_OBSERVATION" if value["trajectories"][0]["steps"][0]["expert_action"] != "CONTINUE_OBSERVATION" else "INCREASE_TRACK_PRIORITY"))
    changed("reward", lambda value: value["trajectories"][0]["steps"][-1].__setitem__("training_reward", value["trajectories"][0]["steps"][-1]["training_reward"] - 0.01))
    changed("partition", lambda value: value["manifest"].__setitem__("generator_partition", "validation"))
    changed("instance-digest", lambda value: value["manifest"]["scenario_instance_digests"].__setitem__(0, "sha256:" + "f" * 64))
    changed("schema-version", lambda value: value.__setitem__("schema_version", "talon.private-dataset/2.0"))
    changed("trajectory-order", lambda value: value["trajectories"].reverse())
    changed("trajectory-added", lambda value: value["trajectories"].append(copy.deepcopy(value["trajectories"][0])))
    changed("trajectory-removed", lambda value: value["trajectories"].pop())
    changed("malformed-digest", lambda value: value["manifest"].__setitem__("dataset_digest", "sha256:not-a-digest"))
    changed("missing-digest", lambda value: value["manifest"].pop("dataset_digest"))


def test_strict_dataset_loader_accepts_only_the_canonical_serialization(tmp_path: Path) -> None:
    dataset = generate_dataset(partition="train", seeds=[7], families=["lost_command_link"])
    target = tmp_path / "dataset.json"
    target.write_text(dataset.model_dump_json(), encoding="utf-8")
    loaded = load_dataset(target)
    assert loaded == dataset
    assert loaded.manifest.dataset_digest == recompute_dataset_digest(loaded)


def test_train_validation_evaluation_are_concretely_disjoint() -> None:
    values = {
        partition: generate_dataset(
            partition=partition,
            seeds=[5],
            families=["delivery_near_protected_zone", "sensor_disagreement"],
        )
        for partition in ("train", "validation", "evaluation")
    }
    digest_sets = {
        partition: set(dataset.manifest.scenario_instance_digests)
        for partition, dataset in values.items()
    }
    assert digest_sets["train"].isdisjoint(digest_sets["validation"])
    assert digest_sets["train"].isdisjoint(digest_sets["evaluation"])
    assert digest_sets["validation"].isdisjoint(digest_sets["evaluation"])

    sequences = {
        partition: [
            step.observation.model_dump(mode="json")
            for step in dataset.trajectories[0].steps
        ]
        for partition, dataset in values.items()
    }
    assert sequences["train"] != sequences["validation"] != sequences["evaluation"]
    actions = {
        partition: [
            [step.expert_action for step in trajectory.steps]
            for trajectory in dataset.trajectories
        ]
        for partition, dataset in values.items()
    }
    assert actions["train"] != actions["evaluation"]
    rewards = {
        partition: sum(step.training_reward for step in dataset.trajectories[0].steps)
        for partition, dataset in values.items()
    }
    assert len(set(rewards.values())) > 1


def test_normalization_is_fitted_only_on_training() -> None:
    training = generate_dataset(partition="train", seeds=[0], families=["bird_false_positive"])
    validation = generate_dataset(partition="validation", seeds=[0], families=["bird_false_positive"])
    evaluation = generate_dataset(partition="evaluation", seeds=[0], families=["bird_false_positive"])
    assert training.manifest.normalization is not None
    assert training.manifest.normalization.fitted_partition == "train"
    assert validation.manifest.normalization is None
    assert evaluation.manifest.normalization is None
    vector = encode_observation(training.trajectories[0].steps[0].observation)
    normalized = apply_normalization(vector, training.manifest.normalization)
    assert normalized.shape == (FEATURE_DIM,)
    assert np.isfinite(normalized).all()


def test_private_training_labels_are_detected_if_misrouted_to_public_export() -> None:
    dataset = generate_dataset(partition="train", seeds=[0], families=["authorised_inspection"])
    serialized = dataset.model_dump(mode="json")
    findings = find_public_leaks(serialized)
    assert any("hidden_family_value" in finding for finding in findings)
    assert any("privileged_key" in finding for finding in findings)


@pytest.mark.parametrize(
    "payload",
    [
        {"nested": [{"safe": "authorised_inspection"}]},
        {"nested": {"alias": "member_a"}},
        {"nested": {"value": "safe_final_disposition"}},
        {"expert_action": "STAND_DOWN"},
        {"message": r"C:\\private\\scenario.json"},
        {"authorization": "Bearer secret-token-value"},
    ],
)
def test_recursive_leak_detection_checks_keys_and_values(payload: dict[str, object]) -> None:
    assert find_public_leaks(payload), json.dumps(payload)
