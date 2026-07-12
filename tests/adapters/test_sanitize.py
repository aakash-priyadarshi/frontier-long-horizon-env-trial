from __future__ import annotations

from training_adapters.sanitize import sanitize_error_message, sanitize_payload


def test_sanitize_strips_privileged_keys() -> None:
    payload = {
        "tick": 1,
        "profile": 0,
        "authority_scope": "secret",
        "handle_salt": "abc",
        "nested": {"sqlite_path": "/tmp/x", "ok": True},
        "roots": {"service_state": "deadbeef"},
    }
    cleaned = sanitize_payload(payload)
    assert "profile" not in cleaned
    assert "authority_scope" not in cleaned
    assert "handle_salt" not in cleaned
    assert "sqlite_path" not in cleaned["nested"]
    assert cleaned["nested"]["ok"] is True
    assert cleaned["roots"]["service_state"] == "deadbeef"


def test_sanitize_redacts_scope_tokens() -> None:
    assert sanitize_payload("scope-71e5a88c9bdc47f0") == "<redacted>"
    assert sanitize_error_message("boom scope-71e5a88c9bdc47f0") == "tool execution failed"
