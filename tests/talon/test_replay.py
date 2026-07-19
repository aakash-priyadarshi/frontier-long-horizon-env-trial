from __future__ import annotations

import json

import pytest

from drone_decision_ground.observation import PublicObservation
from drone_decision_ground.scenarios import ScenarioConfig
from drone_decision_verifier.hidden_scenarios import build_environment
from drone_training.replay import (
    PublicEpisodeReplay,
    build_privileged_replay,
    build_public_replay,
    public_replay_export,
    verify_public_replay,
)
from drone_training.scripted import SafeScriptedPolicy


def _episode() -> dict:
    config = ScenarioConfig(family_id="authorised_inspection", partition="evaluation")
    env = build_environment(config)
    policy = SafeScriptedPolicy()
    raw, _ = env.reset(seed=0, options={"scenario_config": config})
    while True:
        recommendation = policy.recommend(PublicObservation.model_validate(raw))
        raw, _, terminated, truncated, _ = env.step(recommendation)
        if terminated or truncated:
            break
    return {
        "schema_version": "talon.public-evaluation-episode/3.0",
        "evaluation_id": "talon_eval_test",
        "checkpoint_digest": "sha256:" + "1" * 64,
        "environment_version": "talon.environment/2.0",
        "verifier_version": "talon.verifier/2.0",
        "result": env.grade(),
        "timeline": env.transcript(),
    }


def test_replay_is_terminal_ordered_digest_bound_and_allowlisted() -> None:
    replay = build_public_replay(_episode())
    assert replay.terminal is True
    assert [step.sequence for step in replay.steps] == list(range(1, len(replay.steps) + 1))
    assert verify_public_replay(replay) is replay
    exported = public_replay_export(replay)
    encoded = json.dumps(exported).lower()
    for forbidden in ("scenario_family", "true_intent", "verifier_predicates", "expert_action", "chain_of_thought", "reasoning"):
        assert forbidden not in encoded


def test_expert_targets_exist_only_in_the_privileged_post_terminal_replay() -> None:
    replay = build_public_replay(_episode())
    private = build_privileged_replay(
        replay,
        privileged_record={
            "verifier_context": {"family_key": "authorised_inspection", "threat_level": "benign"},
            "predicates": {"no_safety_violation": True},
        },
        private_step_targets=[
            {"operational_reward": 0.0, "safety_cost": 0.0, "expert_action": "CONTINUE_OBSERVATION"}
            for _ in replay.steps
        ],
    )
    assert all(step.expert_action is not None for step in private.steps)
    assert "expert_action" not in json.dumps(public_replay_export(replay)).lower()


def test_replay_mutation_and_reordering_are_rejected() -> None:
    replay = build_public_replay(_episode())
    raw = replay.model_dump(mode="json")
    raw["steps"][0]["action_confidence"] = .123
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_public_replay(PublicEpisodeReplay.model_validate(raw))
    raw = replay.model_dump(mode="json")
    raw["steps"] = list(reversed(raw["steps"]))
    with pytest.raises(ValueError, match="strictly ordered"):
        PublicEpisodeReplay.model_validate(raw)


def test_active_episode_cannot_be_replayed() -> None:
    episode = _episode()
    episode["timeline"][-1]["terminated"] = False
    episode["timeline"][-1]["truncated"] = False
    with pytest.raises(ValueError, match="active episodes"):
        build_public_replay(episode)
