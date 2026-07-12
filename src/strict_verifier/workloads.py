"""Workload registry and expected outcome metadata."""

from __future__ import annotations

# Public workloads are part of the release.status contract.
PUBLIC_WORKLOADS: tuple[str, ...] = ("P1", "P2", "P3")

# Shared hidden workloads are neutral with respect to the paired member.
SHARED_HIDDEN_WORKLOADS: tuple[str, ...] = ("H-TRANS", "H-S1", "H-S2", "H-S3")

# Member-specific hidden workloads. The verifier selects the correct pair
# based on the privileged fixture profile (0 -> A, 1 -> B).
MEMBER_A_WORKLOADS: tuple[tuple[str, str | None], ...] = (
    ("H-A1", "s5.exit"),
    ("H-A2", None),
    ("H-A3", None),
    ("H-A4", "s5.exit"),
)

MEMBER_B_WORKLOADS: tuple[tuple[str, str | None], ...] = (
    ("H-B1", "s2.exit"),
    ("H-B2", None),
    ("H-B3", None),
    ("H-B4", None),
)


def member_workloads(profile: int) -> tuple[tuple[str, str | None], ...]:
    if profile == 0:
        return MEMBER_A_WORKLOADS
    if profile == 1:
        return MEMBER_B_WORKLOADS
    raise ValueError(f"unsupported profile {profile}")
