"""Sanitize adapter observations and results before they leave the builder boundary."""

from __future__ import annotations

import re
from typing import Any

_FORBIDDEN_KEY_FRAGMENTS = (
    "auth_tag",
    "authority",
    "key_hex",
    "handle_salt",
    "fixture_profile",
    "member_selector",
    "profile",
    "sqlite",
    "traceback",
    "stack",
    "secret",
    "password",
    "token_hex",
    "recovery_authority",
    "trace_authority",
)

_FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"scope-[0-9a-f]{16}", re.I),
    re.compile(r"service\.sqlite3", re.I),
    re.compile(r"handle_salt", re.I),
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r"[A-Za-z]:\\\\.*\\\\\.git", re.I),
)

_MAX_STRING = 50_000
_MAX_LIST = 500
_MAX_DEPTH = 8


def _key_forbidden(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _FORBIDDEN_KEY_FRAGMENTS)


def _value_forbidden(value: str) -> bool:
    return any(pattern.search(value) for pattern in _FORBIDDEN_VALUE_PATTERNS)


def sanitize_payload(value: Any, *, depth: int = 0) -> Any:
    """Return a deep-copied payload with privileged fields and tokens removed."""
    if depth > _MAX_DEPTH:
        return "<truncated-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > _MAX_STRING:
            return value[:_MAX_STRING] + "<truncated>"
        if _value_forbidden(value):
            return "<redacted>"
        return value
    if isinstance(value, bytes):
        return "<bytes>"
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if _key_forbidden(key_str):
                continue
            cleaned[key_str] = sanitize_payload(item, depth=depth + 1)
        return cleaned
    if isinstance(value, (list, tuple)):
        items = [sanitize_payload(item, depth=depth + 1) for item in list(value)[:_MAX_LIST]]
        if len(value) > _MAX_LIST:
            items.append("<truncated-list>")
        return items
    return str(value)[:_MAX_STRING]


def sanitize_adapter_result(result: Any) -> Any:
    """Sanitize a successful tool result for training transcripts."""
    return sanitize_payload(result)


def sanitize_error_message(message: str) -> str:
    """Keep error messages neutral and free of privileged tokens."""
    text = str(message)
    if _value_forbidden(text):
        return "tool execution failed"
    if len(text) > 500:
        return text[:500]
    return text
