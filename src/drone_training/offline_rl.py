"""Conservative, simulation-only offline reinforcement learning for Talon.

The module consumes authenticated private Milestone 1 trajectories and never
interacts with a live environment during optimisation.  Operational utility and
safety cost are learned by independent critics.  The exported selector applies
the public policy mask and a safety threshold before consulting reward Q values;
when no action survives it deterministically abstains.
"""

from __future__ import annotations

import hmac
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

try:
    import torch
    from torch import Tensor, nn
except ImportError as exc:  # pragma: no cover - optional dependency guard
    raise ImportError("Talon offline RL requires the optional 'talon' dependency") from exc

from drone_decision_ground.actions import ACTION_SCHEMA_VERSION, DecisionAction, DecisionRecommendation
from drone_decision_ground.authority import policy_profile
from drone_decision_ground.observation import ApprovalPublicStatus, PublicObservation
from drone_decision_ground.policy_gate import PolicyGate

from .datasets import TrajectoryDataset, verify_dataset_integrity
from .features import ACTIONS, FEATURE_DIM, FEATURE_SCHEMA_VERSION, action_from_index, action_index, apply_normalization, encode_observation
from .manifests import NormalizationStats, content_digest


OFFLINE_DATASET_SCHEMA_VERSION = "talon.private-offline-rl-dataset/1.0"
OFFLINE_TRANSITION_SCHEMA_VERSION = "talon.private-offline-transition/1.0"
OFFLINE_DATASET_GENERATOR_VERSION = "talon.offline-transition-generator/1.0"
CQL_ALGORITHM_VERSION = "talon.discrete-cql/1.0"
ACTION_MASK_SCHEMA_VERSION = "talon.public-action-mask/1.0"


class OfflineTransition(BaseModel):
    """Private transition. Expert actions and targets must never be exported."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal["talon.private-offline-transition/1.0"] = OFFLINE_TRANSITION_SCHEMA_VERSION
    episode_id: str = Field(pattern=r"^ep_[a-f0-9]{24}$")
    timestep: int = Field(ge=0)
    observation_history: tuple[PublicObservation, ...] = Field(min_length=1, max_length=64)
    action: DecisionAction
    operational_reward: float = Field(ge=-1, le=1)
    safety_cost: float = Field(ge=0, le=1)
    next_observation_history: tuple[PublicObservation, ...] = Field(min_length=1, max_length=64)
    terminated: bool
    truncated: bool
    current_action_mask: tuple[bool, ...]
    next_action_mask: tuple[bool, ...]

    @field_validator("current_action_mask", "next_action_mask")
    @classmethod
    def validate_mask(cls, value: tuple[bool, ...]) -> tuple[bool, ...]:
        if len(value) != len(ACTIONS):
            raise ValueError("action mask does not match the action schema")
        if not any(value):
            raise ValueError("action mask must retain the fail-safe abstention action")
        return value


class OfflineRLDatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["talon.private-offline-rl-manifest/1.0"] = "talon.private-offline-rl-manifest/1.0"
    dataset_id: str = Field(pattern=r"^offline_[a-f0-9]{24}$")
    dataset_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    source_dataset_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    source_partition: Literal["train"] = "train"
    generator_version: Literal["talon.offline-transition-generator/1.0"] = OFFLINE_DATASET_GENERATOR_VERSION
    feature_schema_version: Literal["talon.features/3.0"] = FEATURE_SCHEMA_VERSION
    action_schema_version: Literal["talon.action/3.0"] = ACTION_SCHEMA_VERSION
    action_mask_schema_version: Literal["talon.public-action-mask/1.0"] = ACTION_MASK_SCHEMA_VERSION
    action_vocabulary: tuple[str, ...]
    context_length: int = Field(ge=1, le=64)
    transition_count: int = Field(ge=1)
    instance_digests: tuple[str, ...] = Field(min_length=1)
    seed_domain_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    normalization: NormalizationStats


class OfflineRLDataset(BaseModel):
    """Canonical private CQL input; never return from a public API route."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["talon.private-offline-rl-dataset/1.0"] = OFFLINE_DATASET_SCHEMA_VERSION
    manifest: OfflineRLDatasetManifest
    transitions: tuple[OfflineTransition, ...] = Field(min_length=1)


def _recommendation(action: DecisionAction, observation: PublicObservation) -> DecisionRecommendation:
    return DecisionRecommendation(
        recommended_action=action,
        target_track_id=observation.track_id,
        valid_until_ms=observation.timestamp_ms + 1_000,
        action_confidence=1.0,
        threat_probability=0.5,
        uncertainty=0.5,
    )


def public_action_mask(observation: PublicObservation, *, profile_id: str) -> tuple[bool, ...]:
    """Return a fail-closed, side-effect-free mask using only public state.

    Gate evaluation is performed without an approval verifier, so no approval can
    be consumed while constructing a dataset or choosing an action.  A mitigation
    recommendation is considered mask-valid only when its sole gate failure is
    the deliberately absent verifier and a fresh public approval is visible.  The
    real gate still verifies and atomically consumes the approval afterwards.
    """

    gate = PolicyGate(policy_profile(profile_id))
    mask: list[bool] = []
    for action in ACTIONS:
        decision = gate.evaluate(_recommendation(action, observation), observation)
        valid = decision.accepted
        if action is DecisionAction.RECOMMEND_AUTHORISED_MITIGATION:
            valid = (
                decision.violation_codes == ("approval_verifier_unavailable",)
                and observation.approval_status is ApprovalPublicStatus.AVAILABLE
                and observation.approval_id is not None
                and observation.approval_expires_at_ms is not None
                and observation.approval_expires_at_ms >= observation.timestamp_ms
            )
        mask.append(valid)
    # Fail-safe abstention must always remain representable.
    mask[action_index(DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE)] = True
    return tuple(mask)


def canonical_offline_dataset_digest_input(dataset: OfflineRLDataset) -> dict[str, Any]:
    manifest = dataset.manifest.model_dump(mode="json")
    manifest.pop("dataset_digest")
    return {
        "schema_version": dataset.schema_version,
        "manifest": manifest,
        "transitions": [item.model_dump(mode="json") for item in dataset.transitions],
    }


def recompute_offline_dataset_digest(dataset: OfflineRLDataset) -> str:
    return content_digest(canonical_offline_dataset_digest_input(dataset))


def verify_offline_dataset_integrity(dataset: OfflineRLDataset) -> OfflineRLDataset:
    manifest = dataset.manifest
    if not hmac.compare_digest(manifest.dataset_digest, recompute_offline_dataset_digest(dataset)):
        raise ValueError("offline dataset digest mismatch")
    if manifest.action_vocabulary != tuple(action.value for action in ACTIONS):
        raise ValueError("offline dataset action vocabulary is incompatible")
    if manifest.transition_count != len(dataset.transitions):
        raise ValueError("offline dataset transition count is inconsistent")
    if manifest.normalization.feature_schema_version != FEATURE_SCHEMA_VERSION:
        raise ValueError("offline dataset normalization is incompatible")
    if any(len(item.observation_history) > manifest.context_length for item in dataset.transitions):
        raise ValueError("offline dataset history exceeds the bound context length")
    by_episode: dict[str, list[OfflineTransition]] = {}
    for item in dataset.transitions:
        by_episode.setdefault(item.episode_id, []).append(item)
    for items in by_episode.values():
        if [item.timestep for item in items] != list(range(len(items))):
            raise ValueError("offline transition ordering is inconsistent")
        if not (items[-1].terminated or items[-1].truncated):
            raise ValueError("offline episode lacks a terminal transition")
        if any(item.terminated or item.truncated for item in items[:-1]):
            raise ValueError("offline episode contains an early terminal transition")
    return dataset


def load_offline_dataset(path: Path) -> OfflineRLDataset:
    if not path.is_file():
        raise ValueError("offline dataset was not found")
    try:
        parsed = OfflineRLDataset.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise ValueError("offline dataset schema is invalid") from exc
    return verify_offline_dataset_integrity(parsed)


def derive_offline_dataset(dataset: TrajectoryDataset, *, context_length: int = 20) -> OfflineRLDataset:
    """Derive deterministic static transitions from an authenticated train split."""

    verify_dataset_integrity(dataset)
    if dataset.manifest.generator_partition != "train" or dataset.manifest.normalization is None:
        raise ValueError("offline RL requires an authenticated training dataset")
    if not 1 <= context_length <= 64:
        raise ValueError("invalid offline context length")
    transitions: list[OfflineTransition] = []
    for trajectory in dataset.trajectories:
        observations = [step.observation for step in trajectory.steps]
        for index, step in enumerate(trajectory.steps):
            history = tuple(observations[max(0, index - context_length + 1): index + 1])
            next_index = min(index + 1, len(observations) - 1)
            next_history = tuple(observations[max(0, next_index - context_length + 1): next_index + 1])
            profile_id = trajectory.scenario_manifest.policy_profile
            transitions.append(
                OfflineTransition(
                    episode_id=step.observation.episode_id,
                    timestep=index,
                    observation_history=history,
                    action=step.expert_action,
                    operational_reward=step.training_reward,
                    # Verified safe-expert datasets contain no unsafe accepted actions.
                    # Gate-invalid actions are represented in the masks and treated
                    # conservatively by the safety critic's invalid-action margin.
                    safety_cost=0.0 if trajectory.final_result.predicates.get("no_safety_violation", True) else 1.0,
                    next_observation_history=next_history,
                    terminated=step.terminated,
                    truncated=step.truncated,
                    current_action_mask=public_action_mask(step.observation, profile_id=profile_id),
                    next_action_mask=public_action_mask(observations[next_index], profile_id=profile_id),
                )
            )
    identity = content_digest({
        "source_dataset_digest": dataset.manifest.dataset_digest,
        "context_length": context_length,
        "generator_version": OFFLINE_DATASET_GENERATOR_VERSION,
        "transitions": [item.model_dump(mode="json") for item in transitions],
    })
    manifest = OfflineRLDatasetManifest(
        dataset_id="offline_" + identity.split(":", 1)[1][:24],
        dataset_digest="sha256:" + "0" * 64,
        source_dataset_digest=dataset.manifest.dataset_digest,
        action_vocabulary=tuple(action.value for action in ACTIONS),
        context_length=context_length,
        transition_count=len(transitions),
        instance_digests=dataset.manifest.scenario_instance_digests,
        seed_domain_digest=dataset.manifest.seed_domain_digest,
        normalization=dataset.manifest.normalization,
    )
    provisional = OfflineRLDataset(manifest=manifest, transitions=tuple(transitions))
    completed = provisional.model_copy(update={
        "manifest": manifest.model_copy(update={"dataset_digest": recompute_offline_dataset_digest(provisional)})
    })
    return verify_offline_dataset_integrity(completed)


@dataclass(frozen=True)
class CQLConfig:
    context_length: int = 20
    hidden_dim: int = 256
    layers: int = 2
    dropout: float = 0.1
    gamma: float = 0.99
    cql_alpha: float = 1.0
    safety_threshold: float = 0.05
    learning_rate: float = 3e-4
    batch_size: int = 128
    epochs: int = 50
    target_update_interval: int = 500
    gradient_clip: float = 1.0
    random_seed: int = 0

    def validate(self) -> None:
        if self.context_length < 1 or self.context_length > 64 or self.hidden_dim < 8 or self.layers < 1:
            raise ValueError("invalid CQL model configuration")
        if not 0 <= self.dropout < 1 or not 0 <= self.gamma <= 1 or self.cql_alpha < 0:
            raise ValueError("invalid CQL objective configuration")
        if not 0 <= self.safety_threshold <= 1 or self.learning_rate <= 0:
            raise ValueError("invalid CQL optimisation configuration")
        if self.batch_size < 1 or self.epochs < 1 or self.target_update_interval < 1 or self.gradient_clip <= 0:
            raise ValueError("invalid CQL training bounds")


class ConservativeQNetwork(nn.Module):
    """GRU state encoder with separate operational-reward and safety-cost heads."""

    def __init__(self, *, hidden_dim: int = 256, layers: int = 2, dropout: float = 0.1) -> None:
        super().__init__()
        self.config = {"hidden_dim": hidden_dim, "layers": layers, "dropout": dropout}
        self.encoder = nn.GRU(
            FEATURE_DIM,
            hidden_dim,
            num_layers=layers,
            batch_first=True,
            dropout=dropout if layers > 1 else 0.0,
        )
        self.reward_head = nn.Linear(hidden_dim, len(ACTIONS))
        self.safety_head = nn.Linear(hidden_dim, len(ACTIONS))

    def forward(self, states: Tensor, mask: Tensor) -> dict[str, Tensor]:
        if states.ndim != 3 or mask.ndim != 2 or states.shape[:2] != mask.shape:
            raise ValueError("CQL sequence inputs are inconsistent")
        encoded, _ = self.encoder(states)
        lengths = mask.sum(dim=1).clamp(min=1).long() - 1
        final = encoded[torch.arange(encoded.shape[0], device=encoded.device), lengths]
        return {"reward_q": self.reward_head(final), "safety_q": torch.sigmoid(self.safety_head(final))}


def masked_argmax(reward_q: Tensor, safety_q: Tensor, action_mask: Tensor, safety_threshold: float) -> Tensor:
    if reward_q.shape != safety_q.shape or reward_q.shape != action_mask.shape:
        raise ValueError("Q values and action masks are inconsistent")
    eligible = action_mask.bool() & (safety_q <= safety_threshold)
    masked = reward_q.masked_fill(~eligible, -torch.inf)
    selected = masked.argmax(dim=-1)
    none_safe = ~eligible.any(dim=-1)
    if none_safe.any():
        selected = selected.clone()
        selected[none_safe] = action_index(DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE)
    return selected


def masked_max_q(q_values: Tensor, action_mask: Tensor) -> tuple[Tensor, Tensor]:
    """Return (max_q, argmax) over mask-valid actions only; invalid a' get -inf."""

    if q_values.shape != action_mask.shape:
        raise ValueError("Q values and action masks are inconsistent")
    masked = q_values.masked_fill(~action_mask.bool(), -torch.inf)
    max_q, argmax = masked.max(dim=-1)
    return max_q, argmax


def discrete_cql_loss(
    reward_q: Tensor,
    safety_q: Tensor,
    actions: Tensor,
    rewards: Tensor,
    costs: Tensor,
    next_reward_q: Tensor,
    next_safety_q: Tensor,
    current_mask: Tensor,
    next_mask: Tensor,
    done: Tensor,
    *,
    gamma: float,
    alpha: float,
    safety_threshold: float,
) -> dict[str, Tensor]:
    """Compute masked target-network TD targets plus discrete CQL regularisation.

    Reward TD target (non-terminal): ``r + gamma * max_{a' valid} Q_target(s', a')``.
    Terminal / truncated: ``done`` is 1 for either ``terminated`` or ``truncated``, so
    both intentionally disable bootstrapping (target = r / c only).  Safety cost uses
    the same greedy next action under the public mask.  Safety-threshold filtering is
    applied at action selection time via ``masked_argmax``, not inside the TD max.
    """

    chosen_reward = reward_q.gather(1, actions[:, None]).squeeze(1)
    chosen_safety = safety_q.gather(1, actions[:, None]).squeeze(1)
    with torch.no_grad():
        # Discrete CQL backup: max over mask-valid next actions only (no safety filter).
        next_reward, next_actions = masked_max_q(next_reward_q, next_mask)
        next_cost = next_safety_q.gather(1, next_actions[:, None]).squeeze(1)
        reward_target = rewards + gamma * (1.0 - done) * next_reward
        safety_target = costs + gamma * (1.0 - done) * next_cost
        safety_target = safety_target.clamp(0.0, 1.0)
    reward_td = torch.nn.functional.smooth_l1_loss(chosen_reward, reward_target)
    safety_td = torch.nn.functional.binary_cross_entropy(chosen_safety.clamp(1e-6, 1 - 1e-6), safety_target)
    valid_logits = reward_q.masked_fill(~current_mask.bool(), -torch.inf)
    cql_penalty = (torch.logsumexp(valid_logits, dim=1) - chosen_reward).mean()
    # Invalid public actions receive a conservative cost floor.  This closes the
    # zero-cost expert-data blind spot without inventing simulator rewards.
    invalid = ~current_mask.bool()
    invalid_cost_margin = (
        torch.relu((safety_threshold + 0.05) - safety_q)[invalid].mean()
        if invalid.any()
        else safety_q.new_zeros(())
    )
    total = reward_td + safety_td + alpha * cql_penalty + invalid_cost_margin
    return {
        "loss": total,
        "reward_td_loss": reward_td,
        "safety_td_loss": safety_td,
        "cql_penalty": cql_penalty,
        "invalid_cost_margin": invalid_cost_margin,
    }


def _encode_history(history: Sequence[PublicObservation], normalization: NormalizationStats, context_length: int) -> tuple[np.ndarray, np.ndarray]:
    selected = history[-context_length:]
    states = np.zeros((context_length, FEATURE_DIM), dtype=np.float32)
    mask = np.zeros((context_length,), dtype=np.bool_)
    for index, observation in enumerate(selected):
        states[index] = apply_normalization(encode_observation(observation), normalization)
        mask[index] = True
    return states, mask


def encoded_transitions(dataset: OfflineRLDataset) -> dict[str, np.ndarray]:
    verify_offline_dataset_integrity(dataset)
    arrays = [
        (
            _encode_history(item.observation_history, dataset.manifest.normalization, dataset.manifest.context_length),
            _encode_history(item.next_observation_history, dataset.manifest.normalization, dataset.manifest.context_length),
        )
        for item in dataset.transitions
    ]
    return {
        "states": np.stack([item[0][0] for item in arrays]),
        "sequence_mask": np.stack([item[0][1] for item in arrays]),
        "next_states": np.stack([item[1][0] for item in arrays]),
        "next_sequence_mask": np.stack([item[1][1] for item in arrays]),
        "actions": np.asarray([action_index(item.action) for item in dataset.transitions], dtype=np.int64),
        "rewards": np.asarray([item.operational_reward for item in dataset.transitions], dtype=np.float32),
        "costs": np.asarray([item.safety_cost for item in dataset.transitions], dtype=np.float32),
        "action_mask": np.asarray([item.current_action_mask for item in dataset.transitions], dtype=np.bool_),
        "next_action_mask": np.asarray([item.next_action_mask for item in dataset.transitions], dtype=np.bool_),
        # Truncation intentionally disables bootstrap (same as termination): the
        # post-horizon next state is treated as non-bootstrappable offline data.
        "done": np.asarray([item.terminated or item.truncated for item in dataset.transitions], dtype=np.float32),
    }


_TORCH_RNG_LOCK = threading.Lock()


def train_discrete_cql(
    dataset: OfflineRLDataset,
    config: CQLConfig,
    *,
    epoch_callback: Callable[[int, dict[str, float]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[ConservativeQNetwork, ConservativeQNetwork, dict[str, list[float]]]:
    config.validate()
    verified = verify_offline_dataset_integrity(dataset)
    if config.context_length != verified.manifest.context_length:
        raise ValueError("CQL context length differs from the authenticated dataset")
    raw = encoded_transitions(verified)
    tensors = {name: torch.from_numpy(value) for name, value in raw.items()}
    history = {name: [] for name in ("loss", "reward_td_loss", "safety_td_loss", "cql_penalty", "invalid_cost_margin", "mean_reward_q", "mean_safety_q")}
    with _TORCH_RNG_LOCK, torch.random.fork_rng(devices=[]):
        torch.manual_seed(config.random_seed)
        model = ConservativeQNetwork(hidden_dim=config.hidden_dim, layers=config.layers, dropout=config.dropout)
        target = ConservativeQNetwork(hidden_dim=config.hidden_dim, layers=config.layers, dropout=config.dropout)
        target.load_state_dict(model.state_dict())
        target.eval()
        optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate)
        generator = torch.Generator().manual_seed(config.random_seed)
        steps = 0
        size = tensors["states"].shape[0]
        for epoch in range(config.epochs):
            if cancelled is not None and cancelled():
                raise InterruptedError("offline RL training cancelled")
            model.train()
            sums = {name: 0.0 for name in history}
            count = 0
            permutation = torch.randperm(size, generator=generator)
            for start in range(0, size, config.batch_size):
                if cancelled is not None and cancelled():
                    raise InterruptedError("offline RL training cancelled")
                indices = permutation[start:start + config.batch_size]
                batch = {name: value[indices] for name, value in tensors.items()}
                optimizer.zero_grad(set_to_none=True)
                current = model(batch["states"], batch["sequence_mask"])
                with torch.no_grad():
                    following = target(batch["next_states"], batch["next_sequence_mask"])
                losses = discrete_cql_loss(
                    current["reward_q"], current["safety_q"], batch["actions"], batch["rewards"], batch["costs"],
                    following["reward_q"], following["safety_q"], batch["action_mask"], batch["next_action_mask"], batch["done"],
                    gamma=config.gamma, alpha=config.cql_alpha, safety_threshold=config.safety_threshold,
                )
                losses["loss"].backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), config.gradient_clip)
                optimizer.step()
                steps += 1
                if steps % config.target_update_interval == 0:
                    target.load_state_dict(model.state_dict())
                batch_size = len(indices)
                count += batch_size
                for name in losses:
                    sums[name] += float(losses[name].detach()) * batch_size
                sums["mean_reward_q"] += float(current["reward_q"].mean().detach()) * batch_size
                sums["mean_safety_q"] += float(current["safety_q"].mean().detach()) * batch_size
            metrics = {name: value / count for name, value in sums.items()}
            for name, value in metrics.items():
                history[name].append(value)
            if epoch_callback is not None:
                epoch_callback(epoch + 1, metrics)
        model.eval()
        history["training_updates"] = [float(steps)]
    return model, target, history


class CQLSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    action: DecisionAction
    abstained: bool
    reward_q: tuple[float, ...]
    safety_q: tuple[float, ...]
    public_action_mask: tuple[bool, ...]
    safety_action_mask: tuple[bool, ...]
    top_actions: tuple[tuple[str, float, float], ...]


def select_cql_action(
    model: ConservativeQNetwork,
    history: Sequence[PublicObservation],
    *,
    normalization: NormalizationStats,
    context_length: int,
    action_mask: Sequence[bool],
    safety_threshold: float,
) -> CQLSelection:
    if len(action_mask) != len(ACTIONS):
        raise ValueError("action mask does not match the action schema")
    states, sequence_mask = _encode_history(history, normalization, context_length)
    previous_mode = model.training
    model.eval()
    try:
        with torch.inference_mode():
            output = model(torch.from_numpy(states)[None, ...], torch.from_numpy(sequence_mask)[None, ...])
        reward_values = output["reward_q"][0]
        safety_values = output["safety_q"][0]
        public_mask = torch.tensor(tuple(action_mask), dtype=torch.bool)
        safe_mask = public_mask & (safety_values <= safety_threshold)
        selected = int(masked_argmax(reward_values[None, :], safety_values[None, :], public_mask[None, :], safety_threshold)[0])
        ranked = sorted(
            ((ACTIONS[index].value, float(reward_values[index]), float(safety_values[index])) for index in range(len(ACTIONS)) if safe_mask[index]),
            key=lambda item: (-item[1], item[0]),
        )[:5]
        action = action_from_index(selected)
        return CQLSelection(
            action=action,
            abstained=not bool(safe_mask.any()) or action is DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE,
            reward_q=tuple(float(value) for value in reward_values),
            safety_q=tuple(float(value) for value in safety_values),
            public_action_mask=tuple(bool(value) for value in public_mask),
            safety_action_mask=tuple(bool(value) for value in safe_mask),
            top_actions=tuple(ranked),
        )
    finally:
        model.train(previous_mode)


def frozen_cql_action_accuracy(
    model: ConservativeQNetwork,
    dataset: TrajectoryDataset,
    *,
    training_normalization: NormalizationStats | dict[str, Any],
    context_length: int,
    safety_threshold: float,
) -> float:
    """Expert-action agreement on a disjoint split with frozen weights."""

    verify_dataset_integrity(dataset)
    if dataset.manifest.generator_partition == "train":
        raise ValueError("CQL validation must use a disjoint non-training partition")
    normalization = (
        training_normalization
        if isinstance(training_normalization, NormalizationStats)
        else NormalizationStats.model_validate(training_normalization)
    )
    correct = 0
    count = 0
    previous_mode = model.training
    model.eval()
    try:
        for trajectory in dataset.trajectories:
            history: list[PublicObservation] = []
            for step in trajectory.steps:
                history.append(step.observation)
                selected = select_cql_action(
                    model,
                    history,
                    normalization=normalization,
                    context_length=context_length,
                    action_mask=public_action_mask(step.observation, profile_id=trajectory.scenario_manifest.policy_profile),
                    safety_threshold=safety_threshold,
                )
                correct += int(selected.action is step.expert_action)
                count += 1
        return correct / count if count else 0.0
    finally:
        model.train(previous_mode)
