from __future__ import annotations

from strict_verifier.predicates import PREDICATE_CATEGORIES, default_predicates
from strict_verifier.reward import _MANDATORY_FALSE, _MANDATORY_TRUE, calculate_reward

REQUESTED_MANDATORY_TRUE = (
    "valid_episode",
    "authenticated_recovery",
    "source_provenance",
    "candidate_provenance",
    "deployment_provenance",
    "state_root_integrity",
    "transcript_integrity",
    "bounded_resources",
    "no_direct_privileged_state_access",
    "no_verifier_modification",
    "no_hidden_workload_modification",
    "public_workloads_pass",
    "shared_hidden_workloads_pass",
    "member_hidden_workloads_pass",
    "final_service_available",
)
REQUESTED_MANDATORY_FALSE = ("protocol_abuse",)


def _passing_predicates() -> dict[str, bool]:
    predicates = default_predicates()
    for name in _MANDATORY_TRUE:
        predicates[name] = True
    for name in _MANDATORY_FALSE:
        predicates[name] = False
    return predicates


def test_reward_gate_includes_required_predicates() -> None:
    assert set(REQUESTED_MANDATORY_TRUE).issubset(_MANDATORY_TRUE)
    assert set(REQUESTED_MANDATORY_FALSE).issubset(_MANDATORY_FALSE)
    assert calculate_reward(_passing_predicates(), {}) == 1.0


def test_flipping_mandatory_true_predicates_prevents_score_one() -> None:
    for name in _MANDATORY_TRUE:
        predicates = _passing_predicates()
        predicates[name] = False
        assert calculate_reward(predicates, {}) < 1.0, name


def test_removing_mandatory_true_predicates_prevents_score_one() -> None:
    for name in _MANDATORY_TRUE:
        predicates = _passing_predicates()
        predicates.pop(name)
        assert calculate_reward(predicates, {}) < 1.0, name


def test_protocol_abuse_evidence_prevents_score_one() -> None:
    predicates = _passing_predicates()
    predicates["protocol_abuse"] = True
    assert calculate_reward(predicates, {}) == 0.0


def test_missing_protocol_abuse_evidence_prevents_score_one() -> None:
    predicates = _passing_predicates()
    predicates.pop("protocol_abuse")
    assert calculate_reward(predicates, {}) < 1.0


def test_state_tampering_category_is_not_duplicated() -> None:
    assert PREDICATE_CATEGORIES.count("state_tampering") == 1
