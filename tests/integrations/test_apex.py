from __future__ import annotations

from integrations.apex_swe.adapter import run_apex_trial
from training_ground.policies import IDEMPOTENT_FLOW, SETTINGS


def test_apex_trial_valid_repair() -> None:
    policy = [
        {"tool": "telemetry.logs", "arguments": {"alias": "Q-41"}},
        {"tool": "state.inspect", "arguments": {"source": "public", "selector": {"stream": "settlement"}, "view": "progress"}},
        {"tool": "recovery.pause", "arguments": {}},
        {"tool": "recovery.restore", "arguments": {"snapshot_id": "S0"}},
        {"tool": "workspace.read", "arguments": {"path": "service/flow.py"}},
        {"tool": "workspace.read", "arguments": {"path": "service/settings.toml"}},
        {"tool": "workspace.edit", "arguments": {"path": "service/flow.py", "content": IDEMPOTENT_FLOW}},
        {"tool": "workspace.edit", "arguments": {"path": "service/settings.toml", "content": SETTINGS}},
        {"tool": "release.deploy", "arguments": {}},
        {"tool": "runtime.run", "arguments": {"workload_id": "P1"}},
        {"tool": "runtime.run", "arguments": {"workload_id": "P2"}},
        {"tool": "runtime.run", "arguments": {"workload_id": "P3"}},
        {"tool": "recovery.resume", "arguments": {}},
        {"tool": "release.status", "arguments": {}},
    ]
    result = run_apex_trial(
        task_id="apex-eval-001",
        policy=policy,
        split="eval",
        seed=0,
        profile=0,
        max_steps=64,
    )
    assert result["success"] is True
    assert result["metadata"]["score"] == 1.0
