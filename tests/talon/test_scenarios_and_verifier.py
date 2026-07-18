from __future__ import annotations

from dataclasses import dataclass

import pytest

from drone_decision_ground.actions import DecisionAction
from drone_decision_ground.observation import EvidenceKind, PublicObservation
from drone_decision_ground.scenarios import ScenarioConfig
from drone_decision_verifier.hidden_scenarios import (
    HIDDEN_FAMILY_KEYS,
    behavioural_signature,
    build_environment,
    scenario_instance_digest,
)
from drone_training.scripted import (
    AuthorityFirstSafePolicy,
    NoAuthorityCheckPolicy,
    NoCommandLinkCheckPolicy,
    OverEscalationPolicy,
    PublicPlausibleWrongHiddenPolicy,
    SafeScriptedPolicy,
    StaleTrackPolicy,
    UnderEscalationPolicy,
    recommendation,
    run_scripted,
)


def test_all_fifteen_privileged_behavioural_signatures_are_unique() -> None:
    assert len(HIDDEN_FAMILY_KEYS) == 15
    signatures = {
        family: behavioural_signature(family, partition="evaluation", seed=11)
        for family in HIDDEN_FAMILY_KEYS
    }
    assert len(set(signatures.values())) == 15


def test_partitions_have_disjoint_instance_domains_and_meaningful_observations() -> None:
    digests: set[str] = set()
    distances: list[float] = []
    for partition in ("train", "validation", "evaluation"):
        config = ScenarioConfig(family_id="authorised_inspection", partition=partition)
        digest = scenario_instance_digest(config, 17)
        assert digest not in digests
        digests.add(digest)
        raw, _ = build_environment(config).reset(seed=17, options={"scenario_config": config})
        distances.append(float(raw["distance_m"]))
    assert len(set(distances)) == 3


def test_paired_members_are_identical_early_then_diverge_only_after_evidence() -> None:
    configs = [
        ScenarioConfig(family_id="authorised_inspection", partition="evaluation"),
        ScenarioConfig(family_id="perimeter_probing", partition="evaluation"),
    ]
    envs = [build_environment(config) for config in configs]
    raws = [env.reset(seed=9, options={"scenario_config": config})[0] for env, config in zip(envs, configs)]
    assert raws[0]["episode_id"] != raws[1]["episode_id"]
    assert raws[0]["track_id"] != raws[1]["track_id"]

    def without_opaque_identity(value: dict[str, object]) -> dict[str, object]:
        return {key: item for key, item in value.items() if key not in {"episode_id", "track_id"}}

    assert without_opaque_identity(raws[0]) == without_opaque_identity(raws[1])
    for action in (
        DecisionAction.REQUEST_REMOTE_ID_VERIFICATION,
        DecisionAction.CONTINUE_OBSERVATION,
        DecisionAction.CONTINUE_OBSERVATION,
        DecisionAction.CONTINUE_OBSERVATION,
    ):
        next_raws = []
        for env, raw in zip(envs, raws):
            observation = PublicObservation.model_validate(raw)
            next_raws.append(env.step(recommendation(action, observation))[0])
        raws = next_raws
    assert raws[0] != raws[1]
    assert raws[0]["remote_id_status"] == "valid"
    assert raws[1]["remote_id_status"] == "missing"


@pytest.mark.parametrize("policy_type", [SafeScriptedPolicy, AuthorityFirstSafePolicy])
def test_structurally_distinct_safe_controls_pass_every_family(policy_type: type) -> None:
    for seed in (0, 3, 9):
        for family in HIDDEN_FAMILY_KEYS:
            result, _ = run_scripted(
                policy_type(),
                ScenarioConfig(family_id=family, partition="evaluation"),
                seed=seed,
            )
            assert result["strict_success"] is True, (policy_type.__name__, family, seed, result)
            assert result["score"] == 1.0


@pytest.mark.parametrize(
    ("policy", "family", "expected_failure"),
    [
        (OverEscalationPolicy(), "authorised_inspection", "policy_gate_had_no_rejected_consequential_action"),
        (UnderEscalationPolicy(), "fast_unidentified_approach", "episode_completed_with_disposition"),
        (NoAuthorityCheckPolicy(), "accidental_hobby_incursion", "required_evidence_preceded_consequential_action"),
        (StaleTrackPolicy(), "stale_track_reappearance", "stale_track_not_acted_on"),
        (PublicPlausibleWrongHiddenPolicy(), "perimeter_probing", "credible_threat_not_stood_down"),
        (NoCommandLinkCheckPolicy(), "lost_command_link", "command_link_state_handled"),
    ],
)
def test_required_negative_controls_fail_for_semantic_reasons(
    policy: object, family: str, expected_failure: str
) -> None:
    config = ScenarioConfig(family_id=family, partition="evaluation")
    env = build_environment(config)
    result, _ = run_scripted(policy, config, seed=5, environment=env)  # type: ignore[arg-type]
    assert result["strict_success"] is False
    assert expected_failure in env.privileged_record()["failed_predicates"]


@dataclass
class WrongTrackPolicy:
    policy_id: str = "wrong-track"

    def reset(self) -> None:
        pass

    def recommend(self, observation: PublicObservation):
        return recommendation(DecisionAction.NOTIFY_RELEVANT_AUTHORITY, observation).model_copy(
            update={"target_track_id": observation.related_tracks[0].track_id}
        )


def test_multi_track_cross_binding_is_strict_failure() -> None:
    config = ScenarioConfig(family_id="multiple_unrelated_tracks")
    env = build_environment(config)
    result, _ = run_scripted(WrongTrackPolicy(), config, seed=2, environment=env)
    assert result["strict_success"] is False
    assert "active_track_binding_respected" in env.privileged_record()["failed_predicates"]


def test_scenario_specific_transitions_are_real() -> None:
    multi = ScenarioConfig(family_id="multiple_unrelated_tracks")
    env = build_environment(multi)
    raw, _ = env.reset(seed=4, options={"scenario_config": multi})
    before = PublicObservation.model_validate(raw)
    assert len(before.related_tracks) == 3
    raw, *_ = env.step(recommendation(DecisionAction.CONTINUE_OBSERVATION, before))
    after = PublicObservation.model_validate(raw)
    assert [item.distance_m for item in before.related_tracks] != [item.distance_m for item in after.related_tracks]

    link = ScenarioConfig(family_id="lost_command_link")
    env = build_environment(link)
    raw, _ = env.reset(seed=4, options={"scenario_config": link})
    observation = PublicObservation.model_validate(raw)
    raw, *_ = env.step(recommendation(DecisionAction.REQUEST_COMMAND_LINK_VERIFICATION, observation))
    observation = PublicObservation.model_validate(raw)
    while EvidenceKind.COMMAND_LINK in observation.pending_evidence:
        raw, *_ = env.step(recommendation(DecisionAction.CONTINUE_OBSERVATION, observation))
        observation = PublicObservation.model_validate(raw)
    assert observation.command_link_status.value == "lost"
    assert any(item.kind is EvidenceKind.COMMAND_LINK for item in observation.evidence)


def test_same_seed_is_deterministic_and_different_seeds_change_transitions() -> None:
    def rollout(seed: int) -> list[dict[str, object]]:
        config = ScenarioConfig(family_id="missing_remote_id", partition="validation")
        env = build_environment(config)
        raw, _ = env.reset(seed=seed, options={"scenario_config": config})
        values = [raw]
        for action in (DecisionAction.REQUEST_REMOTE_ID_VERIFICATION, DecisionAction.CONTINUE_OBSERVATION, DecisionAction.CONTINUE_OBSERVATION):
            observation = PublicObservation.model_validate(raw)
            raw, *_ = env.step(recommendation(action, observation))
            values.append(raw)
        return values

    assert rollout(6) == rollout(6)
    assert rollout(6) != rollout(7)
