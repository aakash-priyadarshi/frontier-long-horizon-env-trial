"""Deterministic graded reward for the strict verifier."""

from __future__ import annotations

from typing import Any

_MANDATORY_TRUE: tuple[str, ...] = (
    "valid_episode",
    "initial_investigation",
    "diagnostic_evidence",
    "authenticated_recovery",
    "candidate_prepared",
    "source_provenance",
    "candidate_provenance",
    "deployment_provenance",
    "state_root_integrity",
    "integrity_provenance_pass",
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

_MANDATORY_FALSE: tuple[str, ...] = (
    "protocol_abuse",
)


def _mandatory_gate_passes(predicates: dict[str, bool]) -> bool:
    for name in _MANDATORY_TRUE:
        if predicates.get(name) is not True:
            return False
    for name in _MANDATORY_FALSE:
        if predicates.get(name) is not False:
            return False
    return True


def calculate_reward(predicates: dict[str, bool], details: dict[str, Any]) -> float:
    """Return a deterministic score in [0, 1] based on predicate outcomes."""

    if not predicates or predicates.get("valid_episode", True) is False:
        return 0.0

    if predicates.get("protocol_abuse", False):
        return 0.0

    if _mandatory_gate_passes(predicates):
        return 1.0

    if not predicates.get("transcript_integrity", False):
        return 0.0

    if not predicates.get("bounded_resources", False):
        return 0.0

    if not predicates.get("no_direct_privileged_state_access", False):
        return 0.0

    if not predicates.get("no_verifier_modification", False):
        return 0.0

    if not predicates.get("no_hidden_workload_modification", False):
        return 0.0

    if not predicates.get("initial_investigation", False):
        return 0.0

    if not predicates.get("diagnostic_evidence", False):
        return 0.10

    if not predicates.get("authenticated_recovery", False) or not predicates.get(
        "candidate_prepared", False
    ):
        return 0.25

    if not predicates.get("source_provenance", False) or not predicates.get(
        "candidate_provenance", False
    ):
        return 0.25

    if not predicates.get("public_workloads_pass", False):
        return 0.55

    if not predicates.get("shared_hidden_workloads_pass", False):
        return 0.70

    if not predicates.get("member_hidden_workloads_pass", False):
        return 0.85

    if not predicates.get("deployment_provenance", False):
        return 0.95

    if not predicates.get("state_root_integrity", False):
        return 0.95

    if not predicates.get("final_service_available", False):
        return 0.95

    return 0.95
