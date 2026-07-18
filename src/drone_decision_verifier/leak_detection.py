"""Recursive post-serialization leak detection for public Talon artifacts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .hidden_scenarios import HIDDEN_FAMILY_KEYS
from .predicates import PREDICATE_NAMES


_PRIVILEGED_KEY_FRAGMENTS = frozenset(
    {
        "actual_object",
        "approval_nonce",
        "behavioural_signature",
        "correct_action",
        "expected_action",
        "expected_plan",
        "expert_action",
        "family_id",
        "final_disposition",
        "future_transition",
        "generator_partition",
        "hidden",
        "instance_digest",
        "paired_member",
        "predicate",
        "privileged",
        "required_evidence",
        "safety_cost",
        "scenario_family",
        "scenario_instance",
        "seed_domain",
        "training_instance",
        "true_intent",
        "truth",
    }
)
_SECRET_KEY_FRAGMENTS = frozenset(
    {"api_key", "authorization", "capability_token", "credential", "password", "private_key", "reasoning", "secret", "token"}
)
_PAIR_ALIASES = frozenset({"paired_blind", "paired_member", "member_a", "member_b", "wrong_hidden"})
_PATH_PATTERN = re.compile(r"(?:[A-Za-z]:\\|/(?:home|Users|workspace|app|tmp)/)")
_BEARER_PATTERN = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_CREDENTIAL_PATTERN = re.compile(r"(?i)\b(?:sk|key|token|secret)[-_][A-Za-z0-9_-]{12,}")


def _normalise(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def find_public_leaks(value: Any) -> list[str]:
    """Return bounded paths for forbidden keys *or values* in a public artifact."""

    findings: list[str] = []
    family_values = {_normalise(item) for item in HIDDEN_FAMILY_KEYS}
    predicate_values = {_normalise(item) for item in PREDICATE_NAMES}

    def add(path: str, category: str) -> None:
        finding = f"{path}:{category}"
        if finding not in findings and len(findings) < 100:
            findings.append(finding)

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for raw_key, nested in item.items():
                key = _normalise(raw_key)
                if any(fragment in key for fragment in _PRIVILEGED_KEY_FRAGMENTS):
                    add(f"{path}.{raw_key}", "privileged_key")
                if any(fragment in key for fragment in _SECRET_KEY_FRAGMENTS):
                    add(f"{path}.{raw_key}", "sensitive_key")
                visit(nested, f"{path}.{raw_key}")
            return
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for index, nested in enumerate(item):
                visit(nested, f"{path}[{index}]")
            return
        if isinstance(item, str):
            normal = _normalise(item)
            if normal in family_values or any(
                normal in {f"scenario_{family}", f"scenario_family_{family}", f"hidden_{family}"}
                for family in family_values
            ):
                add(path, "hidden_family_value")
            if normal in predicate_values or any(
                normal in {f"predicate_{predicate}", f"failed_predicate_{predicate}"}
                for predicate in predicate_values
            ):
                add(path, "verifier_predicate_value")
            if normal in _PAIR_ALIASES or any(alias in normal for alias in _PAIR_ALIASES):
                add(path, "paired_identity_value")
            if _PATH_PATTERN.search(item):
                add(path, "private_path")
            if _BEARER_PATTERN.search(item) or _CREDENTIAL_PATTERN.search(item):
                add(path, "credential_value")

    visit(value, "$")
    return findings


def assert_public_safe(value: Any) -> None:
    findings = find_public_leaks(value)
    if findings:
        categories = sorted({item.rsplit(":", 1)[-1] for item in findings})
        raise ValueError("public Talon artifact failed sanitization: " + ", ".join(categories))
