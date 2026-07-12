"""Named predicate categories for the strict verifier."""

from __future__ import annotations

PREDICATE_CATEGORIES: tuple[str, ...] = (
    "valid_episode",
    "protocol_abuse",
    "state_tampering",
    "initial_investigation",
    "diagnostic_evidence",
    "authenticated_recovery",
    "candidate_prepared",
    "public_workloads_pass",
    "shared_hidden_workloads_pass",
    "member_hidden_workloads_pass",
    "final_service_available",
    "integrity_provenance_pass",
    "source_provenance",
    "candidate_provenance",
    "deployment_provenance",
    "transcript_integrity",
    "bounded_resources",
    "state_root_integrity",
    "state_tampering",
)


def default_predicates() -> dict[str, bool]:
    return {name: False for name in PREDICATE_CATEGORIES}
