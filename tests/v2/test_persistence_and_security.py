from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from evaluation_service.candidate_artifacts import (
    build_candidate_diff,
    candidate_artifact_digest,
)
from evaluation_service.persistence import (
    ActiveRunDeletionError,
    EvaluationStore,
    ImmutableRecordError,
    canonical_json,
    record_digest,
)
from evaluation_service.sanitization import (
    contains_forbidden_public_data,
    public_verifier_result,
    sanitize_arguments,
    sanitize_public,
)
from evaluation_service.schemas import EvaluationCreate


def request() -> EvaluationCreate:
    return EvaluationCreate(provider="scripted", model="scripted-valid")


def make_store(tmp_path: Path) -> EvaluationStore:
    return EvaluationStore(tmp_path / "evaluations.sqlite3", event_replay_limit=100)


def seed_run(store: EvaluationStore) -> str:
    store.create_batch("batch", request(), environment_commit="a" * 40, application_commit="b" * 40)
    store.create_run("run", "batch", split="eval", seed=0, attempt=1, provider="scripted", model="scripted-valid", payload={"authoritative_reward": None})
    return "run"


def test_database_migration_version(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    assert store.schema_version == 1
    store.close()
    reopened = make_store(tmp_path)
    assert reopened.schema_version == 1
    reopened.close()


def test_canonical_digest_is_key_order_independent() -> None:
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert record_digest({"a": 1, "b": 2}) == record_digest({"b": 2, "a": 1})
    assert record_digest({"a": 1, "exported_at": "later"}) == record_digest({"a": 1})


def test_terminal_run_is_immutable(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    seed_run(store)
    digest = store.finalize_run("run", "completed", {"authoritative_reward": 1.0, "authoritative_verdict": "pass"})
    with pytest.raises(ImmutableRecordError):
        store.update_run_progress("run", "running", {"authoritative_reward": 0})
    with pytest.raises(ImmutableRecordError):
        store.finalize_run("run", "completed", {"authoritative_reward": 0})
    assert store.get_run("run")["record_digest"] == digest  # type: ignore[index]
    store.close()


def test_event_ordering_replay_and_cap(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    for index in range(110):
        store.append_event("run", "run", "step", {"index": index})
    events = store.events_after("run", "run", 0, limit=200)
    assert len(events) == 100
    assert [event.id for event in events] == sorted(event.id for event in events)
    replay = store.events_after("run", "run", events[-2].id)
    assert len(replay) == 1
    store.close()


def test_active_records_marked_interrupted_on_restart(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    seed_run(store)
    store.update_run_progress("run", "running", {})
    assert store.mark_active_interrupted() == 1
    assert store.get_run("run")["status"] == "interrupted"  # type: ignore[index]
    with pytest.raises(ImmutableRecordError):
        store.update_run_progress("run", "running", {})
    store.close()


def test_sanitization_removes_secrets_handles_and_private_paths() -> None:
    value = {
        "api_key": "secret", "handle": "capability", "ok": 1,
        "path": r"C:\repo\strict_verifier\workloads.py",
        "nested": {"authorization": "Bearer x"},
    }
    cleaned = sanitize_public(value)
    assert cleaned == {"ok": 1, "path": "<redacted>", "nested": {}}
    assert contains_forbidden_public_data(cleaned) is False


def test_workspace_edit_content_is_summarized() -> None:
    cleaned = sanitize_arguments("workspace.edit", {"path": "service/flow.py", "content": "print('safe')"})
    assert cleaned["path"] == "service/flow.py"
    assert cleaned["content"]["summary"] == "13 bytes"
    assert len(cleaned["content"]["sha256"]) == 64


def test_public_verifier_result_drops_hidden_workloads() -> None:
    grade = {
        "score": 0.85, "verdict": "partial",
        "predicates": {"protocol_abuse": False, "state_tampering": False, "member_hidden_workloads_pass": False},
        "workload_results": {"P1": {"outcome": "pass"}, "H-private": {"outcome": "fail"}},
    }
    public = public_verifier_result(grade)
    assert public["authoritative_reward"] == 0.85
    assert public["failed_predicates"] == ["member_hidden_workloads_pass"]
    assert set(public["public_workload_outcomes"]) == {"P1"}
    assert "H-private" not in json.dumps(public)


def test_secret_value_never_written_to_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-super-secret-test-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    store = make_store(tmp_path)
    seed_run(store)
    store.finalize_run("run", "completed", {"authoritative_reward": 1.0})
    store.close()
    assert secret.encode() not in (tmp_path / "evaluations.sqlite3").read_bytes()


def test_candidate_diff_is_bounded_sanitized_and_digest_bound(tmp_path: Path) -> None:
    initial = tmp_path / "initial"
    candidate = tmp_path / "candidate"
    (initial / "service").mkdir(parents=True)
    (candidate / "service").mkdir(parents=True)
    (initial / "service" / "flow.py").write_text("MODE = 'old'\n", encoding="utf-8")
    secret = "sk-ant-secret-value-that-must-not-survive"
    (candidate / "service" / "flow.py").write_text(
        "MODE = 'new'\n"
        f"API_KEY = '{secret}'\n"
        "WORKLOAD = 'H-private-case'\n",
        encoding="utf-8",
    )

    artifact = build_candidate_diff(initial, candidate)

    assert artifact is not None
    assert artifact["changed_paths"] == ["service/flow.py"]
    assert artifact["artifact_digest"] == candidate_artifact_digest(artifact)
    serialized = json.dumps(artifact)
    assert "MODE = 'new'" in serialized
    assert secret not in serialized
    assert "H-private-case" not in serialized
    assert "<redacted-sensitive-line>" in serialized
    assert "<redacted-hidden-workload>" in serialized


def test_candidate_diff_truncates_oversized_source_lines(tmp_path: Path) -> None:
    initial = tmp_path / "initial"
    candidate = tmp_path / "candidate"
    (initial / "service").mkdir(parents=True)
    (candidate / "service").mkdir(parents=True)
    (initial / "service" / "flow.py").write_text("VALUE = 'old'\n", encoding="utf-8")
    (candidate / "service" / "flow.py").write_text(
        "VALUE = '" + ("x" * (600 * 1024)) + "'\n",
        encoding="utf-8",
    )

    artifact = build_candidate_diff(initial, candidate)

    assert artifact is not None
    assert artifact["truncated"] is True
    assert artifact["files"][0]["truncated"] is True
    assert "<truncated-line>" in artifact["files"][0]["diff"]
    assert len(json.dumps(artifact).encode("utf-8")) < 520 * 1024


def test_candidate_diff_storage_cleanup_preserves_immutable_record(tmp_path: Path) -> None:
    initial = tmp_path / "initial"
    candidate = tmp_path / "candidate"
    (initial / "service").mkdir(parents=True)
    (candidate / "service").mkdir(parents=True)
    (initial / "service" / "flow.py").write_text("MODE = 'old'\n", encoding="utf-8")
    (candidate / "service" / "flow.py").write_text("MODE = 'new'\n", encoding="utf-8")
    artifact = build_candidate_diff(initial, candidate)
    assert artifact is not None

    store = make_store(tmp_path)
    seed_run(store)
    digest = store.finalize_run(
        "run",
        "completed",
        {"authoritative_reward": 0.85},
        candidate_artifact=artifact,
    )
    retained, storage = store.candidate_artifact("run")
    assert retained == artifact
    assert storage["state"] == "available"
    assert store.get_run("run")["record_digest"] == digest  # type: ignore[index]
    deleted = store.delete_candidate_artifact("run")
    assert deleted["deleted"] is True
    assert deleted["reclaimed_bytes"] > 0
    assert store.candidate_artifact("run")[1]["state"] == "deleted"
    assert store.get_run("run")["record_digest"] == digest  # type: ignore[index]
    store.close()


def test_episode_deletion_removes_run_events_artifacts_and_empty_batch(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    seed_run(store)
    store.append_event("run", "run", "tool_completed", {"run_id": "run"})
    store.append_event("batch", "batch", "tool_completed", {"run_id": "run"})
    store.finalize_run("run", "completed", {"authoritative_reward": 1.0})
    run_directory = store.runs_dir / "run"
    assert run_directory.is_dir()

    result = store.delete_run("run")

    assert result["deleted"] is True
    assert store.get_run("run") is None
    assert store.get_batch("batch") is None
    assert not run_directory.exists()
    assert store.events_after("run", "run") == []
    store.close()


def test_active_episode_cannot_be_deleted(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    seed_run(store)
    store.update_run_progress("run", "running", {})
    with pytest.raises(ActiveRunDeletionError):
        store.delete_run("run")
    assert store.get_run("run") is not None
    store.close()


def test_no_raw_score_column_can_be_updated_by_ui(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    columns = [row[1] for row in store._connection.execute("PRAGMA table_info(runs)").fetchall()]
    assert "score" not in columns
    assert "reward" not in columns
    store.close()
