"""Result formatting for the strict verifier."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Result:
    """Container for a strict verifier grading result."""

    score: float
    verdict: str
    predicates: dict[str, bool] = field(default_factory=dict)
    workload_results: dict[str, Any] = field(default_factory=dict)
    roots: dict[str, str | None] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "verdict": self.verdict,
            "predicates": self.predicates,
            "workload_results": self.workload_results,
            "roots": self.roots,
            "details": self.details,
        }
