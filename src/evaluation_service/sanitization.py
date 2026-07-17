"""Public-record sanitization and leak detection."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from training_adapters.sanitize import sanitize_payload


_SECRET_KEYS = re.compile(
    r"(api[_-]?key|authorization|cookie|password|secret|auth_tag|key_hex|handle|capability)",
    re.I,
)
_PRIVATE_PATH = re.compile(r"(?:[A-Za-z]:\\|/)(?:[^\s]+[/\\])+(?:service\.sqlite3|strict_verifier|workloads\.py)", re.I)
_HIDDEN_WORKLOAD = re.compile(r"\bH-[A-Za-z0-9_.-]+\b")


def sanitize_arguments(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    cleaned = sanitize_public(arguments)
    if tool == "workspace.edit" and isinstance(cleaned, dict) and isinstance(cleaned.get("content"), str):
        content = cleaned["content"]
        cleaned["content"] = {
            "summary": f"{len(content.encode('utf-8'))} bytes",
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }
    return cleaned


def sanitize_public(value: Any) -> Any:
    value = sanitize_payload(value)
    if isinstance(value, dict):
        return {
            str(key): sanitize_public(item)
            for key, item in value.items()
            if not _SECRET_KEYS.search(str(key))
        }
    if isinstance(value, list):
        return [sanitize_public(item) for item in value]
    if isinstance(value, str):
        if _PRIVATE_PATH.search(value) or _HIDDEN_WORKLOAD.search(value):
            return "<redacted>"
        return value
    return value


def public_verifier_result(grade: dict[str, Any]) -> dict[str, Any]:
    """Copy only public verifier outputs; never calculate or reinterpret reward."""
    predicates = grade.get("predicates") or {}
    expected_false = {"protocol_abuse", "state_tampering"}
    failed_predicates = sorted(
        str(name)
        for name, passed in predicates.items()
        if (name in expected_false and passed is True)
        or (name not in expected_false and passed is False)
    )
    public_workloads = {
        str(name): sanitize_public(result)
        for name, result in (grade.get("workload_results") or {}).items()
        if str(name) in {"P1", "P2", "P3"}
    }
    return {
        "authoritative_reward": grade.get("score"),
        "authoritative_verdict": grade.get("verdict"),
        "failed_predicates": failed_predicates,
        "public_workload_outcomes": public_workloads,
    }


def contains_forbidden_public_data(value: Any, *, secret_values: tuple[str, ...] = ()) -> bool:
    text = json.dumps(value, sort_keys=True, default=str)
    if _SECRET_KEYS.search(text) or _PRIVATE_PATH.search(text) or _HIDDEN_WORKLOAD.search(text):
        return True
    lowered = text.lower()
    if "member_selector" in lowered or "fixture_profile" in lowered or "auth_tag" in lowered:
        return True
    return any(secret and secret in text for secret in secret_values)
