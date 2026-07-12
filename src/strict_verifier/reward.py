"""Deterministic graded reward for the strict verifier."""

from __future__ import annotations

from typing import Any


def calculate_reward(predicates: dict[str, bool], details: dict[str, Any]) -> float:
    """Return a deterministic score in [0, 1] based on predicate outcomes.

    The ladder is intentionally documented and monotonic. It does not trust
    agent-authored success flags.
    """

    if not predicates or predicates.get("valid_episode", True) is False:
        return 0.0

    if predicates.get("protocol_abuse", False) or predicates.get("state_tampering", False):
        return 0.0

    if not predicates.get("initial_investigation", False):
        return 0.0

    if not predicates.get("diagnostic_evidence", False):
        return 0.10

    if not predicates.get("authenticated_recovery", False) or not predicates.get("candidate_prepared", False):
        return 0.25

    if not predicates.get("public_workloads_pass", False):
        return 0.55

    if not predicates.get("shared_hidden_workloads_pass", False):
        return 0.70

    if not predicates.get("member_hidden_workloads_pass", False):
        return 0.85

    if not predicates.get("final_service_available", False):
        return 0.95

    if not predicates.get("integrity_provenance_pass", False):
        return 0.95

    return 1.0
