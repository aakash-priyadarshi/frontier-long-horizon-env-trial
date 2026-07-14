"""Shared batch orchestration used by API and CLI."""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from pathlib import Path
from typing import Any

from model_runners.registry import ProviderRegistry

from .persistence import EvaluationStore
from .runner import EpisodeRunner
from .schemas import EvaluationCreate


def _git_sha(ref: str) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", ref], cwd=Path.cwd(), check=True,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class EvaluationOrchestrator:
    def __init__(self, store: EvaluationStore, registry: ProviderRegistry | None = None) -> None:
        self.store = store
        self.registry = registry or ProviderRegistry()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancel: dict[str, asyncio.Event] = {}

    def create(self, request: EvaluationCreate, *, start_background: bool = True) -> str:
        provider = next((item for item in self.registry.list() if item["provider"] == request.provider), None)
        if provider is None:
            raise ValueError("unknown provider")
        if not provider["configured"]:
            raise ValueError("provider is not configured")
        if not provider["ready"]:
            raise ValueError("provider endpoint is not ready")
        selected_model = next(
            (model for model in provider["models"] if model.get("id") == request.model),
            None,
        )
        tool_state = selected_model.get("tool_compatibility", {}).get("state") if selected_model else None
        if selected_model and tool_state == "failed":
            raise ValueError("selected model failed the required tool compatibility test")
        if request.provider == "ollama" and selected_model and tool_state != "passed":
            raise ValueError("selected Ollama model must pass the current tool compatibility test")
        batch_id = "batch_" + uuid.uuid4().hex
        environment_commit = _git_sha("main")
        application_commit = _git_sha("HEAD")
        self.store.create_batch(batch_id, request, environment_commit=environment_commit, application_commit=application_commit)
        for seed in range(request.seed_start, request.seed_start + request.seed_count):
            for attempt in range(1, request.attempts + 1):
                run_id = "run_" + uuid.uuid4().hex
                self.store.create_run(
                    run_id, batch_id, split=request.split, seed=seed, attempt=attempt,
                    provider=request.provider, model=request.model,
                    payload={
                        "export_version": "2.0.0", "split": request.split, "seed": seed, "attempt": attempt,
                        "provider": request.provider, "model": request.model,
                        "model_configuration": request.model_configuration.model_dump(mode="json"),
                        "limits": request.limits.model_dump(mode="json"),
                        "environment_commit": environment_commit, "application_commit": application_commit,
                    },
                )
        self.store.append_event("batch", batch_id, "batch_queued", {"batch_id": batch_id, "total_runs": request.seed_count * request.attempts})
        self._cancel[batch_id] = asyncio.Event()
        if start_background:
            self._tasks[batch_id] = asyncio.create_task(self.run_batch(batch_id))
        return batch_id

    async def run_batch(self, batch_id: str) -> None:
        batch = self.store.get_batch(batch_id)
        if batch is None:
            raise KeyError(batch_id)
        request = EvaluationCreate.model_validate(batch["configuration"])
        cancellation = self._cancel.setdefault(batch_id, asyncio.Event())
        semaphore = asyncio.Semaphore(request.concurrency)
        self.store.update_batch_status(batch_id, "running")
        self.store.append_event("batch", batch_id, "batch_started", {"batch_id": batch_id})

        async def execute(run: dict[str, Any]) -> None:
            async with semaphore:
                if cancellation.is_set():
                    self.store.finalize_run(run["run_id"], "cancelled", {"termination_reason": "cancelled", "error_category": "cancelled"})
                    return
                self.store.update_run_progress(run["run_id"], "running", {"started_at": run.get("started_at")})

                async def emit(event_type: str, data: dict[str, Any]) -> None:
                    safe = {"run_id": run["run_id"], **data}
                    self.store.append_event("run", run["run_id"], event_type, safe)
                    self.store.append_event("batch", batch_id, event_type, safe)
                    progress = {key: data[key] for key in ("current_step", "current_tool", "input_tokens", "output_tokens", "estimated_cost", "instance_id") if key in data}
                    if progress:
                        try:
                            self.store.update_run_progress(run["run_id"], "running", progress)
                        except Exception:
                            pass

                episode = EpisodeRunner(
                    adapter=self.registry.create(request.provider), request=request,
                    seed=int(run["seed"]), attempt=int(run["attempt"]),
                    environment_commit=batch["environment_commit"], application_commit=batch["application_commit"],
                    cancelled=cancellation, emit=emit,
                )
                outcome = await episode.run()
                digest = self.store.finalize_run(run["run_id"], outcome.status, outcome.payload)
                await emit("run_finished", {"status": outcome.status, "record_digest": digest, "authoritative_reward": outcome.payload.get("authoritative_reward"), "authoritative_verdict": outcome.payload.get("authoritative_verdict")})

        runs, _ = self.store.list_runs(batch_id=batch_id, limit=10_000)
        await asyncio.gather(*(execute(run) for run in runs))
        refreshed = self.store.get_batch(batch_id, include_runs=False)
        assert refreshed is not None
        if cancellation.is_set():
            final_status = "cancelled"
        elif refreshed["failed_runs"]:
            final_status = "completed_with_errors"
        else:
            final_status = "completed"
        self.store.update_batch_status(batch_id, final_status)
        self.store.append_event("batch", batch_id, "batch_finished", {"batch_id": batch_id, "status": final_status})

    def cancel(self, batch_id: str) -> bool:
        batch = self.store.get_batch(batch_id, include_runs=False)
        if batch is None:
            return False
        event = self._cancel.setdefault(batch_id, asyncio.Event())
        event.set()
        self.store.update_batch_status(batch_id, "cancelling")
        self.store.append_event("batch", batch_id, "batch_cancelling", {"batch_id": batch_id})
        return True

    async def wait(self, batch_id: str) -> None:
        task = self._tasks.get(batch_id)
        if task:
            await task
