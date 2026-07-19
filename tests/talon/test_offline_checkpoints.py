"""Fail-closed integrity tests for Talon offline CQL checkpoints."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import torch

from drone_training.datasets import generate_dataset
from drone_training.features import ACTIONS, FEATURE_SCHEMA_VERSION
from drone_training.offline_checkpoints import (
    OFFLINE_CHECKPOINT_FORMAT_VERSION,
    inspect_offline_checkpoint,
    load_offline_checkpoint,
    save_offline_checkpoint,
)
from drone_training.offline_rl import (
    CQL_ALGORITHM_VERSION,
    CQLConfig,
    derive_offline_dataset,
    train_discrete_cql,
)


@pytest.fixture(scope="module")
def source_dataset():
    return generate_dataset(partition="train", seeds=[0], families=["authorised_inspection"])


@pytest.fixture(scope="module")
def offline_dataset(source_dataset):
    return derive_offline_dataset(source_dataset, context_length=4)


@pytest.fixture
def trained(offline_dataset):
    config = CQLConfig(
        context_length=4,
        hidden_dim=8,
        layers=1,
        dropout=0,
        batch_size=8,
        epochs=1,
        target_update_interval=2,
        random_seed=11,
    )
    model, target, history = train_discrete_cql(offline_dataset, config)
    updates = int(history.pop("training_updates", [0.0])[-1])
    return model, target, history, config, updates


def _save(tmp_path: Path, offline_dataset, trained, name: str = "checkpoint.pt") -> tuple[Path, str]:
    model, target, history, config, updates = trained
    path = tmp_path / name
    digest = save_offline_checkpoint(
        path,
        model=model,
        target=target,
        dataset=offline_dataset,
        config=config,
        training_history=history,
        training_updates=updates,
    )
    return path, digest


def _rewrite_payload(path: Path, mutator) -> None:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    mutator(payload)
    path.chmod(0o600)
    torch.save(payload, path)
    path.chmod(0o444)


def test_valid_checkpoint_loads_with_trusted_digest(tmp_path, offline_dataset, trained) -> None:
    path, digest = _save(tmp_path, offline_dataset, trained)
    model, target, metadata = load_offline_checkpoint(path, expected_digest=digest)
    assert metadata["format_version"] == OFFLINE_CHECKPOINT_FORMAT_VERSION
    assert metadata["checkpoint_digest"] == digest
    assert metadata["training_updates"] >= 1
    assert set(model.state_dict()) == set(target.state_dict())
    inspected = inspect_offline_checkpoint(path, expected_digest=digest)
    assert inspected["parameter_count"] == sum(item.numel() for item in model.parameters())


def test_missing_or_malformed_expected_digest_is_rejected(tmp_path, offline_dataset, trained) -> None:
    path, digest = _save(tmp_path, offline_dataset, trained)
    with pytest.raises(TypeError):
        load_offline_checkpoint(path)  # type: ignore[call-arg]
    for bad in (None, "", "sha256:deadbeef", "md5:" + "a" * 32, "sha256:" + "g" * 64):
        with pytest.raises(ValueError, match="missing or malformed"):
            load_offline_checkpoint(path, expected_digest=bad)  # type: ignore[arg-type]
    assert digest.startswith("sha256:")


def test_weight_tamper_is_rejected(tmp_path, offline_dataset, trained) -> None:
    path, digest = _save(tmp_path, offline_dataset, trained)

    def mutate(payload: dict) -> None:
        key = next(iter(payload["online_state_dict"]))
        payload["online_state_dict"][key] = payload["online_state_dict"][key] + 1.0

    _rewrite_payload(path, mutate)
    with pytest.raises(ValueError, match="digest mismatch"):
        load_offline_checkpoint(path, expected_digest=digest)


def test_target_weight_tamper_is_rejected(tmp_path, offline_dataset, trained) -> None:
    path, digest = _save(tmp_path, offline_dataset, trained)

    def mutate(payload: dict) -> None:
        key = next(iter(payload["target_state_dict"]))
        payload["target_state_dict"][key] = payload["target_state_dict"][key] + 0.5

    _rewrite_payload(path, mutate)
    with pytest.raises(ValueError, match="digest mismatch"):
        load_offline_checkpoint(path, expected_digest=digest)


@pytest.mark.parametrize("field", ["gamma", "cql_alpha", "safety_threshold"])
def test_training_config_mutations_are_rejected(tmp_path, offline_dataset, trained, field: str) -> None:
    path, digest = _save(tmp_path, offline_dataset, trained)
    mutated_value = {"gamma": 0.5, "cql_alpha": 9.0, "safety_threshold": 0.9}[field]

    def mutate(payload: dict) -> None:
        payload["training_config"] = dict(payload["training_config"])
        payload["training_config"][field] = mutated_value
        if field == "safety_threshold":
            payload["safety_threshold"] = mutated_value

    _rewrite_payload(path, mutate)
    with pytest.raises(ValueError, match="digest mismatch"):
        load_offline_checkpoint(path, expected_digest=digest)
    actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    expected_kwargs = {
        "expected_gamma": trained[3].gamma,
        "expected_cql_alpha": trained[3].cql_alpha,
        "expected_safety_threshold": trained[3].safety_threshold,
    }
    with pytest.raises(ValueError, match="training configuration mismatch"):
        load_offline_checkpoint(path, expected_digest=actual, **expected_kwargs)


def test_source_and_offline_digest_binding_mismatches_are_rejected(tmp_path, offline_dataset, trained) -> None:
    path, digest = _save(tmp_path, offline_dataset, trained)
    fake = "sha256:" + "ab" * 32
    with pytest.raises(ValueError, match="offline-dataset binding mismatch"):
        load_offline_checkpoint(
            path,
            expected_digest=digest,
            expected_offline_dataset_digest=fake,
        )
    with pytest.raises(ValueError, match="source-dataset binding mismatch"):
        load_offline_checkpoint(
            path,
            expected_digest=digest,
            expected_source_dataset_digest=fake,
        )


def test_schema_and_action_binding_mismatches_are_rejected(tmp_path, offline_dataset, trained) -> None:
    path, digest = _save(tmp_path, offline_dataset, trained)
    with pytest.raises(ValueError, match="action schema"):
        load_offline_checkpoint(
            path,
            expected_digest=digest,
            expected_actions=["CONTINUE_OBSERVATION"],
        )
    with pytest.raises(ValueError, match="algorithm is incompatible"):
        load_offline_checkpoint(
            path,
            expected_digest=digest,
            expected_algorithm_version="talon.discrete-cql/0.0",
        )
    with pytest.raises(ValueError, match="feature schema"):
        load_offline_checkpoint(
            path,
            expected_digest=digest,
            expected_feature_schema_version="talon.features/0.0",
        )


def test_embedded_digest_rewrite_is_not_trusted(tmp_path, offline_dataset, trained) -> None:
    path, digest = _save(tmp_path, offline_dataset, trained)

    def mutate(payload: dict) -> None:
        payload["checkpoint_digest"] = "sha256:" + "cd" * 32
        payload["claimed_digest"] = digest

    _rewrite_payload(path, mutate)
    with pytest.raises(ValueError, match="digest mismatch"):
        load_offline_checkpoint(path, expected_digest=digest)
    # Loading with the mutated file's real digest succeeds only for byte identity;
    # metadata still reports the verified file digest, not the embedded claim.
    actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    _, _, metadata = load_offline_checkpoint(path, expected_digest=actual)
    assert metadata["checkpoint_digest"] == actual
    assert metadata["checkpoint_digest"] != payload_claim(path)


def payload_claim(path: Path) -> str:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    return str(payload.get("checkpoint_digest"))


def test_cross_run_digest_substitution_is_rejected(tmp_path, offline_dataset, trained) -> None:
    first, first_digest = _save(tmp_path, offline_dataset, trained, "first.pt")
    other_config = CQLConfig(
        context_length=4,
        hidden_dim=8,
        layers=1,
        dropout=0,
        batch_size=8,
        epochs=1,
        target_update_interval=2,
        random_seed=99,
    )
    model, target, history = train_discrete_cql(offline_dataset, other_config)
    updates = int(history.pop("training_updates", [0.0])[-1])
    second = tmp_path / "second.pt"
    second_digest = save_offline_checkpoint(
        second,
        model=model,
        target=target,
        dataset=offline_dataset,
        config=other_config,
        training_history=history,
        training_updates=updates,
    )
    assert first_digest != second_digest
    with pytest.raises(ValueError, match="digest mismatch"):
        load_offline_checkpoint(first, expected_digest=second_digest)
    with pytest.raises(ValueError, match="digest mismatch"):
        load_offline_checkpoint(second, expected_digest=first_digest)


def test_legacy_v1_checkpoint_is_rejected_without_fabricating_target(tmp_path, offline_dataset, trained) -> None:
    model, _target, history, config, _updates = trained
    from drone_training.features import FEATURE_DIM

    path = tmp_path / "legacy.pt"
    payload = {
        "format_version": "talon.offline-rl-checkpoint/1.0",
        "algorithm_version": CQL_ALGORITHM_VERSION,
        "architecture": "cql_gru",
        "model_config": dict(model.config),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_dim": FEATURE_DIM,
        "actions": [item.value for item in ACTIONS],
        "offline_dataset_digest": offline_dataset.manifest.dataset_digest,
        "source_dataset_digest": offline_dataset.manifest.source_dataset_digest,
        "dataset_digest_verification": "recomputed",
        "training_instance_digests": list(offline_dataset.manifest.instance_digests),
        "seed_domain_digest": offline_dataset.manifest.seed_domain_digest,
        "normalization": offline_dataset.manifest.normalization.model_dump(mode="json"),
        "context_length": config.context_length,
        "safety_threshold": config.safety_threshold,
        "training_config": config.__dict__,
        "final_training_metrics": {key: value[-1] for key, value in history.items() if value},
        "state_dict": model.state_dict(),
    }
    torch.save(payload, path)
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="unsupported offline checkpoint format"):
        load_offline_checkpoint(path, expected_digest=digest)


def test_incompatible_environment_or_verifier_versions_are_rejected(tmp_path, offline_dataset, trained) -> None:
    path, digest = _save(tmp_path, offline_dataset, trained)

    def mutate_environment(payload: dict) -> None:
        payload["environment_version"] = "talon.environment/incompatible"

    _rewrite_payload(path, mutate_environment)
    with pytest.raises(ValueError, match="digest mismatch"):
        load_offline_checkpoint(path, expected_digest=digest)
    actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="environment compatibility"):
        load_offline_checkpoint(path, expected_digest=actual)

    path, digest = _save(tmp_path, offline_dataset, trained, "verifier.pt")

    def mutate_verifier(payload: dict) -> None:
        payload["verifier_version"] = "talon.verifier/incompatible"

    _rewrite_payload(path, mutate_verifier)
    actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="verifier compatibility"):
        load_offline_checkpoint(path, expected_digest=actual)


def test_partial_and_truncated_files_are_rejected(tmp_path, offline_dataset, trained) -> None:
    path, digest = _save(tmp_path, offline_dataset, trained)
    path.chmod(0o600)
    truncated = path.read_bytes()[:64]
    path.write_bytes(truncated)
    path.chmod(0o444)
    with pytest.raises(ValueError, match="digest mismatch"):
        load_offline_checkpoint(path, expected_digest=digest)
    actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="incomplete or invalid|unsupported"):
        load_offline_checkpoint(path, expected_digest=actual)
    garbage = tmp_path / "garbage.pt"
    garbage.write_bytes(b"not-a-torch-checkpoint")
    garbage_digest = "sha256:" + hashlib.sha256(garbage.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="incomplete or invalid"):
        load_offline_checkpoint(garbage, expected_digest=garbage_digest)


def test_public_errors_omit_filesystem_paths(tmp_path, offline_dataset, trained) -> None:
    missing = tmp_path / "does-not-exist.pt"
    digest = "sha256:" + "11" * 32
    with pytest.raises(ValueError) as raised:
        load_offline_checkpoint(missing, expected_digest=digest)
    message = str(raised.value)
    assert str(missing) not in message
    assert "offline checkpoint was not found" in message

    path, trusted = _save(tmp_path, offline_dataset, trained, "present.pt")
    with pytest.raises(ValueError) as mismatch:
        load_offline_checkpoint(path, expected_digest=digest)
    assert str(path) not in str(mismatch.value)


def test_save_requires_target_and_serializes_both_networks(tmp_path, offline_dataset, trained) -> None:
    model, target, history, config, updates = trained
    path = tmp_path / "both.pt"
    with pytest.raises(TypeError):
        save_offline_checkpoint(  # type: ignore[call-arg]
            path,
            model=model,
            dataset=offline_dataset,
            config=config,
            training_history=history,
        )
    digest = save_offline_checkpoint(
        path,
        model=model,
        target=target,
        dataset=offline_dataset,
        config=config,
        training_history=history,
        training_updates=updates,
    )
    payload = torch.load(path, map_location="cpu", weights_only=False)
    assert "online_state_dict" in payload and "target_state_dict" in payload
    assert "state_dict" not in payload
    loaded_model, loaded_target, metadata = load_offline_checkpoint(path, expected_digest=digest)
    assert metadata["training_updates"] == updates
    for key in model.state_dict():
        assert torch.equal(loaded_model.state_dict()[key], model.state_dict()[key])
        assert torch.equal(loaded_target.state_dict()[key], target.state_dict()[key])
