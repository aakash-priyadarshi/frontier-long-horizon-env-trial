"""Deterministic supervised training for the GRU and Decision Transformer."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Literal

import numpy as np

try:
    import torch
    from torch import Tensor, nn
except ImportError as exc:  # pragma: no cover - exercised by dependency guard
    raise ImportError("Talon training requires the optional 'talon' dependency") from exc

from .datasets import TrajectoryDataset, verify_dataset_integrity
from .decision_transformer import DecisionTransformerPolicy
from .features import (
    ACTION_PADDING_INDEX,
    FEATURE_DIM,
    action_index,
    apply_normalization,
    encode_observation,
    missing_evidence_targets,
)
from .gru_policy import GRUPolicy
from .manifests import NormalizationStats


@dataclass(frozen=True)
class TrainingConfig:
    architecture: Literal["gru", "decision_transformer"]
    epochs: int = 20
    learning_rate: float = 1e-3
    batch_size: int = 32
    context_length: int = 20
    random_seed: int = 0
    hidden_dim: int | None = None
    layers: int | None = None
    heads: int | None = None
    dropout: float = 0.1


_TORCH_RNG_LOCK = threading.Lock()


def returns_to_go(rewards: list[float] | np.ndarray) -> np.ndarray:
    """Canonical undiscounted return from each timestep, including that step."""

    values = np.asarray(rewards, dtype=np.float32)
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError("rewards must be a finite one-dimensional sequence")
    return np.cumsum(values[::-1], dtype=np.float32)[::-1].copy()


def _examples(
    dataset: TrajectoryDataset,
    context_length: int,
    *,
    normalization: Any | None = None,
    training_only: bool = True,
) -> dict[str, np.ndarray]:
    verify_dataset_integrity(dataset)
    states: list[np.ndarray] = []
    previous_actions: list[np.ndarray] = []
    masks: list[np.ndarray] = []
    returns: list[np.ndarray] = []
    targets: list[int] = []
    threat_targets: list[float] = []
    uncertainty_targets: list[float] = []
    evidence_targets: list[np.ndarray] = []
    raw_normalization = normalization or dataset.manifest.normalization
    fitted_normalization = (
        raw_normalization
        if isinstance(raw_normalization, NormalizationStats)
        else NormalizationStats.model_validate(raw_normalization)
        if raw_normalization is not None
        else None
    )
    if training_only and dataset.manifest.generator_partition != "train":
        raise ValueError("training examples require the training partition")
    if fitted_normalization is None:
        raise ValueError("training examples require training-only normalization statistics")
    for trajectory in dataset.trajectories:
        history_states: list[np.ndarray] = []
        history_actions: list[int] = []
        trajectory_returns = returns_to_go(
            [step.training_reward for step in trajectory.steps]
        )
        for index, step in enumerate(trajectory.steps):
            history_states.append(apply_normalization(encode_observation(step.observation), fitted_normalization))
            previous = ACTION_PADDING_INDEX if index == 0 else action_index(trajectory.steps[index - 1].expert_action)
            history_actions.append(previous)
            selected_states = history_states[-context_length:]
            selected_actions = history_actions[-context_length:]
            selected_returns = trajectory_returns[: index + 1][-context_length:]
            length = len(selected_states)
            state_array = np.zeros((context_length, FEATURE_DIM), dtype=np.float32)
            action_array = np.full((context_length,), ACTION_PADDING_INDEX, dtype=np.int64)
            mask_array = np.zeros((context_length,), dtype=np.bool_)
            return_array = np.zeros((context_length,), dtype=np.float32)
            state_array[:length] = selected_states
            action_array[:length] = selected_actions
            mask_array[:length] = True
            return_array[:length] = selected_returns
            states.append(state_array)
            previous_actions.append(action_array)
            masks.append(mask_array)
            returns.append(return_array)
            targets.append(action_index(step.expert_action))
            threat_targets.append(step.threat_probability_target)
            uncertainty_targets.append(step.uncertainty_target)
            evidence_targets.append(missing_evidence_targets(step.missing_evidence_targets))
    return {
        "states": np.stack(states),
        "previous_actions": np.stack(previous_actions),
        "mask": np.stack(masks),
        "returns_to_go": np.stack(returns),
        "action_targets": np.asarray(targets, dtype=np.int64),
        "threat_targets": np.asarray(threat_targets, dtype=np.float32),
        "uncertainty_targets": np.asarray(uncertainty_targets, dtype=np.float32),
        "missing_evidence_targets": np.stack(evidence_targets),
    }


def build_model(config: TrainingConfig) -> nn.Module:
    if config.architecture == "gru":
        return GRUPolicy(
            hidden_dim=config.hidden_dim or 128,
            layers=config.layers or 2,
            dropout=config.dropout,
        )
    return DecisionTransformerPolicy(
        hidden_dim=config.hidden_dim or 256,
        layers=config.layers or 6,
        heads=config.heads or 8,
        context_length=config.context_length,
        dropout=config.dropout,
    )


def _forward(model: nn.Module, architecture: str, batch: dict[str, Tensor]) -> dict[str, Tensor]:
    if architecture == "gru":
        return model(batch["states"], batch["previous_actions"], batch["mask"])  # type: ignore[no-any-return]
    return model(
        batch["states"], batch["previous_actions"], batch["returns_to_go"], batch["mask"]
    )  # type: ignore[no-any-return]


def train_behavior_cloning(
    dataset: TrajectoryDataset,
    config: TrainingConfig,
    *,
    epoch_callback: Callable[[int, dict[str, float]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[nn.Module, dict[str, list[float]]]:
    if dataset.manifest.generator_partition != "train":
        raise ValueError("only the training partition can be used for optimisation")
    if config.epochs < 1 or config.batch_size < 1 or config.context_length < 1:
        raise ValueError("invalid training configuration")
    arrays = _examples(dataset, config.context_length)
    tensors = {name: torch.from_numpy(value) for name, value in arrays.items()}
    # Model constructors use Torch's default generator. fork_rng restores its
    # state, the lock prevents concurrent in-process callers from observing the
    # temporary seed, and production jobs additionally run in separate spawned
    # processes. Python and NumPy global RNGs are never used by this path.
    with _TORCH_RNG_LOCK, torch.random.fork_rng(devices=[]):
        torch.manual_seed(config.random_seed)
        model = build_model(config)
        model.train()
        optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate)
        action_loss = nn.CrossEntropyLoss()
        regression_loss = nn.MSELoss()
        multi_label_loss = nn.BCEWithLogitsLoss()
        generator = torch.Generator().manual_seed(config.random_seed)
        history: dict[str, list[float]] = {"loss": [], "training_action_accuracy": []}
        size = tensors["states"].shape[0]
        for epoch in range(config.epochs):
            if cancelled is not None and cancelled():
                raise InterruptedError("training cancelled")
            permutation = torch.randperm(size, generator=generator)
            total_loss = 0.0
            total_correct = 0
            for start in range(0, size, config.batch_size):
                if cancelled is not None and cancelled():
                    raise InterruptedError("training cancelled")
                indices = permutation[start:start + config.batch_size]
                batch = {name: value[indices] for name, value in tensors.items()}
                optimizer.zero_grad(set_to_none=True)
                output = _forward(model, config.architecture, batch)
                loss = (
                    action_loss(output["action_logits"], batch["action_targets"])
                    + 0.25 * regression_loss(output["threat_probability"], batch["threat_targets"])
                    + 0.25 * regression_loss(output["uncertainty"], batch["uncertainty_targets"])
                    + 0.25 * multi_label_loss(
                        output["missing_evidence"], batch["missing_evidence_targets"]
                    )
                )
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                total_loss += float(loss.detach()) * len(indices)
                total_correct += int((output["action_logits"].argmax(dim=-1) == batch["action_targets"]).sum())
            history["loss"].append(total_loss / size)
            history["training_action_accuracy"].append(total_correct / size)
            if epoch_callback is not None:
                epoch_callback(
                    epoch + 1,
                    {
                        "loss": history["loss"][-1],
                        "training_action_accuracy": history["training_action_accuracy"][-1],
                    },
                )
        model.eval()
    return model, history


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


def encoded_examples(dataset: TrajectoryDataset, context_length: int) -> dict[str, np.ndarray]:
    """Expose deterministic arrays for frozen-weight evaluation and tests."""

    return _examples(dataset, context_length)


def frozen_action_accuracy(
    model: nn.Module,
    dataset: TrajectoryDataset,
    *,
    architecture: str,
    context_length: int,
    training_normalization: Any,
) -> float:
    """Measure private expert-action agreement without mutating model weights.

    Validation/evaluation datasets never carry normalization statistics.  Their
    public observations are transformed only with the supplied training-fitted
    statistics, and the entire pass runs under inference mode with no optimiser.
    """

    arrays = _examples(
        dataset,
        context_length,
        normalization=training_normalization,
        training_only=False,
    )
    batch = {name: torch.from_numpy(value) for name, value in arrays.items()}
    previous_mode = model.training
    model.eval()
    try:
        with torch.inference_mode():
            output = _forward(model, architecture, batch)
            correct = (
                output["action_logits"].argmax(dim=-1) == batch["action_targets"]
            ).sum()
        return float(correct) / int(batch["action_targets"].shape[0])
    finally:
        model.train(previous_mode)
