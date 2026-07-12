from __future__ import annotations

import pytest

from strict_verifier.predicates import default_predicates
from strict_verifier.reward import calculate_reward


REQUIRED_STRICT_GATES = (
    "transcript_integrity",
    "bounded_resources",
    "authenticated_recovery",
    "source_provenance",
    "candidate_provenance",
    "deployment_provenance",
    "state_root_integrity",
    "no_direct_privileged_state_access",
    "verifier_integrity_pass",
    "workload_integrity_pass",
)


def _all_true() -> dict[str, bool]:
    predicates = {key: True for key in default_predicates()}
    predicates.update({key: True for key in REQUIRED_STRICT_GATES})
    predicates["valid_episode"] = True
    predicates["protocol_abuse"] = False
    predicates["state_tampering"] = False
    return predicates


@pytest.mark.parametrize("gate", REQUIRED_STRICT_GATES)
def test_false_strict_gate_prevents_score_one(gate: str) -> None:
    predicates = _all_true()
    predicates[gate] = False
    assert calculate_reward(predicates, {}) < 1.0


def test_protocol_abuse_prevents_score_one() -> None:
    predicates = _all_true()
    predicates["protocol_abuse"] = True
    assert calculate_reward(predicates, {}) < 1.0
