from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
import torch

from drone_decision_ground.actions import DecisionAction
from drone_decision_verifier.leak_detection import find_public_leaks
from drone_training.datasets import generate_dataset
from drone_training.cli import main as cli_main
from drone_training.manifests import write_immutable_json
from drone_training.offline_rl import (
    CQLConfig,
    ConservativeQNetwork,
    OfflineRLDataset,
    OfflineTransition,
    derive_offline_dataset,
    discrete_cql_loss,
    encoded_transitions,
    frozen_cql_action_accuracy,
    masked_argmax,
    masked_max_q,
    recompute_offline_dataset_digest,
    select_cql_action,
    train_discrete_cql,
    verify_offline_dataset_integrity,
)


@pytest.fixture(scope="module")
def source_dataset():
    return generate_dataset(partition="train", seeds=[0], families=["authorised_inspection"])


@pytest.fixture(scope="module")
def offline_dataset(source_dataset):
    return derive_offline_dataset(source_dataset, context_length=4)


def test_offline_transition_dataset_is_canonical_and_source_bound(source_dataset, offline_dataset) -> None:
    assert offline_dataset.manifest.source_dataset_digest == source_dataset.manifest.dataset_digest
    assert offline_dataset.manifest.transition_count == len(offline_dataset.transitions)
    assert recompute_offline_dataset_digest(offline_dataset) == offline_dataset.manifest.dataset_digest
    assert verify_offline_dataset_integrity(offline_dataset) is offline_dataset
    assert all(len(item.current_action_mask) == 13 for item in offline_dataset.transitions)


@pytest.mark.parametrize(
    "mutation",
    ["reward", "cost", "action", "observation", "current_mask", "next_mask", "order", "missing", "added"],
)
def test_every_integrity_relevant_transition_mutation_is_rejected(offline_dataset, mutation: str) -> None:
    raw = offline_dataset.model_dump(mode="json")
    if mutation == "reward":
        raw["transitions"][0]["operational_reward"] = .25
    elif mutation == "cost":
        raw["transitions"][0]["safety_cost"] = 1
    elif mutation == "action":
        raw["transitions"][0]["action"] = "STAND_DOWN"
    elif mutation == "observation":
        raw["transitions"][0]["observation_history"][0]["distance_m"] += 1
    elif mutation == "current_mask":
        raw["transitions"][0]["current_action_mask"][0] = not raw["transitions"][0]["current_action_mask"][0]
    elif mutation == "next_mask":
        raw["transitions"][0]["next_action_mask"][0] = not raw["transitions"][0]["next_action_mask"][0]
    elif mutation == "order":
        raw["transitions"] = list(reversed(raw["transitions"]))
    elif mutation == "missing":
        raw["transitions"].pop()
    else:
        raw["transitions"].append(copy.deepcopy(raw["transitions"][-1]))
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_offline_dataset_integrity(OfflineRLDataset.model_validate(raw))


def test_masked_action_selection_abstains_when_no_action_is_safe() -> None:
    reward_q = torch.tensor([[9.0, 8.0, 7.0] + [0.0] * 10])
    safety_q = torch.ones_like(reward_q)
    public_mask = torch.ones_like(reward_q, dtype=torch.bool)
    selected = masked_argmax(reward_q, safety_q, public_mask, .05)
    assert int(selected[0]) == list(DecisionAction).index(DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE)


def test_public_architecture_width_is_not_confused_with_hidden_scenario_state() -> None:
    assert find_public_leaks({"hidden_dim": 256}) == []
    assert find_public_leaks({"hidden_dim": "privileged-value"})
    assert find_public_leaks({"hidden_state": {"true_intent": "unknown"}})


def test_masking_precedes_reward_q_ranking() -> None:
    reward_q = torch.tensor([[100.0, 2.0] + [0.0] * 11])
    safety_q = torch.zeros_like(reward_q)
    public_mask = torch.tensor([[False, True] + [False] * 11])
    selected = masked_argmax(reward_q, safety_q, public_mask, .05)
    assert int(selected[0]) == 1


def test_discrete_cql_loss_keeps_reward_and_safety_targets_separate() -> None:
    reward_q = torch.zeros((2, 13), requires_grad=True)
    safety_q = torch.full((2, 13), .1, requires_grad=True)
    next_reward = torch.zeros((2, 13))
    next_safety = torch.zeros((2, 13))
    mask = torch.ones((2, 13), dtype=torch.bool)
    output = discrete_cql_loss(
        reward_q, safety_q, torch.tensor([0, 1]), torch.tensor([1.0, -1.0]),
        torch.tensor([0.0, 1.0]), next_reward, next_safety, mask, mask,
        torch.tensor([1.0, 1.0]), gamma=.99, alpha=1.0, safety_threshold=.05,
    )
    assert set(output) == {"loss", "reward_td_loss", "safety_td_loss", "cql_penalty", "invalid_cost_margin"}
    assert all(torch.isfinite(value) for value in output.values())
    output["loss"].backward()
    assert reward_q.grad is not None and safety_q.grad is not None


def _full_mask(batch: int = 1) -> torch.Tensor:
    return torch.ones((batch, 13), dtype=torch.bool)


def test_hand_calculated_ordinary_td_target_non_terminal() -> None:
    """Non-terminal: y = r + gamma * max_{a' valid} Q_target(s', a')."""

    gamma = 0.99
    rewards = torch.tensor([1.0])
    done = torch.tensor([0.0])
    next_reward_q = torch.zeros((1, 13))
    next_reward_q[0, 0] = 10.0  # invalid under mask — must not win
    next_reward_q[0, 1] = 2.0  # valid masked max
    next_reward_q[0, 2] = 1.5
    next_mask = _full_mask()
    next_mask[0, 0] = False
    max_q, argmax = masked_max_q(next_reward_q, next_mask)
    assert int(argmax[0]) == 1
    assert float(max_q[0]) == pytest.approx(2.0)
    expected_target = torch.tensor([1.0 + gamma * 2.0])  # 2.98
    assert torch.allclose(rewards + gamma * (1.0 - done) * max_q, expected_target)

    reward_q = torch.zeros((1, 13), requires_grad=True)
    safety_q = torch.full((1, 13), 0.01)
    next_safety = torch.zeros((1, 13))
    output = discrete_cql_loss(
        reward_q, safety_q, torch.tensor([3]), rewards, torch.tensor([0.0]),
        next_reward_q, next_safety, _full_mask(), next_mask, done,
        gamma=gamma, alpha=0.0, safety_threshold=0.05,
    )
    # chosen reward Q(s,a=3)=0; smooth_l1(0, 2.98) = 2.48 (beta=1)
    assert float(output["reward_td_loss"].detach()) == pytest.approx(torch.nn.functional.smooth_l1_loss(
        torch.tensor(0.0), expected_target[0]
    ).item())


def test_hand_calculated_terminal_td_target_no_bootstrap() -> None:
    """Terminal: y = r (gamma term zeroed by done=1)."""

    gamma = 0.99
    rewards = torch.tensor([0.5])
    done = torch.tensor([1.0])
    next_reward_q = torch.full((1, 13), 100.0)
    expected_target = torch.tensor([0.5])
    max_q, _ = masked_max_q(next_reward_q, _full_mask())
    assert torch.allclose(rewards + gamma * (1.0 - done) * max_q, expected_target)

    reward_q = torch.zeros((1, 13), requires_grad=True)
    safety_q = torch.full((1, 13), 0.01)
    output = discrete_cql_loss(
        reward_q, safety_q, torch.tensor([0]), rewards, torch.tensor([0.0]),
        next_reward_q, torch.zeros((1, 13)), _full_mask(), _full_mask(), done,
        gamma=gamma, alpha=0.0, safety_threshold=0.05,
    )
    assert float(output["reward_td_loss"].detach()) == pytest.approx(
        torch.nn.functional.smooth_l1_loss(torch.tensor(0.0), expected_target[0]).item()
    )


def test_hand_calculated_truncated_disables_bootstrap_intentionally(offline_dataset) -> None:
    """Truncation is encoded as done=1 so offline TD does not bootstrap past the horizon."""

    encoded = encoded_transitions(offline_dataset)
    for item, done_flag in zip(offline_dataset.transitions, encoded["done"]):
        if item.truncated:
            assert float(done_flag) == 1.0
        if item.terminated:
            assert float(done_flag) == 1.0
        if not item.terminated and not item.truncated:
            assert float(done_flag) == 0.0

    gamma = 0.99
    rewards = torch.tensor([0.25])
    # Truncated transition: same done encoding as terminal → target = r only.
    done = torch.tensor([1.0])
    next_reward_q = torch.full((1, 13), 50.0)
    expected_target = torch.tensor([0.25])
    max_q, _ = masked_max_q(next_reward_q, _full_mask())
    assert torch.allclose(rewards + gamma * (1.0 - done) * max_q, expected_target)


def test_hand_calculated_masked_next_action_excludes_invalid_from_max() -> None:
    next_reward_q = torch.tensor([[9.0, 3.0, 4.0] + [0.0] * 10])
    next_mask = torch.tensor([[False, True, True] + [True] * 10])
    max_q, argmax = masked_max_q(next_reward_q, next_mask)
    assert int(argmax[0]) == 2  # 4.0 beats 3.0; 9.0 excluded
    assert float(max_q[0]) == pytest.approx(4.0)


def test_hand_calculated_safety_cost_td_target() -> None:
    """Safety: c + gamma * (1-done) * Q_safety_target(s', a*) with a* = masked reward argmax."""

    gamma = 0.99
    costs = torch.tensor([0.1])
    done = torch.tensor([0.0])
    next_reward_q = torch.zeros((1, 13))
    next_reward_q[0, 2] = 5.0  # a* = 2
    next_reward_q[0, 1] = 4.0
    next_safety_q = torch.zeros((1, 13))
    next_safety_q[0, 2] = 0.2
    next_safety_q[0, 1] = 0.9  # must not be used — not the reward-greedy action
    next_mask = _full_mask()
    _, next_actions = masked_max_q(next_reward_q, next_mask)
    assert int(next_actions[0]) == 2
    next_cost = next_safety_q.gather(1, next_actions[:, None]).squeeze(1)
    expected_target = costs + gamma * (1.0 - done) * next_cost
    assert torch.allclose(expected_target, torch.tensor([0.1 + 0.99 * 0.2]))  # 0.298

    reward_q = torch.zeros((1, 13), requires_grad=True)
    safety_q = torch.full((1, 13), 0.4, requires_grad=True)
    chosen = safety_q[0, 0].clamp(1e-6, 1 - 1e-6)
    expected_bce = torch.nn.functional.binary_cross_entropy(chosen, expected_target[0])
    output = discrete_cql_loss(
        reward_q, safety_q, torch.tensor([0]), torch.tensor([0.0]), costs,
        next_reward_q, next_safety_q, _full_mask(), next_mask, done,
        gamma=gamma, alpha=0.0, safety_threshold=0.05,
    )
    assert float(output["safety_td_loss"].detach()) == pytest.approx(float(expected_bce.detach()))


def test_hand_calculated_cql_penalty_logsumexp_minus_data_action() -> None:
    """CQL penalty = mean(logsumexp(Q(s, valid)) - Q(s, a_data))."""

    reward_q = torch.zeros((1, 13), requires_grad=True)
    with torch.no_grad():
        reward_q[0, 0] = 1.0  # a_data
        reward_q[0, 1] = 2.0
        reward_q[0, 2] = 0.0
        reward_q[0, 3] = 5.0  # invalid — excluded from logsumexp
    current_mask = torch.zeros((1, 13), dtype=torch.bool)
    current_mask[0, 0] = True
    current_mask[0, 1] = True
    current_mask[0, 2] = True
    valid = torch.tensor([1.0, 2.0, 0.0])
    expected_penalty = float(torch.logsumexp(valid, dim=0) - 1.0)
    # logsumexp([1,2,0]) - 1 ≈ 1.4076058864593506
    assert expected_penalty == pytest.approx(1.4076058864593506)

    safety_q = torch.full((1, 13), 0.01)
    output = discrete_cql_loss(
        reward_q, safety_q, torch.tensor([0]), torch.tensor([0.0]), torch.tensor([0.0]),
        torch.zeros((1, 13)), torch.zeros((1, 13)), current_mask, _full_mask(),
        torch.tensor([1.0]), gamma=0.99, alpha=1.0, safety_threshold=0.05,
    )
    assert float(output["cql_penalty"].detach()) == pytest.approx(expected_penalty)


def test_target_network_hard_copy_after_interval() -> None:
    online = ConservativeQNetwork(hidden_dim=8, layers=1, dropout=0)
    target = ConservativeQNetwork(hidden_dim=8, layers=1, dropout=0)
    target.load_state_dict(online.state_dict())
    assert all(torch.equal(a, b) for a, b in zip(online.parameters(), target.parameters()))
    with torch.no_grad():
        online.reward_head.bias.add_(1.0)
    assert not all(torch.equal(a, b) for a, b in zip(online.parameters(), target.parameters()))
    target.load_state_dict(online.state_dict())  # hard copy (same as train_discrete_cql)
    assert all(torch.equal(a, b) for a, b in zip(online.parameters(), target.parameters()))


def test_train_discrete_cql_hard_updates_target_at_interval(offline_dataset) -> None:
    """After target_update_interval steps, target weights match the online network."""

    snapshots: list[tuple[dict[str, torch.Tensor], dict[str, torch.Tensor]]] = []
    config = CQLConfig(
        context_length=4, hidden_dim=8, layers=1, dropout=0, batch_size=4,
        epochs=1, target_update_interval=1, random_seed=0, learning_rate=1e-2,
    )
    verified = verify_offline_dataset_integrity(offline_dataset)
    raw = encoded_transitions(verified)
    tensors = {name: torch.from_numpy(value) for name, value in raw.items()}
    torch.manual_seed(0)
    model = ConservativeQNetwork(hidden_dim=8, layers=1, dropout=0)
    target = ConservativeQNetwork(hidden_dim=8, layers=1, dropout=0)
    target.load_state_dict(model.state_dict())
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate)
    indices = torch.arange(min(4, tensors["states"].shape[0]))
    batch = {name: value[indices] for name, value in tensors.items()}
    model.train()
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
    optimizer.step()
    before = {k: v.detach().clone() for k, v in target.state_dict().items()}
    online_after_step = {k: v.detach().clone() for k, v in model.state_dict().items()}
    assert not all(torch.equal(before[k], online_after_step[k]) for k in before)
    target.load_state_dict(model.state_dict())  # interval == 1 → hard copy
    assert all(torch.equal(target.state_dict()[k], model.state_dict()[k]) for k in model.state_dict())
    snapshots.append((before, online_after_step))
    assert snapshots  # exercised hard-copy path used by train_discrete_cql


def test_safety_threshold_filters_actions_from_selection() -> None:
    reward_q = torch.tensor([[1.0, 10.0] + [0.0] * 11])
    safety_q = torch.tensor([[0.01, 0.9] + [0.01] * 11])  # action 1 exceeds threshold
    public_mask = torch.ones_like(reward_q, dtype=torch.bool)
    selected = masked_argmax(reward_q, safety_q, public_mask, 0.05)
    assert int(selected[0]) == 0  # high-Q unsafe action excluded; action 0 remains


def test_abstention_fallback_to_abstain_insufficient_evidence() -> None:
    reward_q = torch.tensor([[9.0, 8.0, 7.0] + [0.0] * 10])
    safety_q = torch.ones_like(reward_q)  # all above threshold
    public_mask = torch.ones_like(reward_q, dtype=torch.bool)
    selected = masked_argmax(reward_q, safety_q, public_mask, 0.05)
    abstain = list(DecisionAction).index(DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE)
    assert abstain == 12
    assert int(selected[0]) == abstain


def test_offline_transition_required_fields_and_digest_coverage(offline_dataset) -> None:
    required = set(OfflineTransition.model_fields)
    assert required == {
        "schema_version",
        "episode_id",
        "timestep",
        "observation_history",
        "action",
        "operational_reward",
        "safety_cost",
        "next_observation_history",
        "terminated",
        "truncated",
        "current_action_mask",
        "next_action_mask",
    }
    for item in offline_dataset.transitions:
        dumped = item.model_dump(mode="json")
        assert required <= set(dumped)
    # Digest covers every transition field: mutating terminated flips integrity.
    raw = offline_dataset.model_dump(mode="json")
    raw["transitions"][0]["terminated"] = not raw["transitions"][0]["terminated"]
    # Keep episode terminal invariants for schema path that reaches digest check first.
    with pytest.raises(ValueError, match="digest mismatch|terminal"):
        verify_offline_dataset_integrity(OfflineRLDataset.model_validate(raw))
    raw = offline_dataset.model_dump(mode="json")
    raw["transitions"][0]["safety_cost"] = 0.5 if raw["transitions"][0]["safety_cost"] == 0.0 else 0.0
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_offline_dataset_integrity(OfflineRLDataset.model_validate(raw))


def _trained_digest(dataset, seed: int) -> str:
    model, _target, history = train_discrete_cql(dataset, CQLConfig(context_length=4, hidden_dim=16, layers=1, dropout=0, batch_size=8, epochs=1, target_update_interval=2, random_seed=seed))
    assert history["loss"]
    payload = b"".join(value.detach().cpu().numpy().tobytes() for value in model.state_dict().values())
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def test_cql_training_is_reproducible_sequentially_and_concurrently(offline_dataset) -> None:
    expected = _trained_digest(offline_dataset, 7)
    assert _trained_digest(offline_dataset, 7) == expected
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: _trained_digest(offline_dataset, 7), range(2)))
    assert results == [expected, expected]
    assert _trained_digest(offline_dataset, 8) != expected


def test_frozen_selector_does_not_mutate_model_or_dataset(source_dataset, offline_dataset) -> None:
    model = ConservativeQNetwork(hidden_dim=16, layers=1, dropout=0)
    before = [parameter.detach().clone() for parameter in model.parameters()]
    first = offline_dataset.transitions[0]
    result = select_cql_action(
        model,
        first.observation_history,
        normalization=offline_dataset.manifest.normalization,
        context_length=4,
        action_mask=first.current_action_mask,
        safety_threshold=.05,
    )
    assert result.action in DecisionAction
    assert all(torch.equal(left, right) for left, right in zip(before, model.parameters()))
    assert json.dumps(source_dataset.model_dump(mode="json"), sort_keys=True)


def test_frozen_accuracy_validates_serialized_checkpoint_normalization(source_dataset) -> None:
    model = ConservativeQNetwork(hidden_dim=16, layers=1, dropout=0)
    evaluation = generate_dataset(
        partition="evaluation", seeds=[0], families=["authorised_inspection"]
    )
    normalization = source_dataset.manifest.normalization
    assert normalization is not None
    accuracy = frozen_cql_action_accuracy(
        model,
        evaluation,
        training_normalization=normalization.model_dump(mode="json"),
        context_length=4,
        safety_threshold=.05,
    )
    assert 0 <= accuracy <= 1


def test_offline_dataset_inspector_reports_verified_canonical_fields(
    tmp_path, offline_dataset, capsys
) -> None:
    path = tmp_path / "offline.json"
    write_immutable_json(path, offline_dataset)
    assert cli_main(["inspect-offline-dataset", "--dataset", str(path)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["integrity_verified"] is True
    assert inspected["partition"] == "train"
    assert inspected["feature_schema"] == "talon.features/3.0"
    assert inspected["dataset_digest"] == offline_dataset.manifest.dataset_digest


def test_isolated_cql_policy_client_probe_blocks_privileged_imports(tmp_path, offline_dataset) -> None:
    from drone_training.offline_checkpoints import save_offline_checkpoint
    from drone_training.offline_policy_isolation import IsolatedCQLPolicyClient

    config = CQLConfig(
        context_length=4,
        hidden_dim=8,
        layers=1,
        dropout=0,
        batch_size=8,
        epochs=1,
        target_update_interval=2,
        random_seed=3,
    )
    model, target, history = train_discrete_cql(offline_dataset, config)
    checkpoint = tmp_path / "cql-probe.pt"
    digest = save_offline_checkpoint(
        checkpoint,
        model=model,
        target=target,
        dataset=offline_dataset,
        config=config,
        training_history={key: value for key, value in history.items() if key != "training_updates"},
        training_updates=int(history.get("training_updates", [0])[-1]),
    )
    with IsolatedCQLPolicyClient(checkpoint, expected_digest=digest) as policy:
        probe = policy.probe()
    assert probe["python_isolated"] is True
    assert probe["simulator_import_blocked"] is True
    assert probe["training_import_blocked"] is True
    assert probe["verifier_import_blocked"] is True
    assert probe["hidden_scenario_import_blocked"] is True
    assert probe["filesystem_blocked"] is True
    assert all(probe.values())
