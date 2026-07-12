"""Pair-blind reference repair policies for reproducible verification."""

from __future__ import annotations

from typing import Any


IDEMPOTENT_FLOW = """from __future__ import annotations

def s1(command, store): return store.prepare(command)

def s2(command, store):
    existing = store.get_event_id(command.get("command_key"), command.get("occurrence_id"))
    return existing if existing else store.append(command)

def s3(command, event_id, store): store.register(command, event_id)

def s4(event_id, store): return store.load(event_id)

def s5(event, store):
    existing = store.effect_exists(event["event_id"])
    return existing if existing else store.settle(event)

def s6(sequence, store): store.advance(sequence)
"""

SETTINGS = """[service]
intake_enabled = true
settlement_enabled = true
attempt_budget = 3
transient_behavior = "retry"
"""


def valid_repair_policy(
    flow: str = IDEMPOTENT_FLOW,
    settings: str = SETTINGS,
) -> list[dict[str, Any]]:
    """Return a pair-blind valid repair action sequence."""
    return [
        {"tool": "telemetry.logs", "arguments": {"alias": "Q-41"}},
        {"tool": "state.inspect", "arguments": {"source": "public", "selector": {"stream": "settlement"}, "view": "progress"}},
        {"tool": "recovery.pause", "arguments": {}},
        {"tool": "recovery.restore", "arguments": {"snapshot_id": "S0"}},
        {"tool": "workspace.read", "arguments": {"path": "service/flow.py"}},
        {"tool": "workspace.read", "arguments": {"path": "service/settings.toml"}},
        {"tool": "workspace.edit", "arguments": {"path": "service/flow.py", "content": flow}},
        {"tool": "workspace.edit", "arguments": {"path": "service/settings.toml", "content": settings}},
        {"tool": "release.deploy", "arguments": {}},
        {"tool": "runtime.run", "arguments": {"workload_id": "P1"}},
        {"tool": "runtime.run", "arguments": {"workload_id": "P2"}},
        {"tool": "runtime.run", "arguments": {"workload_id": "P3"}},
        {"tool": "recovery.resume", "arguments": {}},
        {"tool": "release.status", "arguments": {}},
    ]
