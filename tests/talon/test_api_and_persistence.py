from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
import torch
from fastapi.testclient import TestClient

from drone_decision_verifier.leak_detection import find_public_leaks
from drone_training.checkpoints import load_checkpoint
from drone_training.datasets import load_dataset
from drone_training.orchestration import TalonOrchestrator
from drone_training.persistence import (
    TalonIdempotencyConflict,
    TalonImmutableRecordError,
    TalonStore,
)
from drone_training.schemas import DatasetCreate, EvaluationCreate, TrainingCreate
from evaluation_service.app import create_app
from evaluation_service.settings import Settings


def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "frontier",
        database_path=tmp_path / "frontier" / "evaluations.sqlite3",
        talon_data_dir=tmp_path / "talon",
        talon_database_path=tmp_path / "talon" / "talon.sqlite3",
    )


def _crash_worker() -> None:
    os._exit(17)


async def wait_for(orchestrator: TalonOrchestrator, record_id: str) -> dict[str, object]:
    await orchestrator.wait(record_id)
    record = orchestrator.store.get(record_id)
    assert record is not None
    return record


def poll(client: TestClient, path: str, timeout: float = 30) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(path)
        assert response.status_code == 200, response.text
        record = response.json()
        if record["status"] in {"completed", "failed", "cancelled", "interrupted", "timed_out"}:
            return record
        time.sleep(0.05)
    raise AssertionError("record did not reach a terminal status")


def test_lazy_talon_api_real_dataset_idempotency_and_sanitization(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path))
    headers = {"Origin": "http://localhost:3000", "Idempotency-Key": "dataset-request-0001"}
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        components = client.get("/api/health/components").json()
        assert components["frontier"]["status"] == "available"
        assert components["talon"]["status"] == "not_initialized"
        health = client.get("/api/drone/health").json()
        assert health["simulation_only"] is True
        assert health["decision_support_only"] is True
        assert health["physical_response_controls"] is False
        capabilities = client.get("/api/drone/scenarios").json()
        assert capabilities["total"] == 5
        assert find_public_leaks(capabilities) == []
        demo = client.post(
            "/api/drone/policy/approval-demo",
            json={"mode": "replay"},
            headers={"Origin": "http://localhost:3000"},
        ).json()
        assert demo["first_use"]["accepted"] is True
        assert demo["replay"]["reason_code"] == "approval_already_consumed"
        assert demo["gate_rejection"]["accepted"] is False
        assert demo["gate_rejection"]["external_effect"] is False
        assert find_public_leaks(demo) == []

        rejected = client.post(
            "/api/drone/datasets/generate",
            json={"seed_count": 1},
            headers={"Origin": "https://unapproved.example"},
        )
        assert rejected.status_code == 403
        created = client.post("/api/drone/datasets/generate", json={"seed_count": 1}, headers=headers)
        assert created.status_code == 202
        retried = client.post("/api/drone/datasets/generate", json={"seed_count": 1}, headers=headers)
        assert retried.json()["dataset_id"] == created.json()["dataset_id"]
        conflict = client.post("/api/drone/datasets/generate", json={"seed_count": 2}, headers=headers)
        assert conflict.status_code == 409

        dataset_id = created.json()["dataset_id"]
        record = poll(client, f"/api/drone/datasets/{dataset_id}")
        assert record["status"] == "completed"
        assert find_public_leaks(record) == []
        assert "trajectories" not in json.dumps(record)
        assert client.get(f"/api/drone/exports/{dataset_id}.json").status_code == 409


def test_talon_failure_isolated_from_frontier_and_retryable(tmp_path: Path) -> None:
    config = settings(tmp_path)
    assert config.talon_database_path is not None
    config.talon_database_path.parent.mkdir(parents=True)
    with sqlite3.connect(config.talon_database_path) as connection:
        connection.execute("CREATE TABLE talon_schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        connection.execute("INSERT INTO talon_schema_meta VALUES('schema_version','999')")
    app = create_app(config)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/api/providers").status_code == 200
        unavailable = client.get("/api/drone/health")
        assert unavailable.status_code == 503
        assert unavailable.json()["error"]["code"] == "talon_service_unavailable"
        assert client.get("/api/health/components").json()["talon"]["status"] == "unavailable"
        with sqlite3.connect(config.talon_database_path) as connection:
            connection.execute("UPDATE talon_schema_meta SET value='2' WHERE key='schema_version'")
        assert client.get("/api/drone/health").status_code == 200


@pytest.mark.parametrize("failure_mode", ["database_is_directory", "parent_is_file", "permission_error"])
def test_talon_path_and_permission_failures_do_not_block_frontier(
    tmp_path: Path,
    failure_mode: str,
) -> None:
    config = settings(tmp_path)
    assert config.talon_database_path is not None
    if failure_mode == "database_is_directory":
        config.talon_database_path.mkdir(parents=True)
    elif failure_mode == "parent_is_file":
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("blocked", encoding="utf-8")
        config = replace(
            config,
            talon_database_path=blocker / "talon.sqlite3",
            talon_data_dir=blocker,
        )
    app = create_app(config)
    connect_patch = (
        patch("drone_training.persistence.sqlite3.connect", side_effect=PermissionError("denied"))
        if failure_mode == "permission_error"
        else None
    )
    context = connect_patch if connect_patch is not None else nullcontext()
    with context, TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/api/providers").status_code == 200
        response = client.get("/api/drone/health")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "talon_service_unavailable"


@pytest.mark.asyncio
async def test_real_worker_training_cancellation_timeout_and_single_terminal_event(tmp_path: Path) -> None:
    store = TalonStore(tmp_path / "talon.sqlite3")
    orchestrator = TalonOrchestrator(store)
    dataset_id = orchestrator.create_dataset(DatasetCreate(seed_count=1), start_background=True)
    dataset = await wait_for(orchestrator, dataset_id)
    assert dataset["status"] == "completed"

    cancelled_id = orchestrator.create_training(
        TrainingCreate(dataset_id=dataset_id, architecture="gru", epochs=500, timeout_seconds=120),
        start_background=True,
    )
    await asyncio.sleep(0.2)
    assert orchestrator.cancel(cancelled_id) is True
    assert orchestrator.cancel(cancelled_id) is True
    cancelled = await wait_for(orchestrator, cancelled_id)
    assert cancelled["status"] == "cancelled"
    assert not (store.private_dir / cancelled_id / "checkpoint.pt").exists()
    assert [event.event_type for event in store.events_after("talon_training", cancelled_id)].count("terminal") == 1

    timed_id = orchestrator.create_training(
        TrainingCreate(dataset_id=dataset_id, architecture="gru", epochs=500, timeout_seconds=1),
        start_background=True,
    )
    timed = await wait_for(orchestrator, timed_id)
    assert timed["status"] == "timed_out"
    assert not (store.private_dir / timed_id / "checkpoint.pt").exists()
    assert not orchestrator._tasks and not orchestrator._jobs
    store.close()


@pytest.mark.asyncio
async def test_cancel_before_start_and_parent_restart_are_authoritative(tmp_path: Path) -> None:
    database = tmp_path / "talon.sqlite3"
    store = TalonStore(database)
    orchestrator = TalonOrchestrator(store)
    dataset_id = orchestrator.create_dataset(DatasetCreate(), start_background=False)
    assert orchestrator.cancel(dataset_id)
    await orchestrator._monitor(dataset_id)
    assert store.get(dataset_id)["status"] == "cancelled"  # type: ignore[index]

    active_id = orchestrator.create_dataset(DatasetCreate(seed_start=3), start_background=False)
    store.close()
    restarted = TalonStore(database)
    assert restarted.mark_active_interrupted() == 1
    assert restarted.get(active_id)["status"] == "interrupted"  # type: ignore[index]
    restarted.close()


@pytest.mark.asyncio
async def test_worker_crash_and_concurrent_cancellation_have_one_terminal_outcome(
    tmp_path: Path,
) -> None:
    store = TalonStore(tmp_path / "talon.sqlite3")
    orchestrator = TalonOrchestrator(store)
    crashed_id = orchestrator.create_dataset(DatasetCreate(), start_background=False)
    crashed_job = orchestrator._jobs[crashed_id]
    crashed_job.process = orchestrator._context.Process(target=_crash_worker)
    await orchestrator._monitor(crashed_id)
    crashed = store.get(crashed_id)
    assert crashed is not None
    assert crashed["status"] == "failed"
    assert crashed["error_category"] == "dataset_worker_crash"
    assert [event.event_type for event in store.events_after("talon_dataset", crashed_id)].count("terminal") == 1

    dataset_id = orchestrator.create_dataset(DatasetCreate(), start_background=True)
    await wait_for(orchestrator, dataset_id)
    training_id = orchestrator.create_training(
        TrainingCreate(
            dataset_id=dataset_id,
            architecture="gru",
            epochs=500,
            timeout_seconds=120,
        ),
        start_background=True,
    )
    await asyncio.sleep(0.2)
    outcomes = await asyncio.gather(
        *(asyncio.to_thread(orchestrator.cancel, training_id) for _ in range(8))
    )
    assert all(outcomes)
    cancelled = await wait_for(orchestrator, training_id)
    assert cancelled["status"] == "cancelled"
    assert [event.event_type for event in store.events_after("talon_training", training_id)].count("terminal") == 1
    assert orchestrator.cancel(training_id) is False
    store.close()


@pytest.mark.asyncio
async def test_completed_records_are_immutable_private_and_dependency_protected(tmp_path: Path) -> None:
    store = TalonStore(tmp_path / "talon.sqlite3")
    orchestrator = TalonOrchestrator(store)
    dataset_id = orchestrator.create_dataset(DatasetCreate(), start_background=True)
    await wait_for(orchestrator, dataset_id)
    training_id = orchestrator.create_training(
        TrainingCreate(dataset_id=dataset_id, architecture="gru", epochs=1, batch_size=32, timeout_seconds=60),
        start_background=True,
    )
    training = await wait_for(orchestrator, training_id)
    assert training["status"] == "completed", training
    assert training["checkpoint_digest"].startswith("sha256:")
    assert 0.0 <= training["training_metrics"]["validation_action_accuracy"] <= 1.0
    assert (store.private_dir / training_id / "checkpoint.pt").exists()
    assert not (store.records_dir / training_id / "checkpoint.pt").exists()
    verified_dataset = load_dataset(store.private_dir / dataset_id / "dataset.json")
    private_manifest = json.loads(
        (store.private_dir / training_id / "manifest.json").read_text(encoding="utf-8")
    )
    assert private_manifest["dataset_digest_verification"] == "recomputed"
    assert private_manifest["dataset_digest"] == verified_dataset.manifest.dataset_digest
    with pytest.raises(TalonImmutableRecordError):
        store.update(training_id, "running", {"progress": {}})
    with pytest.raises(TalonImmutableRecordError, match="referenced"):
        store.delete_terminal(dataset_id)
    assert store.delete_terminal(training_id)
    assert store.delete_terminal(dataset_id)
    store.close()


@pytest.mark.asyncio
async def test_worker_rejects_tampered_dataset_before_checkpoint_creation(tmp_path: Path) -> None:
    store = TalonStore(tmp_path / "talon.sqlite3")
    orchestrator = TalonOrchestrator(store)
    dataset_id = orchestrator.create_dataset(DatasetCreate(), start_background=True)
    assert (await wait_for(orchestrator, dataset_id))["status"] == "completed"
    path = store.private_dir / dataset_id / "dataset.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["manifest"]["normalization"]["mean"][0] += 0.25
    path.write_text(json.dumps(payload), encoding="utf-8")

    training_id = orchestrator.create_training(
        TrainingCreate(dataset_id=dataset_id, architecture="gru", epochs=1),
        start_background=True,
    )
    training = await wait_for(orchestrator, training_id)
    assert training["status"] == "failed"
    assert training["error_category"] == "training_failure"
    assert not (store.private_dir / training_id / "checkpoint.pt").exists()
    assert not (store.private_dir / training_id / "manifest.json").exists()
    store.close()


@pytest.mark.asyncio
async def test_concurrent_worker_training_is_seed_reproducible(tmp_path: Path) -> None:
    store = TalonStore(tmp_path / "talon.sqlite3")
    orchestrator = TalonOrchestrator(store)
    dataset_id = orchestrator.create_dataset(DatasetCreate(), start_background=True)
    assert (await wait_for(orchestrator, dataset_id))["status"] == "completed"

    configuration = TrainingCreate(
        dataset_id=dataset_id,
        architecture="gru",
        epochs=1,
        batch_size=64,
        context_length=8,
        random_seed=31,
        timeout_seconds=90,
    )
    run_ids = [
        orchestrator.create_training(configuration, start_background=True)
        for _ in range(2)
    ]
    first, second = await asyncio.gather(
        *(wait_for(orchestrator, run_id) for run_id in run_ids)
    )
    assert first["status"] == second["status"] == "completed"
    assert first["training_history"] == second["training_history"]
    models = [
        load_checkpoint(
            store.private_dir / run_id / "checkpoint.pt",
            expected_digest=str(record["checkpoint_digest"]),
        )[0]
        for run_id, record in zip(run_ids, (first, second))
    ]
    assert all(
        torch.equal(models[0].state_dict()[key], models[1].state_dict()[key])
        for key in models[0].state_dict()
    )

    different_id = orchestrator.create_training(
        configuration.model_copy(update={"random_seed": 32}),
        start_background=True,
    )
    different = await wait_for(orchestrator, different_id)
    assert different["status"] == "completed"
    different_model, _ = load_checkpoint(
        store.private_dir / different_id / "checkpoint.pt",
        expected_digest=str(different["checkpoint_digest"]),
    )
    assert any(
        not torch.equal(models[0].state_dict()[key], different_model.state_dict()[key])
        for key in models[0].state_dict()
    )
    store.close()


@pytest.mark.asyncio
async def test_real_evaluation_sse_replay_and_allowlisted_export(tmp_path: Path) -> None:
    store = TalonStore(tmp_path / "talon.sqlite3")
    orchestrator = TalonOrchestrator(store)
    dataset_id = orchestrator.create_dataset(DatasetCreate(), start_background=True)
    await wait_for(orchestrator, dataset_id)
    training_id = orchestrator.create_training(
        TrainingCreate(dataset_id=dataset_id, architecture="gru", epochs=1, batch_size=64, timeout_seconds=60),
        start_background=True,
    )
    training = await wait_for(orchestrator, training_id)
    assert training["status"] == "completed", training
    evaluation_id = orchestrator.create_evaluation(
        EvaluationCreate(training_run_id=training_id, seed_count=1, timeout_seconds=90),
        start_background=True,
    )
    evaluation = await wait_for(orchestrator, evaluation_id)
    assert evaluation["status"] == "completed", evaluation
    assert evaluation["aggregate"]["episode_count"] == 15
    assert 0.0 <= evaluation["aggregate"]["held_out_action_accuracy"] <= 1.0
    assert 0.0 <= evaluation["aggregate"]["safety_violation_rate"] <= 1.0
    assert 0.0 <= evaluation["aggregate"]["false_escalation_rate"] <= 1.0
    assert 0.0 <= evaluation["aggregate"]["missed_threat_rate"] <= 1.0
    assert len(evaluation["episodes"]) == 15
    assert find_public_leaks(evaluation) == []
    events = store.events_after("talon_evaluation", evaluation_id)
    assert [event.id for event in events] == sorted(event.id for event in events)
    assert events[-1].event_type == "terminal"
    replay = store.events_after("talon_evaluation", evaluation_id, events[2].id)
    assert replay and replay[0].id > events[2].id
    assert (store.private_dir / evaluation_id / "verification.json").exists()
    store.close()


def test_sqlite_tampering_and_public_hidden_payload_are_rejected(tmp_path: Path) -> None:
    database = tmp_path / "talon.sqlite3"
    store = TalonStore(database)
    with pytest.raises(ValueError, match="sanitization"):
        store.create_record("dataset_" + "a" * 24, "dataset", {"nested": "authorised_inspection"})
    store.create_record("record_a", "test", {"schema_version": "safe/1"})
    store.finalize("record_a", "completed", {"result": "ok"})
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT payload_json FROM talon_records WHERE record_id='record_a'").fetchone()
        payload = json.loads(row[0])
        payload["status"] = "tampered"
        connection.execute("UPDATE talon_records SET payload_json=? WHERE record_id='record_a'", (json.dumps(payload),))
    with pytest.raises(TalonImmutableRecordError, match="digest binding"):
        store.get("record_a")
    store.close()


def test_deletion_plan_restart_recovery_rolls_back_or_completes(tmp_path: Path) -> None:
    database = tmp_path / "talon.sqlite3"
    store = TalonStore(database)
    store.create_record("record_rollback", "test", {"schema_version": "safe/1"})
    store.finalize("record_rollback", "completed", {"result": "ok"})
    public = store._record_directory("record_rollback")
    quarantine = store.quarantine_dir / "record_rollback"
    with store._connection:
        store._connection.execute(
            "INSERT INTO talon_deletion_plans VALUES(?,?,?)",
            ("record_rollback", "planned", "2026-01-01T00:00:00Z"),
        )
    os.replace(public, quarantine)
    store.close()

    recovered = TalonStore(database)
    assert recovered.get("record_rollback") is not None
    assert public.exists() and not quarantine.exists()
    recovered.create_record("record_complete", "test", {"schema_version": "safe/1"})
    recovered.finalize("record_complete", "completed", {"result": "ok"})
    complete_public = recovered._record_directory("record_complete")
    complete_private = recovered._private_directory("record_complete")
    complete_quarantine = recovered.quarantine_dir / "record_complete"
    with recovered._connection:
        recovered._connection.execute(
            "INSERT INTO talon_deletion_plans VALUES(?,?,?)",
            ("record_complete", "db_deleted", "2026-01-01T00:00:00Z"),
        )
        recovered._connection.execute("DELETE FROM talon_records WHERE record_id='record_complete'")
    os.replace(complete_public, complete_quarantine)
    recovered.close()

    completed = TalonStore(database)
    assert completed.get("record_complete") is None
    assert not complete_quarantine.exists()
    assert not complete_private.exists()
    completed.close()
