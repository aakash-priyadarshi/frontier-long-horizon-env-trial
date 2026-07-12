from __future__ import annotations

import pytest

from training_ground import load_environment

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

SETTINGS_OK = """[service]
intake_enabled = true
settlement_enabled = true
attempt_budget = 3
transient_behavior = "retry"
"""

SETTINGS_LOW = """[service]
intake_enabled = true
settlement_enabled = true
attempt_budget = 1
transient_behavior = "retry"
"""


def _run_policy(policy, profile: int = 0):
    env = load_environment("eval", 0, options={"profile": profile, "max_steps": 64})
    env.reset()
    terminated = False
    truncated = False
    for action in policy:
        if terminated or truncated:
            break
        _, _, terminated, truncated, _ = env.step(action)
    grade = env.grade()
    env.close()
    return grade


def _valid_policy(flow: str, settings: str) -> list[dict]:
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


def test_valid_repair_scores_one() -> None:
    grade = _run_policy(_valid_policy(IDEMPOTENT_FLOW, SETTINGS_OK), profile=0)
    assert grade["score"] == 1.0
    assert grade["verdict"] == "pass"


def test_low_attempt_budget_fails_public() -> None:
    grade = _run_policy(_valid_policy(IDEMPOTENT_FLOW, SETTINGS_LOW), profile=0)
    assert grade["score"] < 0.6
    assert not grade["predicates"]["public_workloads_pass"]


DEFAULT_FLOW = '''"""Public stage composition for intake and settlement delivery."""
from __future__ import annotations

def s1(command: dict[str, str], store: object) -> dict[str, str]:
    return store.prepare(command)

def s2(command: dict[str, str], store: object) -> str:
    return store.append(command)

def s3(command: dict[str, str], event_id: str, store: object) -> None:
    store.register(command, event_id)

def s4(event_id: str, store: object) -> dict[str, str]:
    return store.load(event_id)

def s5(event: dict[str, str], store: object) -> str:
    return store.settle(event)

def s6(sequence: int, store: object) -> None:
    store.advance(sequence)
'''


def test_unedited_flow_fails_member_hidden() -> None:
    # Default flow.py is not idempotent; it should fail member-specific hidden workloads.
    grade = _run_policy(_valid_policy(DEFAULT_FLOW, SETTINGS_OK), profile=0)
    assert grade["score"] < 1.0


def test_cheat_tool_rejected_by_action_surface() -> None:
    env = load_environment("eval", 0, options={"max_steps": 10})
    env.reset()
    obs, reward, terminated, truncated, info = env.step(
        {"tool": "system.leak_probe", "arguments": {}}
    )
    env.close()
    assert "error" in obs
    assert obs["incident"] == "open"
