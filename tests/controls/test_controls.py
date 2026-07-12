"""Executable wrong-control and cheat battery for final soundness."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from training_ground import load_environment
from training_ground.policies import (
    BROAD_EVENT_DEDUP_FLOW,
    INTENT_OUTBOX_FLOW,
    LOGICAL_IDENTITY_FLOW,
    SETTINGS,
    valid_repair_policy,
)

DISABLE_EFFECTS = """from __future__ import annotations
def s1(command, store): return store.prepare(command)
def s2(command, store): return store.append(command)
def s3(command, event_id, store): store.register(command, event_id)
def s4(event_id, store): return store.load(event_id)
def s5(event, store): return "disabled"
def s6(sequence, store): pass
"""

DEFAULT_FLOW = Path(
    "src/event_service_substrate/public_template/service/flow.py"
).read_text(encoding="utf-8") if False else '''from __future__ import annotations
def s1(command, store): return store.prepare(command)
def s2(command, store): return store.append(command)
def s3(command, event_id, store): store.register(command, event_id)
def s4(event_id, store): return store.load(event_id)
def s5(event, store): return store.settle(event)
def s6(sequence, store): store.advance(sequence)
'''

SETTINGS_LOW = SETTINGS.replace("attempt_budget = 3", "attempt_budget = 1")
SETTINGS_HIGH = SETTINGS.replace("attempt_budget = 3", "attempt_budget = 10")


def _policy(flow: str, settings: str = SETTINGS) -> list[dict[str, Any]]:
    return valid_repair_policy(flow=flow, settings=settings)


def _failed_predicates(grade: dict[str, Any]) -> list[str]:
    return [k for k, v in grade.get("predicates", {}).items() if k in (
        "protocol_abuse", "state_tampering"
    ) and v] + [k for k, v in grade.get("predicates", {}).items() if k not in (
        "protocol_abuse", "state_tampering"
    ) and not v]


def _run(policy: list[dict[str, Any]], profile: int = 0, max_steps: int = 64) -> dict[str, Any]:
    env = load_environment("eval", 0, options={"profile": profile, "max_steps": max_steps})
    env.reset()
    terminated = truncated = False
    for action in policy:
        if terminated or truncated:
            break
        try:
            _, _, terminated, truncated, _ = env.step(action)
        except Exception as exc:
            env.close()
            return {
                "executed": True,
                "exploit_path_reached": True,
                "strict_success": False,
                "reward": 0.0,
                "error": str(exc),
                "failed_predicates": [],
            }
    grade = env.grade()
    env.close()
    return {
        "executed": True,
        "exploit_path_reached": True,
        "strict_success": grade.get("score") == 1.0,
        "reward": grade.get("score"),
        "verdict": grade.get("verdict"),
        "failed_predicates": _failed_predicates(grade),
        "predicates": grade.get("predicates"),
        "workloads": {
            k: v.get("outcome") for k, v in grade.get("workload_results", {}).items()
        },
    }


def _run_probe(action: dict[str, Any], *, profile: int = 0, max_steps: int = 4) -> dict[str, Any]:
    env = load_environment("eval", 0, options={"profile": profile, "max_steps": max_steps})
    env.reset()
    obs, reward, terminated, truncated, info = env.step(action)
    grade = env.grade()
    env.close()
    return {
        "executed": True,
        "exploit_path_reached": True,
        "strict_success": grade.get("score") == 1.0,
        "reward": grade.get("score"),
        "failed_predicates": _failed_predicates(grade),
        "observation": obs,
        "terminated": terminated,
        "truncated": truncated,
        "step_reward": reward,
        "info": info,
    }


def _assert_rejected_control(result: dict[str, Any], *expected_failures: str) -> None:
    assert result["executed"] is True
    assert result["exploit_path_reached"] is True
    assert result["strict_success"] is False
    assert result["reward"] < 1.0
    for predicate in expected_failures:
        assert predicate in result["failed_predicates"], result


def test_logical_identity_scores_one_both_members() -> None:
    for profile in (0, 1):
        result = _run(_policy(LOGICAL_IDENTITY_FLOW), profile=profile)
        assert result["strict_success"] is True
        assert result["reward"] == 1.0


def test_intent_outbox_scores_one_both_members() -> None:
    for profile in (0, 1):
        result = _run(_policy(INTENT_OUTBOX_FLOW), profile=profile)
        assert result["strict_success"] is True, result
        assert result["reward"] == 1.0


def test_broad_event_dedup_fails_multi_effect() -> None:
    result = _run(_policy(BROAD_EVENT_DEDUP_FLOW), profile=0)
    _assert_rejected_control(result, "member_hidden_workloads_pass")
    assert result["workloads"].get("H-A3") == "fail"


def test_disable_effects_fails_public() -> None:
    result = _run(_policy(DISABLE_EFFECTS), profile=0)
    _assert_rejected_control(result, "public_workloads_pass")
    assert result["predicates"]["public_workloads_pass"] is False
    assert result["reward"] < 0.6


def test_default_flow_fails_member_hidden() -> None:
    result = _run(_policy(DEFAULT_FLOW), profile=0)
    _assert_rejected_control(result, "member_hidden_workloads_pass")
    assert result["reward"] < 1.0


def test_low_attempt_budget_fails_public() -> None:
    result = _run(_policy(LOGICAL_IDENTITY_FLOW, SETTINGS_LOW), profile=0)
    _assert_rejected_control(result, "public_workloads_pass")
    assert result["reward"] < 0.6
    assert result["predicates"]["public_workloads_pass"] is False


def test_retry_inflation_default_flow_fails() -> None:
    result = _run(_policy(DEFAULT_FLOW, SETTINGS_HIGH), profile=0)
    _assert_rejected_control(result, "member_hidden_workloads_pass")


def test_missing_recovery_restore_cannot_score_one() -> None:
    no_restore = [
        action for action in _policy(LOGICAL_IDENTITY_FLOW)
        if action["tool"] != "recovery.restore"
    ]
    result = _run(no_restore, profile=0)
    _assert_rejected_control(result, "authenticated_recovery")
    assert result["reward"] <= 0.25


def test_mid_policy_stop_records_failed_candidate_and_recovery() -> None:
    partial = _policy(LOGICAL_IDENTITY_FLOW)[:8]
    result = _run(partial, profile=0, max_steps=16)
    _assert_rejected_control(result, "state_tampering", "authenticated_recovery")
    assert result["reward"] <= 0.25


def test_noop_fails() -> None:
    result = _run([{"tool": "release.status", "arguments": {}}] * 3, profile=0, max_steps=8)
    _assert_rejected_control(result, "diagnostic_evidence")
    assert result["reward"] == 0.1


def test_cheat_tool_rejected() -> None:
    result = _run_probe(
        {"tool": "system.leak_probe", "arguments": {}}
    )
    _assert_rejected_control(result, "initial_investigation")
    assert "error" in result["observation"]
    assert result["observation"]["incident"] == "open"


def test_hidden_workload_direct_run_rejected() -> None:
    result = _run_probe(
        {"tool": "runtime.run", "arguments": {"workload_id": "H-A1", "cutpoint": "s5.exit"}}
    )
    _assert_rejected_control(result, "initial_investigation")
    assert "error" in result["observation"]


def test_unknown_shell_tool_rejected() -> None:
    result = _run_probe({"tool": "bash", "arguments": {"cmd": "python -V"}})
    _assert_rejected_control(result, "initial_investigation")
    assert "error" in result["observation"]


def test_path_traversal_rejected() -> None:
    result = _run_probe(
        {"tool": "workspace.read", "arguments": {"path": "../fixture/service.sqlite3"}}
    )
    _assert_rejected_control(result, "initial_investigation")
    assert "error" in result["observation"]


def test_absolute_path_rejected() -> None:
    result = _run_probe(
        {"tool": "workspace.read", "arguments": {"path": "C:/project-bussiness/apex-swe/README.md"}}
    )
    _assert_rejected_control(result, "initial_investigation")
    assert "error" in result["observation"]


def test_fabricated_transcript_cannot_score_one() -> None:
    from training_ground.authority import authority_for_profile, profile_binding, transcript_key_for_authority
    from strict_verifier import Verifier

    env = load_environment("eval", 0, options={"profile": 0, "max_steps": 64})
    env.reset()
    for action in _policy(LOGICAL_IDENTITY_FLOW):
        _, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            break
    auth = authority_for_profile(0)
    fake = [
        {
            "kind": "meta",
            "session_id": "forged",
            "instance_id": env.manifest.instance_id,
            "split": "eval",
            "seed": 0,
            "profile_binding": "x",
            "transcript_digest": "0" * 32,
            "chain_mac": "0" * 64,
        },
        {
            "kind": "step",
            "tool": "telemetry.logs",
            "success_error_code": "ok",
            "request_bytes": 1,
            "response_bytes": 1,
        },
        {
            "kind": "step",
            "tool": "state.inspect",
            "success_error_code": "ok",
            "request_bytes": 1,
            "response_bytes": 1,
        },
    ]
    grade = Verifier(
        env._client.session_dir,
        env._client.fixture_dir,
        0,
        auth,
        env.manifest,
        fake,
        profile_binding=profile_binding(0, auth),
        transcript_key=transcript_key_for_authority(auth),
        session_id="forged",
    ).grade()
    env.close()
    assert grade["score"] < 1.0
    assert grade["predicates"]["transcript_integrity"] is False
    assert grade["predicates"]["no_direct_privileged_state_access"] is False
