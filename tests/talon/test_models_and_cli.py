from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
import torch
from pydantic import ValidationError

from drone_decision_ground.observation import PublicObservation
from drone_decision_ground.scenarios import ScenarioConfig
from drone_decision_verifier.hidden_scenarios import build_environment, scenario_instance_digest
from drone_decision_verifier.leak_detection import find_public_leaks
from drone_training.behaviour_cloning import (
    TrainingConfig,
    encoded_examples,
    frozen_action_accuracy,
    returns_to_go,
    train_behavior_cloning,
)
from drone_training.checkpoints import file_digest, load_checkpoint, save_checkpoint
from drone_training.datasets import generate_dataset
from drone_training.decision_transformer import DecisionTransformerPolicy
from drone_training.evaluation import evaluate_checkpoint
from drone_training.features import ACTIONS, ACTION_PADDING_INDEX, FEATURE_DIM, encode_observation
from drone_training.gru_policy import GRUPolicy
from drone_training.policy_isolation import IsolatedPolicyClient
from drone_training.cli import build_parser


def tiny_dataset():
    return generate_dataset(partition="train", seeds=[0], families=["bird_false_positive"])


def config(architecture: str, seed: int = 7) -> TrainingConfig:
    return TrainingConfig(
        architecture=architecture,  # type: ignore[arg-type]
        epochs=2,
        learning_rate=0.01,
        batch_size=4,
        context_length=8,
        random_seed=seed,
        hidden_dim=24 if architecture == "gru" else 32,
        layers=1,
        heads=4,
        dropout=0.0,
    )


def save(tmp_path: Path, architecture: str = "gru"):
    dataset = tiny_dataset()
    model, history = train_behavior_cloning(dataset, config(architecture))
    checkpoint = tmp_path / f"{architecture}.pt"
    target = max(sum(step.training_reward for step in trajectory.steps) for trajectory in dataset.trajectories)
    digest = save_checkpoint(
        checkpoint,
        model=model,
        architecture=architecture,
        dataset_digest=dataset.manifest.dataset_digest,
        context_length=8,
        normalization=dataset.manifest.normalization,  # type: ignore[arg-type]
        training_instance_digests=dataset.manifest.scenario_instance_digests,
        seed_domain_digest=dataset.manifest.seed_domain_digest,
        return_conditioning_target=target,
    )
    return dataset, checkpoint, digest, history


def test_return_to_go_is_hand_calculated_and_padding_is_masked() -> None:
    assert returns_to_go([1.0, 0.0, -0.5]).tolist() == pytest.approx([0.5, -0.5, -0.5])
    assert returns_to_go([0.0, 0.0]).tolist() == [0.0, 0.0]
    dataset = tiny_dataset()
    arrays = encoded_examples(dataset, 8)
    first_length = int(arrays["mask"][0].sum())
    assert first_length == 1
    assert arrays["returns_to_go"][0, 0] == pytest.approx(
        sum(step.training_reward for step in dataset.trajectories[0].steps)
    )
    assert np.all(arrays["returns_to_go"][0, first_length:] == 0)


def test_feature_encoding_distinguishes_zero_missing_unknown_and_multitrack() -> None:
    scenario = ScenarioConfig(family_id="multiple_unrelated_tracks")
    raw, _ = build_environment(scenario).reset(seed=0, options={"scenario_config": scenario})
    observation = PublicObservation.model_validate(raw)
    missing = encode_observation(observation.model_copy(update={"critical_asset_proximity_m": None}))
    zero = encode_observation(observation.model_copy(update={"critical_asset_proximity_m": 0.0}))
    no_related = encode_observation(observation.model_copy(update={"related_tracks": ()}))
    assert missing.shape == zero.shape == (FEATURE_DIM,)
    assert not np.array_equal(missing, zero)
    assert not np.array_equal(zero, no_related)
    with pytest.raises(ValueError, match="categorical"):
        encode_observation(observation.model_copy(update={"object_class": "unknown-category"}))
    with pytest.raises(ValueError, match="schema version"):
        encode_observation(observation.model_copy(update={"schema_version": "talon.observation/1.0"}))
    with pytest.raises(ValidationError):
        PublicObservation.model_validate({**raw, "distance_m": float("nan")})
    with pytest.raises(ValidationError):
        PublicObservation.model_validate({**raw, "speed_mps": float("inf")})


@pytest.mark.parametrize("architecture", ["gru", "decision_transformer"])
def test_models_have_supervised_heads_only_and_respect_shapes(architecture: str) -> None:
    model = (
        GRUPolicy(hidden_dim=16, layers=1, dropout=0.0)
        if architecture == "gru"
        else DecisionTransformerPolicy(hidden_dim=32, layers=1, heads=4, context_length=4, dropout=0.0)
    )
    states = torch.zeros((2, 4, FEATURE_DIM))
    actions = torch.full((2, 4), ACTION_PADDING_INDEX, dtype=torch.long)
    mask = torch.tensor([[True, True, False, False], [True, True, True, True]])
    output = (
        model(states, actions, mask)
        if architecture == "gru"
        else model(states, actions, torch.ones((2, 4)), mask)
    )
    assert "policy_risk" not in output
    assert output["action_logits"].shape == (2, len(ACTIONS))
    assert output["missing_evidence"].shape[0] == 2


def test_decision_transformer_causal_mask_ignores_padded_future() -> None:
    model = DecisionTransformerPolicy(hidden_dim=32, layers=1, heads=4, context_length=4, dropout=0.0)
    model.eval()
    states = torch.randn((1, 4, FEATURE_DIM))
    actions = torch.full((1, 4), ACTION_PADDING_INDEX, dtype=torch.long)
    returns = torch.ones((1, 4))
    mask = torch.tensor([[True, True, False, False]])
    first = model(states, actions, returns, mask)["action_logits"]
    changed = states.clone()
    changed[:, 2:] = 1_000
    second = model(changed, actions, returns, mask)["action_logits"]
    assert torch.allclose(first, second, atol=1e-6)


def test_concurrent_training_is_reproducible_and_restores_global_rng() -> None:
    dataset = tiny_dataset()
    before_torch = torch.random.get_rng_state().clone()
    before_python = random.getstate()
    before_numpy = np.random.get_state()

    def train_once():
        model, history = train_behavior_cloning(dataset, config("gru", seed=13))
        return history, {key: value.detach().clone() for key, value in model.state_dict().items()}

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(lambda _: train_once(), range(2)))
    sequential = train_once()
    different_model, different_history = train_behavior_cloning(dataset, config("gru", seed=14))
    different = {
        key: value.detach().clone() for key, value in different_model.state_dict().items()
    }
    assert first[0] == second[0]
    assert first[0] == sequential[0]
    assert all(torch.equal(first[1][key], second[1][key]) for key in first[1])
    assert all(torch.equal(first[1][key], sequential[1][key]) for key in first[1])
    assert different_history != first[0] or any(
        not torch.equal(first[1][key], different[key]) for key in first[1]
    )
    assert torch.equal(before_torch, torch.random.get_rng_state())
    assert before_python == random.getstate()
    after_numpy = np.random.get_state()
    assert before_numpy[0] == after_numpy[0]
    assert np.array_equal(before_numpy[1], after_numpy[1])
    assert before_numpy[2:] == after_numpy[2:]


@pytest.mark.parametrize("architecture", ["gru", "decision_transformer"])
def test_atomic_checkpoint_and_isolated_frozen_evaluation(tmp_path: Path, architecture: str) -> None:
    dataset, checkpoint, digest, _ = save(tmp_path, architecture)
    assert file_digest(checkpoint) == digest
    _, metadata = load_checkpoint(checkpoint, expected_digest=digest)
    assert metadata["training_instance_digests"] == list(dataset.manifest.scenario_instance_digests)
    before = checkpoint.read_bytes()
    with IsolatedPolicyClient(checkpoint, expected_digest=digest) as policy:
        assert all(policy.probe().values())
    for probe in ("malformed_output", "oversized_output", "timeout"):
        with IsolatedPolicyClient(
            checkpoint,
            expected_digest=digest,
            timeout_seconds=5.0,
        ) as policy:
            if probe == "timeout":
                policy.timeout_seconds = 0.25
            assert all(policy.protocol_fault_probe(probe).values())
    evaluation = evaluate_checkpoint(
        checkpoint,
        family="bird_false_positive",
        seed=99,
        partition="evaluation",
        expected_checkpoint_digest=digest,
        timeout_seconds=20,
    )
    assert checkpoint.read_bytes() == before
    assert find_public_leaks(evaluation["public"]) == []
    assert evaluation["private"]["privileged_result"]["predicates"]


def test_contaminated_tampered_and_partial_checkpoints_are_rejected(tmp_path: Path) -> None:
    dataset = tiny_dataset()
    model, _ = train_behavior_cloning(dataset, config("gru"))
    evaluation_config = ScenarioConfig(family_id="bird_false_positive", partition="evaluation")
    overlap = scenario_instance_digest(evaluation_config, 4)
    checkpoint = tmp_path / "contaminated.pt"
    digest = save_checkpoint(
        checkpoint,
        model=model,
        architecture="gru",
        dataset_digest=dataset.manifest.dataset_digest,
        context_length=8,
        normalization=dataset.manifest.normalization,  # type: ignore[arg-type]
        training_instance_digests=(overlap,),
        seed_domain_digest=dataset.manifest.seed_domain_digest,
        return_conditioning_target=0.9,
    )
    with pytest.raises(ValueError, match="overlaps"):
        evaluate_checkpoint(checkpoint, family="bird_false_positive", seed=4, partition="evaluation", expected_checkpoint_digest=digest)

    checkpoint.chmod(0o600)
    checkpoint.write_bytes(checkpoint.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="digest mismatch"):
        load_checkpoint(checkpoint, expected_digest=digest)
    partial = tmp_path / "partial.pt"
    partial.write_bytes(b"not a checkpoint")
    from drone_training.checkpoints import file_digest

    with pytest.raises(ValueError, match="incomplete or invalid|digest mismatch|missing or malformed"):
        load_checkpoint(partial, expected_digest=file_digest(partial))
    with pytest.raises(ValueError, match="missing or malformed"):
        load_checkpoint(partial, expected_digest="")  # type: ignore[arg-type]


def test_evaluation_partition_cannot_be_optimized() -> None:
    evaluation = generate_dataset(partition="evaluation", seeds=[0], families=["bird_false_positive"])
    with pytest.raises(ValueError, match="training partition"):
        train_behavior_cloning(evaluation, config("gru"))


def test_validation_accuracy_is_frozen_and_uses_training_normalization() -> None:
    training = tiny_dataset()
    validation = generate_dataset(
        partition="validation",
        seeds=[0],
        families=["bird_false_positive"],
    )
    model, _ = train_behavior_cloning(training, config("gru"))
    before = {key: value.detach().clone() for key, value in model.state_dict().items()}
    accuracy = frozen_action_accuracy(
        model,
        validation,
        architecture="gru",
        context_length=8,
        training_normalization=training.manifest.normalization,
    )
    assert 0.0 <= accuracy <= 1.0
    assert all(torch.equal(before[key], value) for key, value in model.state_dict().items())
    assert model.training is False


def test_cli_dataset_timeout_is_explicit_and_validated() -> None:
    parsed = build_parser().parse_args(
        [
            "generate-dataset",
            "--output",
            "private.json",
            "--timeout-seconds",
            "7",
        ]
    )
    assert parsed.timeout_seconds == 7


def test_bc_checkpoint_rejects_mismatched_or_missing_env_verifier_versions(tmp_path: Path) -> None:
    from drone_decision_ground.environment import ENVIRONMENT_VERSION
    from drone_decision_verifier.scoring import VERIFIER_VERSION

    _, checkpoint, digest, _ = save(tmp_path, "gru")
    _, metadata = load_checkpoint(checkpoint, expected_digest=digest)
    assert metadata["environment_version"] == ENVIRONMENT_VERSION
    assert metadata["verifier_version"] == VERIFIER_VERSION

    checkpoint.chmod(0o600)
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    payload["environment_version"] = "talon.environment/0.0"
    torch.save(payload, checkpoint)
    with pytest.raises(ValueError, match="environment compatibility is incompatible"):
        load_checkpoint(checkpoint, expected_digest=file_digest(checkpoint))

    _, checkpoint2, _, _ = save(tmp_path / "v2", "gru")
    checkpoint2.chmod(0o600)
    payload = torch.load(checkpoint2, map_location="cpu", weights_only=False)
    payload["verifier_version"] = "talon.verifier/0.0"
    torch.save(payload, checkpoint2)
    with pytest.raises(ValueError, match="verifier compatibility is incompatible"):
        load_checkpoint(checkpoint2, expected_digest=file_digest(checkpoint2))

    _, checkpoint3, _, _ = save(tmp_path / "v3", "gru")
    checkpoint3.chmod(0o600)
    payload = torch.load(checkpoint3, map_location="cpu", weights_only=False)
    del payload["environment_version"]
    del payload["verifier_version"]
    torch.save(payload, checkpoint3)
    with pytest.raises(ValueError, match="unsupported checkpoint format"):
        load_checkpoint(checkpoint3, expected_digest=file_digest(checkpoint3))


def test_bc_architecture_config_mismatch_raises_sanitized_value_error(tmp_path: Path) -> None:
    """DT-only model_config fields must not surface as TypeError on GRU load."""

    _, checkpoint, _, _ = save(tmp_path, "decision_transformer")
    checkpoint.chmod(0o600)
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    payload["architecture"] = "gru"
    torch.save(payload, checkpoint)
    with pytest.raises(ValueError, match="model configuration is incompatible"):
        load_checkpoint(checkpoint, expected_digest=file_digest(checkpoint))

    _, gru_checkpoint, _, _ = save(tmp_path / "gru-extra", "gru")
    gru_checkpoint.chmod(0o600)
    payload = torch.load(gru_checkpoint, map_location="cpu", weights_only=False)
    payload["model_config"] = {**payload["model_config"], "heads": 8, "context_length": 20}
    torch.save(payload, gru_checkpoint)
    with pytest.raises(ValueError, match="model configuration is incompatible"):
        load_checkpoint(gru_checkpoint, expected_digest=file_digest(gru_checkpoint))
