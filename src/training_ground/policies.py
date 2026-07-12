"""Pair-blind reference repair policies for reproducible verification."""

from __future__ import annotations

from typing import Any


LOGICAL_IDENTITY_FLOW = """from __future__ import annotations

def s1(command, store): return store.prepare(command)

def s2(command, store):
    existing = store.get_event_id(command.get("command_key"), command.get("occurrence_id"))
    return existing if existing else store.append(command)

def s3(command, event_id, store): store.register(command, event_id)

def s4(event_id, store): return store.load(event_id)

def s5(event, store):
    key = event.get("logical_effect_key", "settlement")
    existing = store.effect_by_key(event["event_id"], key)
    return existing if existing else store.settle(event)

def s6(sequence, store): store.advance(sequence)
"""

INTENT_OUTBOX_FLOW = """from __future__ import annotations

def s1(command, store): return store.prepare(command)

def s2(command, store):
    existing = store.get_event_id(command.get("command_key"), command.get("occurrence_id"))
    return existing if existing else store.append(command)

def s3(command, event_id, store): store.register(command, event_id)

def s4(event_id, store): return store.load(event_id)

def s5(event, store):
    key = event.get("logical_effect_key", "settlement")
    existing = store.effect_by_key(event["event_id"], key)
    if existing:
        intent = store.get_intent(event["event_id"], key)
        if intent and intent.get("state") != "completed":
            store.intent_complete(intent["intent_id"], existing)
        return existing
    intent = store.get_intent(event["event_id"], key)
    if intent and intent.get("state") == "completed" and intent.get("effect_id"):
        return intent["effect_id"]
    if intent is None:
        intent_id = store.intent_create(
            event["event_id"], event["command_key"], event["occurrence_id"], key
        )
    else:
        intent_id = intent["intent_id"]
    effect_id = store.settle(event)
    store.intent_complete(intent_id, effect_id)
    return effect_id

def s6(sequence, store): store.advance(sequence)
"""

IDEMPOTENT_FLOW = LOGICAL_IDENTITY_FLOW

SETTINGS = """[service]
intake_enabled = true
settlement_enabled = true
attempt_budget = 3
transient_behavior = "retry"
"""

BROAD_EVENT_DEDUP_FLOW = """from __future__ import annotations

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


def valid_repair_policy(
    flow: str = LOGICAL_IDENTITY_FLOW,
    settings: str = SETTINGS,
) -> list[dict[str, Any]]:
    """Pair-blind valid repair with >=15 meaningful causal/info actions."""
    return [
        {"tool": "release.status", "arguments": {}},
        {"tool": "telemetry.logs", "arguments": {"alias": "Q-41"}},
        {"tool": "recovery.pause", "arguments": {}},
        {"tool": "runtime.run", "arguments": {"workload_id": "diag-s2", "cutpoint": "s2.exit"}},
        {"tool": "telemetry.trace", "arguments": {"handle": "__from_previous__"}},
        {"tool": "runtime.run", "arguments": {"workload_id": "diag-s5", "cutpoint": "s5.exit"}},
        {"tool": "telemetry.trace", "arguments": {"handle": "__from_previous__"}},
        {"tool": "state.inspect", "arguments": {"source": "public", "selector": {"stream": "settlement"}, "view": "progress"}},
        {"tool": "release.rollback", "arguments": {"revision": "r0"}},
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


def pair_informed_shortest_policy(
    flow: str = LOGICAL_IDENTITY_FLOW,
    settings: str = SETTINGS,
) -> list[dict[str, Any]]:
    return [
        {"tool": "recovery.pause", "arguments": {}},
        {"tool": "recovery.restore", "arguments": {"snapshot_id": "S0"}},
        {"tool": "workspace.edit", "arguments": {"path": "service/flow.py", "content": flow}},
        {"tool": "workspace.edit", "arguments": {"path": "service/settings.toml", "content": settings}},
        {"tool": "release.deploy", "arguments": {}},
        {"tool": "runtime.run", "arguments": {"workload_id": "P1"}},
        {"tool": "runtime.run", "arguments": {"workload_id": "P2"}},
        {"tool": "runtime.run", "arguments": {"workload_id": "P3"}},
        {"tool": "recovery.resume", "arguments": {}},
        {"tool": "release.status", "arguments": {}},
    ]


def intent_outbox_policy() -> list[dict[str, Any]]:
    return valid_repair_policy(flow=INTENT_OUTBOX_FLOW)
