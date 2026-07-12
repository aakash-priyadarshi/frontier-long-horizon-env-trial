"""Focused regressions for final integrated audit falsifications."""

from __future__ import annotations

import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from strict_verifier import Verifier  # noqa: E402
from strict_verifier.predicates import PREDICATE_CATEGORIES  # noqa: E402
from strict_verifier.reward import calculate_reward  # noqa: E402
from training_ground import load_environment  # noqa: E402
from training_ground.authority import (  # noqa: E402
    authority_for_profile,
    profile_binding,
    transcript_key_for_authority,
)
from training_ground.policies import (  # noqa: E402
    BROAD_EVENT_DEDUP_FLOW,
    INTENT_OUTBOX_FLOW,
    LOGICAL_IDENTITY_FLOW,
    valid_repair_policy,
)
from verify_common import validate_source_commit  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _run_policy(flow: str, profile: int = 0) -> dict[str, Any]:
    env = load_environment("eval", 0, options={"profile": profile, "max_steps": 64})
    env.reset()
    try:
        for action in valid_repair_policy(flow=flow):
            _, _, terminated, truncated, _ = env.step(action)
            if terminated or truncated:
                break
        return env.grade()
    finally:
        env.close()


def _successful_env_with_transcript() -> tuple[Any, list[dict[str, Any]]]:
    env = load_environment("eval", 0, options={"profile": 0, "max_steps": 64})
    env.reset()
    for action in valid_repair_policy(flow=LOGICAL_IDENTITY_FLOW):
        _, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            break
    assert env.grade()["score"] == 1.0
    return env, env.transcript()


def _grade_with_transcript(env: Any, transcript: list[dict[str, Any]], session_id: str) -> dict[str, Any]:
    auth = authority_for_profile(0)
    return Verifier(
        env._client.session_dir,
        env._client.fixture_dir,
        0,
        auth,
        env.manifest,
        transcript,
        profile_binding=profile_binding(0, auth),
        transcript_key=transcript_key_for_authority(auth),
        session_id=session_id,
    ).grade()


def test_source_commit_binding_requires_full_commit_sha(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / "file.txt").write_text("source\n", encoding="utf-8")
    _git(repo, "add", "file.txt")
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "source")
    full_sha = _git(repo, "rev-parse", "HEAD")

    assert validate_source_commit(repo, full_sha, ()) == full_sha
    with pytest.raises(ValueError, match="malformed source commit"):
        validate_source_commit(repo, full_sha[:12], ())


def test_transcript_forgery_rejected() -> None:
    env, _ = _successful_env_with_transcript()
    fake = [
        {
            "kind": "meta",
            "session_id": "forged",
            "instance_id": env.manifest.instance_id,
            "split": "eval",
            "seed": 0,
            "profile_binding": "forged",
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
    ]
    try:
        grade = _grade_with_transcript(env, fake, "forged")
    finally:
        env.close()
    assert grade["score"] == 0.0
    assert grade["predicates"]["transcript_integrity"] is False
    assert grade["predicates"]["protocol_abuse"] is True


def test_mutated_authenticated_transcript_cannot_score_one() -> None:
    env, transcript = _successful_env_with_transcript()
    forged = deepcopy(transcript)
    for entry in forged:
        if entry.get("kind") == "step":
            entry["tool"] = "telemetry.logs"
            break
    try:
        grade = _grade_with_transcript(env, forged, transcript[0]["session_id"])
    finally:
        env.close()
    assert grade["score"] == 0.0
    assert grade["predicates"]["transcript_integrity"] is False


def test_both_gold_families_score_one_on_both_profiles() -> None:
    for flow in (LOGICAL_IDENTITY_FLOW, INTENT_OUTBOX_FLOW):
        for profile in (0, 1):
            grade = _run_policy(flow, profile)
            assert grade["score"] == 1.0, (profile, grade)


def test_broad_effect_exists_fails_h_a3() -> None:
    grade = _run_policy(BROAD_EVENT_DEDUP_FLOW, profile=0)
    assert grade["score"] < 1.0
    assert grade["workload_results"]["H-A3"]["outcome"] == "fail"
    assert grade["predicates"]["member_hidden_workloads_pass"] is False


def test_pair_blind_policy_horizon_includes_required_diagnostics() -> None:
    policy = valid_repair_policy()
    tools = [action["tool"] for action in policy]
    assert len(policy) >= 15
    assert "telemetry.logs" in tools
    assert "state.inspect" in tools
    assert any(
        action["tool"] == "runtime.run" and "cutpoint" in action.get("arguments", {})
        for action in policy
    )
    assert "telemetry.trace" in tools
    assert "release.rollback" in tools


def test_gym_check_env_passes() -> None:
    pytest.importorskip("gymnasium")
    from gymnasium.utils.env_checker import check_env
    from training_adapters.gym_env import IncidentGymEnv

    env = IncidentGymEnv(profile=0, max_steps=8)
    try:
        check_env(env, skip_render_check=True)
    finally:
        env.close()


def test_reward_requires_transcript_integrity_and_bounded_resources() -> None:
    predicates = {name: True for name in PREDICATE_CATEGORIES}
    predicates["protocol_abuse"] = False
    predicates["state_tampering"] = False
    assert calculate_reward(predicates, {}) == 1.0

    missing_transcript = {**predicates, "transcript_integrity": False}
    assert calculate_reward(missing_transcript, {}) == 0.0

    unbounded = {**predicates, "bounded_resources": False}
    assert calculate_reward(unbounded, {}) == 0.0
