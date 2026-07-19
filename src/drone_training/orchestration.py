"""Killable, race-safe local orchestration for Talon jobs."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import queue as queue_module
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .persistence import TERMINAL_STATUSES, TalonImmutableRecordError, TalonStore
from .schemas import DatasetCreate, EvaluationCreate, OfflineRLTrainingCreate, TrainingCreate
from .worker import run_job


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


@dataclass
class _Job:
    operation: str
    process: Any
    queue: Any
    cancelled: Any
    timeout_seconds: int
    completion_received: bool = False


class TalonOrchestrator:
    def __init__(self, store: TalonStore) -> None:
        self.store = store
        self._context = mp.get_context("spawn")
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._jobs: dict[str, _Job] = {}
        self._creation_lock = threading.RLock()

    def _create(
        self,
        *,
        operation: str,
        record_id: str,
        kind: str,
        configuration: dict[str, Any],
        timeout_seconds: int,
        paths: dict[str, str],
        depends_on: tuple[str, ...] = (),
        idempotency_key: str | None = None,
        start_background: bool = True,
    ) -> str:
        with self._creation_lock:
            existing = self.store.resolve_idempotency(operation, idempotency_key, configuration)
            if existing is not None:
                return existing
            self.store.create_record(
                record_id,
                kind,
                {
                    "schema_version": f"talon.public-{kind}-record/2.0",
                    "configuration": configuration,
                    "application_commit": _git_sha(),
                    "progress": {"phase": "queued"},
                },
                depends_on=depends_on,
            )
            bound = self.store.bind_idempotency(operation, idempotency_key, configuration, record_id)
            if bound != record_id:
                raise RuntimeError("idempotent creation race left an unexpected local record")
        scope = self._scope(kind)
        self.store.append_event(scope, record_id, "queued", {"record_id": record_id, "status": "queued"})
        cancellation = self._context.Event()
        paths = {**paths, "data_root": str(self.store.path.parent)}
        worker_request = {
            **configuration,
            "run_id": record_id,
            "application_commit": _git_sha(),
        }
        work_queue = self._context.Queue()
        process = self._context.Process(
            target=run_job,
            args=(operation, worker_request, paths, work_queue, cancellation),
            name=f"talon-{operation}-{record_id[-8:]}",
        )
        self._jobs[record_id] = _Job(operation, process, work_queue, cancellation, timeout_seconds)
        if start_background:
            task = asyncio.create_task(self._monitor(record_id))
            self._tasks[record_id] = task
        return record_id

    @staticmethod
    def _scope(kind: str) -> str:
        return {
            "dataset": "talon_dataset",
            "training": "talon_training",
            "evaluation": "talon_evaluation",
        }[kind]

    def create_dataset(self, request: DatasetCreate, *, idempotency_key: str | None = None, start_background: bool = True) -> str:
        record_id = "dataset_" + uuid.uuid4().hex[:24]
        private = self.store._private_directory(record_id) / "dataset.json"
        return self._create(
            operation="dataset",
            record_id=record_id,
            kind="dataset",
            configuration=request.model_dump(mode="json"),
            timeout_seconds=request.timeout_seconds,
            paths={"dataset": str(private)},
            idempotency_key=idempotency_key,
            start_background=start_background,
        )

    def create_training(self, request: TrainingCreate, *, idempotency_key: str | None = None, start_background: bool = True) -> str:
        dataset = self.store.get(request.dataset_id)
        if dataset is None or dataset.get("kind") != "dataset" or dataset.get("status") != "completed":
            raise ValueError("completed training dataset was not found")
        run_id = "talon_train_" + uuid.uuid4().hex
        private = self.store._private_directory(run_id)
        return self._create(
            operation="training",
            record_id=run_id,
            kind="training",
            configuration=request.model_dump(mode="json"),
            timeout_seconds=request.timeout_seconds,
            paths={
                "dataset": str(self.store._private_directory(request.dataset_id) / "dataset.json"),
                "checkpoint": str(private / "checkpoint.pt"),
                "manifest": str(private / "manifest.json"),
            },
            depends_on=(request.dataset_id,),
            idempotency_key=idempotency_key,
            start_background=start_background,
        )

    def create_offline_training(self, request: OfflineRLTrainingCreate, *, idempotency_key: str | None = None, start_background: bool = True) -> str:
        dataset = self.store.get(request.dataset_id)
        if dataset is None or dataset.get("kind") != "dataset" or dataset.get("status") != "completed":
            raise ValueError("completed training dataset was not found")
        run_id = "talon_cql_" + uuid.uuid4().hex
        private = self.store._private_directory(run_id)
        return self._create(
            operation="offline_training",
            record_id=run_id,
            kind="training",
            configuration=request.model_dump(mode="json"),
            timeout_seconds=request.timeout_seconds,
            paths={
                "dataset": str(self.store._private_directory(request.dataset_id) / "dataset.json"),
                "offline_dataset": str(private / "offline_dataset.json"),
                "checkpoint": str(private / "checkpoint.pt"),
                "manifest": str(private / "manifest.json"),
            },
            depends_on=(request.dataset_id,),
            idempotency_key=idempotency_key,
            start_background=start_background,
        )

    def create_evaluation(self, request: EvaluationCreate, *, idempotency_key: str | None = None, start_background: bool = True) -> str:
        from .bindings import assert_product_checkpoint_usable, require_dataset_bindings

        training = self.store.get(request.training_run_id)
        if training is None or training.get("kind") != "training" or training.get("status") != "completed":
            raise ValueError("completed training run was not found")
        if training.get("checkpoint_unavailable") is True or not self.store.checkpoint_is_available(request.training_run_id):
            raise ValueError("training checkpoint is marked unavailable")
        binding = assert_product_checkpoint_usable(self.store.private_dir, training)
        evaluation_id = "talon_eval_" + uuid.uuid4().hex
        private = self.store._private_directory(evaluation_id)
        configuration = request.model_dump(mode="json")
        configuration["checkpoint_digest"] = binding.trusted_digest
        configuration["artifact_identity"] = binding.artifact_identity
        configuration["checkpoint_binding_source"] = binding.binding_source.value
        offline = training.get("architecture") == "cql_gru" or training.get("algorithm") == "discrete_cql"
        if offline:
            offline_digest, source_digest = require_dataset_bindings(binding)
            configuration["offline_dataset_digest"] = offline_digest
            configuration["dataset_digest"] = source_digest
        elif binding.offline_dataset_digest is not None:
            configuration["offline_dataset_digest"] = binding.offline_dataset_digest
        if not offline and binding.source_dataset_digest is not None:
            configuration["dataset_digest"] = binding.source_dataset_digest
        # Path is derived from the trusted logical identity, never a free-form absolute path.
        checkpoint_path = self.store.private_dir / Path(*binding.artifact_identity.split("/"))
        return self._create(
            operation="offline_evaluation" if offline else "evaluation",
            record_id=evaluation_id,
            kind="evaluation",
            configuration=configuration,
            timeout_seconds=request.timeout_seconds,
            paths={
                "dataset": str(self.store._private_directory(training["configuration"]["dataset_id"]) / "dataset.json"),
                "checkpoint": str(checkpoint_path),
                "private_evaluation": str(private / "verification.json"),
            },
            depends_on=(request.training_run_id,),
            idempotency_key=idempotency_key,
            start_background=start_background,
        )

    def create_completed_comparison(
        self,
        *,
        configuration: dict[str, Any],
        payload: dict[str, Any],
        results: dict[str, Any],
        depends_on: tuple[str, ...],
        idempotency_key: str | None = None,
    ) -> tuple[str, bool]:
        """Create one immutable comparison under the same race guard as async jobs."""
        with self._creation_lock:
            existing = self.store.resolve_idempotency("comparison", idempotency_key, configuration)
            if existing is not None:
                return existing, False
            comparison_id = "talon_compare_" + uuid.uuid4().hex
            self.store.create_record(
                comparison_id,
                "comparison",
                payload,
                status="running",
                depends_on=depends_on,
            )
            bound = self.store.bind_idempotency(
                "comparison", idempotency_key, configuration, comparison_id
            )
            if bound != comparison_id:
                raise RuntimeError("idempotent comparison creation race left an unexpected local record")
            self.store.finalize(comparison_id, "completed", results)
            return comparison_id, True

    async def _stop_process(self, job: _Job) -> None:
        if job.process.is_alive():
            job.cancelled.set()
            job.process.terminate()
            await asyncio.to_thread(job.process.join, 5)
        if job.process.is_alive():
            job.process.kill()
            await asyncio.to_thread(job.process.join, 5)

    def _cleanup_partial_artifacts(self, record_id: str, operation: str) -> None:
        private = self.store._private_directory(record_id)
        for item in private.glob("*.partial"):
            item.unlink(missing_ok=True)
        if operation != "dataset":
            checkpoint = private / "checkpoint.pt"
            if checkpoint.exists():
                try:
                    checkpoint.chmod(0o600)
                except OSError:
                    pass
                checkpoint.unlink(missing_ok=True)
            (private / "manifest.json").unlink(missing_ok=True)
            (private / "verification.json").unlink(missing_ok=True)
            (private / "offline_dataset.json").unlink(missing_ok=True)
        if operation == "dataset":
            (private / "dataset.json").unlink(missing_ok=True)

    async def _monitor(self, record_id: str) -> None:
        job = self._jobs[record_id]
        record = self.store.get(record_id)
        if record is None:
            return
        scope = self._scope(str(record["kind"]))
        started = time.monotonic()
        terminal_status: str | None = None
        terminal_payload: dict[str, Any] = {}

        def accept_message(message: dict[str, Any]) -> None:
            nonlocal terminal_status, terminal_payload
            message_type = str(message.get("type"))
            data = message.get("data") if isinstance(message.get("data"), dict) else {}
            if message_type == "progress":
                progress = {"phase": "running", **data}
                self.store.update(record_id, "running", {"progress": progress})
                self.store.append_event(scope, record_id, "progress", {"record_id": record_id, "progress": progress})
            elif message_type == "episode":
                progress = {"phase": "running", **data}
                self.store.update(record_id, "running", {"progress": progress})
                self.store.append_event(scope, record_id, "episode_completed", {"record_id": record_id, **data})
            elif message_type == "timeline_step":
                self.store.append_event(scope, record_id, "timeline_step", {"record_id": record_id, **data})
            elif message_type == "completed":
                # Publication already happened in the worker; completed always wins
                # over in-flight cancel/timeout/failure classification.
                job.completion_received = True
                terminal_status = "completed"
                terminal_payload = data
            elif message_type in {"cancelled", "timed_out", "failed"}:
                if job.completion_received or terminal_status == "completed":
                    return
                terminal_status = message_type
                terminal_payload = data

        def drain_queue() -> None:
            while True:
                try:
                    buffered = job.queue.get_nowait()
                except queue_module.Empty:
                    break
                if isinstance(buffered, dict):
                    accept_message(buffered)

        try:
            if record.get("status") == "cancelling":
                terminal_status = "cancelled"
                terminal_payload = {"error_category": "cancelled_before_start"}
            else:
                job.process.start()
                self.store.update(record_id, "running", {"progress": {"phase": "running"}})
                self.store.append_event(scope, record_id, "started", {"record_id": record_id, "status": "running"})
            while terminal_status is None:
                message: dict[str, Any] | None = None
                try:
                    message = job.queue.get_nowait()
                except queue_module.Empty:
                    pass
                if message:
                    accept_message(message)
                current = self.store.get(record_id)
                if terminal_status is None and current and current.get("status") == "cancelling":
                    # A worker may have published and enqueued completed just
                    # before soft-cancel. Drain repeatedly: multiprocessing.Queue
                    # visibility can lag on Windows after Process.put.
                    for _ in range(5):
                        drain_queue()
                        if terminal_status is not None:
                            break
                        await asyncio.sleep(0.02)
                    if terminal_status is None:
                        terminal_status = "cancelled"
                        terminal_payload = {"error_category": "cancelled"}
                if terminal_status is None and time.monotonic() - started >= job.timeout_seconds:
                    for _ in range(5):
                        drain_queue()
                        if terminal_status is not None:
                            break
                        await asyncio.sleep(0.02)
                    if terminal_status is None:
                        terminal_status = "timed_out"
                        terminal_payload = {"error_category": "execution_timeout"}
                if terminal_status is None and job.process.exitcode is not None:
                    # A fast worker can exit while multiple progress/timeline
                    # messages are still ahead of its terminal message. Join
                    # the queue feeder and drain every buffered message before
                    # classifying the process as crashed.
                    await asyncio.to_thread(job.process.join, 0.5)
                    for _ in range(5):
                        drain_queue()
                        if terminal_status is not None:
                            break
                        await asyncio.sleep(0.02)
                    if terminal_status is None:
                        terminal_status = "failed"
                        terminal_payload = {"error_category": f"{job.operation}_worker_crash"}
                if terminal_status is None:
                    await asyncio.sleep(0.05)

            await self._stop_process(job)
            if terminal_status != "completed":
                self._cleanup_partial_artifacts(record_id, job.operation)
            try:
                if terminal_status == "completed":
                    digest = self.store.try_complete_with_checkpoint(record_id, result=terminal_payload)
                    if digest is None:
                        # Soft-cancel / timeout already finalised, or a stricter
                        # expected-status set rejected completion after publish loss.
                        self._cleanup_partial_artifacts(record_id, job.operation)
                        final = self.store.get(record_id)
                        if final is None or final.get("status") not in TERMINAL_STATUSES:
                            digest = self.store.finalize(
                                record_id,
                                "cancelled",
                                {"error_category": "cancelled_after_losing_publish_race"},
                            )
                            terminal_status = "cancelled"
                        else:
                            digest = str(final.get("record_digest", ""))
                            terminal_status = str(final["status"])
                    else:
                        terminal_status = "completed"
                else:
                    digest = self.store.finalize(record_id, terminal_status, terminal_payload)
            except TalonImmutableRecordError:
                final = self.store.get(record_id)
                if final is None:
                    return
                digest = str(final.get("record_digest", ""))
                terminal_status = str(final["status"])
            self.store.append_terminal_event(
                scope,
                record_id,
                {"record_id": record_id, "status": terminal_status, "record_digest": digest},
            )
        finally:
            self._tasks.pop(record_id, None)
            self._jobs.pop(record_id, None)
            try:
                job.queue.close()
                job.queue.join_thread()
            except (AttributeError, OSError):
                pass

    def cancel(self, record_id: str) -> bool:
        record = self.store.get(record_id)
        if record is None or record.get("status") in TERMINAL_STATUSES:
            return False
        if record.get("status") == "cancelling":
            return True
        job = self._jobs.get(record_id)
        if job is not None and job.completion_received:
            return False
        if job is not None:
            job.cancelled.set()
        self.store.update(record_id, "cancelling", {"progress": {"phase": "cancelling"}})
        self.store.append_event(self._scope(str(record["kind"])), record_id, "cancellation_requested", {"record_id": record_id})
        return True

    async def wait(self, record_id: str) -> None:
        while True:
            task = self._tasks.get(record_id)
            if task is not None:
                await asyncio.shield(task)
                return
            record = self.store.get(record_id)
            if record is None or record.get("status") in TERMINAL_STATUSES:
                return
            await asyncio.sleep(0.05)

    async def run_training(self, run_id: str) -> None:
        await self._monitor(run_id)

    async def run_evaluation(self, run_id: str) -> None:
        await self._monitor(run_id)

    async def shutdown(self) -> None:
        for record_id in tuple(self._jobs):
            self.cancel(record_id)
        tasks = tuple(self._tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
