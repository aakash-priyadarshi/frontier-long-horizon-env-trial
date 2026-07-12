from __future__ import annotations

from pathlib import Path

from training_adapters.apex_compat import (
    format_apex_test_stdout,
    validate_apex_task_dir,
)
from training_adapters.protocol import ALLOWED_TOOLS
from training_adapters.rollout import ScriptedRecoveryPolicy, run_rollout
from training_adapters.session import ProtocolGateway


REPO = Path(__file__).resolve().parents[2]
TASK = REPO / "integrations" / "apex_swe" / "tasks" / "frontier-incident-smoke"


def test_static_apex_task_layout() -> None:
    problems = validate_apex_task_dir(TASK)
    assert problems == [], problems


def test_task_yaml_mentions_twelve_tools() -> None:
    text = (TASK / "task.yaml").read_text(encoding="utf-8")
    for tool in ALLOWED_TOOLS:
        assert tool in text


def test_protocol_session_blocks_unknown_tool() -> None:
    with ProtocolGateway(0) as session:
        response = session.call("_store", {})
        assert response.ok is False
        assert response.error_code == "unknown_tool"


def test_scripted_rollout_closes_incident() -> None:
    result = run_rollout(profile=0, policy=ScriptedRecoveryPolicy(), max_steps=16)
    assert result.success is True
    status = result.final_observation["status"]
    assert status["incident"] == "closed"
    assert status["public_canary"] == "pass"
    assert "profile" not in status


def test_apex_marker_format() -> None:
    text = format_apex_test_stdout(True)
    assert "results starts here" in text
    assert "PASSED" in text
