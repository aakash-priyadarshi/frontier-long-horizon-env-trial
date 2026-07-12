from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

import pytest

from strict_verifier import Verifier
from training_ground.authority import authority_for_profile
from training_ground.manifests import build_manifest

from tests.final_audit.conftest import execute_policy


def _grade_with(env: Any, transcript: list[dict[str, Any]]) -> dict[str, Any]:
    assert env._client is not None
    return Verifier(
        session_dir=env._client.session_dir,
        fixture_dir=env._client.fixture_dir,
        profile=env.manifest.profile,
        authority=authority_for_profile(env.manifest.profile),
        manifest=env.manifest,
        transcript=transcript,
    ).grade()


def _steps(transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in transcript if entry.get("kind") == "step"]


def _assert_rejected(env: Any, transcript: list[dict[str, Any]]) -> None:
    grade = _grade_with(env, transcript)
    assert grade["score"] < 1.0, grade
    assert grade["predicates"].get("transcript_integrity") is False


def test_fabricated_diagnostic_tool_names_cannot_score_one(valid_episode: Any) -> None:
    original = valid_episode.transcript()
    steps = _steps(original)
    fabricated = [
        copy.deepcopy(original[0]),
        {**copy.deepcopy(steps[0]), "sequence": 1, "tool": "telemetry.logs"},
        {**copy.deepcopy(steps[1]), "sequence": 2, "tool": "state.inspect"},
    ]
    _assert_rejected(valid_episode, fabricated)


def test_reordered_transcript_is_rejected(valid_episode: Any) -> None:
    transcript = copy.deepcopy(valid_episode.transcript())
    header, steps = transcript[0], transcript[1:]
    _assert_rejected(valid_episode, [header, *reversed(steps)])


def test_deleted_step_is_rejected(valid_episode: Any) -> None:
    transcript = copy.deepcopy(valid_episode.transcript())
    del transcript[4]
    _assert_rejected(valid_episode, transcript)


def test_duplicated_step_is_rejected(valid_episode: Any) -> None:
    transcript = copy.deepcopy(valid_episode.transcript())
    transcript.insert(4, copy.deepcopy(transcript[3]))
    _assert_rejected(valid_episode, transcript)


def test_altered_tool_is_rejected(valid_episode: Any) -> None:
    transcript = copy.deepcopy(valid_episode.transcript())
    step = _steps(transcript)[0]
    step["tool"] = "telemetry.trace"
    _assert_rejected(valid_episode, transcript)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("canonical_arguments_digest", "0" * 32),
        ("bounded_public_result_digest", "1" * 32),
        ("request_bytes", 1),
        ("response_bytes", 1),
    ),
    ids=("argument-digest", "result-digest", "request-bytes", "response-bytes"),
)
def test_altered_step_evidence_is_rejected(
    valid_episode: Any, field: str, replacement: str | int
) -> None:
    transcript = copy.deepcopy(valid_episode.transcript())
    _steps(transcript)[0][field] = replacement
    _assert_rejected(valid_episode, transcript)


def test_cross_session_transcript_is_rejected(valid_episode: Any) -> None:
    transcript = copy.deepcopy(valid_episode.transcript())
    transcript[0]["session_id"] = "session_from_another_episode"
    _assert_rejected(valid_episode, transcript)


def test_cross_seed_transcript_is_rejected(valid_episode: Any) -> None:
    transcript = copy.deepcopy(valid_episode.transcript())
    other = build_manifest("eval", 1)
    transcript[0]["seed"] = other.seed
    transcript[0]["instance_id"] = other.instance_id
    _assert_rejected(valid_episode, transcript)


def test_cross_member_transcript_is_rejected(valid_episode: Any, tmp_path: Path) -> None:
    other = execute_policy(profile=1, seed=0, work_dir=tmp_path / "other-member")
    try:
        assert other.grade()["score"] == 1.0
        _assert_rejected(valid_episode, other.transcript())
    finally:
        other.close()
