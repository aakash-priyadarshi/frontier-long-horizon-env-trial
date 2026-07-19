"""Cancel-vs-complete publication races for Talon checkpoints."""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from pathlib import Path

import pytest
import torch

from drone_training.datasets import generate_dataset
from drone_training.offline_checkpoints import save_offline_checkpoint
from drone_training.offline_rl import (
    CQLConfig,
    derive_offline_dataset,
    discrete_cql_loss,
    masked_argmax,
    masked_max_q,
    train_discrete_cql,
)
from drone_training.orchestration import TalonOrchestrator
from drone_training.persistence import ACTIVE_STATUSES, TalonStore
from drone_training.schemas import DatasetCreate, TrainingCreate
from drone_training import worker as worker_module


def _idle_until_cancelled(queue_obj, cancelled_event) -> None:
    """Spawn-safe stub worker: does not emit terminal events."""

    deadline = time.monotonic() + 5.0
    while not cancelled_event.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)


async def wait_for(orchestrator: TalonOrchestrator, record_id: str) -> dict[str, object]:
    await orchestrator.wait(record_id)
    record = orchestrator.store.get(record_id)
    assert record is not None
    return record


@pytest.fixture(scope="module")
def tiny_offline():
    source = generate_dataset(partition="train", seeds=[0], families=["authorised_inspection"])
    offline = derive_offline_dataset(source, context_length=4)
    config = CQLConfig(
        context_length=4,
        hidden_dim=8,
        layers=1,
        dropout=0,
        batch_size=16,
        epochs=1,
        target_update_interval=2,
    )
    model, target, history = train_discrete_cql(offline, config)
    return offline, config, model, target, history


def test_td_backup_is_mask_only_while_selection_applies_safety_threshold() -> None:
    """Document the layered contract: mask-only TD vs threshold selection vs gate."""

    reward_q = torch.zeros((1, 13))
    reward_q[0, 0] = 10.0  # high reward but will be unsafe at selection
    reward_q[0, 1] = 3.0
    safety_q = torch.zeros((1, 13))
    safety_q[0, 0] = 0.9  # above threshold
    safety_q[0, 1] = 0.01
    mask = torch.ones((1, 13), dtype=torch.bool)

    # 1) Reward backup action selection: public mask only.
    max_q, argmax = masked_max_q(reward_q, mask)
    assert int(argmax[0]) == 0
    assert float(max_q[0]) == pytest.approx(10.0)

    # 2) Safety TD target uses that same next action (not safety-min / threshold filter).
    next_cost = safety_q.gather(1, argmax[:, None]).squeeze(1)
    assert float(next_cost[0]) == pytest.approx(0.9)

    # Safety threshold does not change the TD max action.
    loss = discrete_cql_loss(
        torch.zeros((1, 13), requires_grad=True),
        torch.full((1, 13), 0.2),
        torch.tensor([1]),
        torch.tensor([0.0]),
        torch.tensor([0.0]),
        reward_q,
        safety_q,
        mask,
        mask,
        torch.tensor([0.0]),
        gamma=0.99,
        alpha=0.0,
        safety_threshold=0.05,
    )
    assert torch.isfinite(loss["reward_td_loss"])

    # 3) Runtime safety threshold filtering at selection time.
    selected = masked_argmax(reward_q, safety_q, mask, 0.05)
    assert int(selected[0]) == 1

    # 4) Policy gate enforcement is outside this module; selection still yields a
    # recommendation that the gate may reject. The TD path must not silently
    # apply the threshold or the contracts above collapse into one filter.
    assert int(argmax[0]) != int(selected[0])


def test_try_complete_with_checkpoint_cas(tmp_path: Path) -> None:
    store = TalonStore(tmp_path / "talon.sqlite3")
    run_id = "train_" + ("b" * 24)
    store.create_record(
        run_id,
        "training",
        {"schema_version": "talon.public-training-record/2.0", "configuration": {}, "progress": {"phase": "queued"}},
    )
    store.update(run_id, "running", {"progress": {"phase": "running"}})
    store.update(run_id, "cancelling", {"progress": {"phase": "cancelling"}})

    lost = store.try_complete_with_checkpoint(
        run_id,
        result={"checkpoint_digest": "sha256:" + ("a" * 64)},
        expected_statuses=frozenset({"queued", "running"}),
    )
    assert lost is None
    assert store.get(run_id)["status"] == "cancelling"

    won = store.try_complete_with_checkpoint(
        run_id,
        result={"checkpoint_digest": "sha256:" + ("a" * 64), "model_id": run_id},
        expected_statuses=ACTIVE_STATUSES,
    )
    assert won is not None
    assert store.get(run_id)["status"] == "completed"
    assert store.try_complete_with_checkpoint(run_id, result={"checkpoint_digest": "sha256:" + ("c" * 64)}) is None
    store.close()


def test_offline_checkpoint_abort_after_temp_before_publish(tmp_path: Path, tiny_offline) -> None:
    offline, config, model, target, history = tiny_offline
    path = tmp_path / "checkpoint.pt"
    abort = {"value": False}
    phases: list[str] = []

    def barrier(phase: str) -> None:
        phases.append(phase)
        if phase == "after_temp_write":
            abort["value"] = True

    with pytest.raises(InterruptedError, match="aborted before link"):
        save_offline_checkpoint(
            path,
            model=model,
            target=target,
            dataset=offline,
            config=config,
            training_history=history,
            training_updates=1,
            should_abort=lambda: abort["value"],
            _test_barrier=barrier,
        )
    assert not path.exists()
    assert list(tmp_path.glob("*.partial")) == []
    assert phases == ["after_temp_write"]


def test_offline_checkpoint_abort_before_save_gate(tmp_path: Path, tiny_offline) -> None:
    offline, config, model, target, history = tiny_offline
    path = tmp_path / "checkpoint.pt"
    with pytest.raises(InterruptedError, match="aborted before link"):
        save_offline_checkpoint(
            path,
            model=model,
            target=target,
            dataset=offline,
            config=config,
            training_history=history,
            training_updates=1,
            should_abort=lambda: True,
        )
    assert not path.exists()


def test_offline_checkpoint_after_publish_ignores_later_abort(tmp_path: Path, tiny_offline) -> None:
    offline, config, model, target, history = tiny_offline
    path = tmp_path / "checkpoint.pt"
    abort = {"value": False}
    phases: list[str] = []

    def barrier(phase: str) -> None:
        phases.append(phase)
        if phase == "after_publish":
            abort["value"] = True

    digest = save_offline_checkpoint(
        path,
        model=model,
        target=target,
        dataset=offline,
        config=config,
        training_history=history,
        training_updates=1,
        should_abort=lambda: abort["value"],
        _test_barrier=barrier,
    )
    assert path.is_file()
    assert digest.startswith("sha256:")
    assert phases == ["after_temp_write", "before_publish", "after_publish"]


@pytest.mark.parametrize(
    "cancel_phase",
    ["after_train", "before_validation", "after_validation", "before_save"],
)
def test_inprocess_offline_worker_cancel_before_publish(tmp_path: Path, cancel_phase: str) -> None:
    store = TalonStore(tmp_path / "talon.sqlite3")
    orchestrator = TalonOrchestrator(store)
    dataset_id = orchestrator.create_dataset(
        DatasetCreate(seed_start=0, seed_count=1),
        start_background=False,
    )
    from drone_training.worker import run_job

    dataset_job = orchestrator._jobs[dataset_id]
    dataset_queue: queue.Queue = queue.Queue()
    run_job(
        "dataset",
        {"seed_start": 0, "seed_count": 1, "families": ["authorised_inspection"], "run_id": dataset_id},
        {"dataset": str(store.private_dir / dataset_id / "dataset.json"), "data_root": str(store.path.parent)},
        dataset_queue,
        dataset_job.cancelled,
    )
    completed_payload = None
    dataset_messages = []
    while True:
        try:
            message = dataset_queue.get_nowait()
        except queue.Empty:
            break
        dataset_messages.append(message)
        if message.get("type") == "completed":
            completed_payload = message["data"]
    assert completed_payload is not None, f"dataset worker did not complete: {dataset_messages!r}"
    store.finalize(dataset_id, "completed", completed_payload)
    assert store.get(dataset_id)["status"] == "completed"

    run_id = "offrun_" + ("c" * 23)
    store.create_record(
        run_id,
        "training",
        {"schema_version": "talon.public-training-record/2.0", "configuration": {}, "progress": {"phase": "running"}},
        status="running",
    )
    private = store._private_directory(run_id)
    paths = {
        "dataset": str(store.private_dir / dataset_id / "dataset.json"),
        "offline_dataset": str(private / "offline_dataset.json"),
        "checkpoint": str(private / "checkpoint.pt"),
        "manifest": str(private / "manifest.json"),
        "data_root": str(store.path.parent),
    }
    request = {
        "run_id": run_id,
        "context_length": 4,
        "hidden_dim": 8,
        "layers": 1,
        "dropout": 0.0,
        "gamma": 0.99,
        "cql_alpha": 1.0,
        "safety_threshold": 0.05,
        "learning_rate": 3e-4,
        "batch_size": 16,
        "epochs": 1,
        "target_update_interval": 2,
        "gradient_clip": 1.0,
        "random_seed": 0,
    }
    cancelled = threading.Event()
    work_queue: queue.Queue = queue.Queue()

    def hook(phase: str) -> None:
        if phase == cancel_phase:
            cancelled.set()

    previous = worker_module._TEST_PHASE_HOOK
    worker_module._TEST_PHASE_HOOK = hook
    try:
        run_job("offline_training", request, paths, work_queue, cancelled)
    finally:
        worker_module._TEST_PHASE_HOOK = previous

    messages = []
    while True:
        try:
            messages.append(work_queue.get_nowait())
        except queue.Empty:
            break
    assert any(item["type"] == "cancelled" for item in messages)
    assert not any(item["type"] == "completed" for item in messages)
    assert not Path(paths["checkpoint"]).exists()
    store.close()


@pytest.mark.asyncio
async def test_completed_drains_ahead_of_soft_cancel(tmp_path: Path) -> None:
    """After publish, a buffered completed message must win over cancelling."""

    store = TalonStore(tmp_path / "talon.sqlite3")
    orchestrator = TalonOrchestrator(store)
    record_id = orchestrator.create_dataset(DatasetCreate(), start_background=False)
    job = orchestrator._jobs[record_id]

    # Enqueue completed in the parent before the monitor runs so the test does
    # not depend on spawn-import latency for a custom child target.
    digest = "sha256:" + ("d" * 64)
    job.queue.put({"type": "completed", "data": {"checkpoint_digest": digest, "diagnostic": "prequeued"}})
    job.process = orchestrator._context.Process(target=_idle_until_cancelled, args=(job.queue, job.cancelled))
    task = asyncio.create_task(orchestrator._monitor(record_id))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        record = store.get(record_id)
        if job.completion_received or (record is not None and record.get("status") == "completed"):
            break
        await asyncio.sleep(0.01)
    assert job.completion_received or (store.get(record_id) or {}).get("status") == "completed"
    assert orchestrator.cancel(record_id) is False
    await task
    record = store.get(record_id)
    assert record is not None
    assert record["status"] == "completed"
    assert record["diagnostic"] == "prequeued"
    assert [event.event_type for event in store.events_after("talon_dataset", record_id)].count("terminal") == 1
    assert orchestrator.cancel(record_id) is False
    store.close()


@pytest.mark.asyncio
async def test_soft_cancel_drains_late_completed_from_queue(tmp_path: Path) -> None:
    """Cancelling while completed is already buffered must still complete."""

    store = TalonStore(tmp_path / "talon.sqlite3")
    orchestrator = TalonOrchestrator(store)
    record_id = orchestrator.create_dataset(DatasetCreate(), start_background=False)
    job = orchestrator._jobs[record_id]
    job.process = orchestrator._context.Process(target=_idle_until_cancelled, args=(job.queue, job.cancelled))
    task = asyncio.create_task(orchestrator._monitor(record_id))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and (store.get(record_id) or {}).get("status") != "running":
        await asyncio.sleep(0.01)
    job.queue.put(
        {
            "type": "completed",
            "data": {"checkpoint_digest": "sha256:" + ("e" * 64), "diagnostic": "late_complete"},
        }
    )
    assert orchestrator.cancel(record_id) is True
    await task
    record = store.get(record_id)
    assert record is not None
    assert record["status"] == "completed"
    assert record["diagnostic"] == "late_complete"
    assert [event.event_type for event in store.events_after("talon_dataset", record_id)].count("terminal") == 1
    store.close()


@pytest.mark.asyncio
async def test_real_training_cancel_leaves_no_usable_checkpoint(tmp_path: Path) -> None:
    store = TalonStore(tmp_path / "talon.sqlite3")
    orchestrator = TalonOrchestrator(store)
    dataset_id = orchestrator.create_dataset(DatasetCreate(), start_background=True)
    assert (await wait_for(orchestrator, dataset_id))["status"] == "completed"
    training_id = orchestrator.create_training(
        TrainingCreate(dataset_id=dataset_id, architecture="gru", epochs=500, timeout_seconds=120),
        start_background=True,
    )
    await asyncio.sleep(0.2)
    assert orchestrator.cancel(training_id) is True
    cancelled = await wait_for(orchestrator, training_id)
    assert cancelled["status"] == "cancelled"
    assert not (store.private_dir / training_id / "checkpoint.pt").exists()
    assert [event.event_type for event in store.events_after("talon_training", training_id)].count("terminal") == 1
    store.close()
