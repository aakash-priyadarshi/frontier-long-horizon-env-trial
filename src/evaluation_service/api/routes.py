"""Typed local-only evaluation API routes."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from model_runners.registry import ProviderRegistry

from ..comparison import compare_batches
from ..orchestration import EvaluationOrchestrator
from ..persistence import EvaluationStore, canonical_json
from ..sanitization import contains_forbidden_public_data
from ..schemas import EvaluationCreate


TERMINAL_BATCH = {"completed", "completed_with_errors", "cancelled", "interrupted"}
TERMINAL_RUN = {"completed", "failed", "cancelled", "interrupted"}


def _not_found(kind: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": f"{kind}_not_found", "message": f"{kind} was not found"})


def build_router(store: EvaluationStore, orchestrator: EvaluationOrchestrator, registry: ProviderRegistry) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health")
    async def health() -> dict[str, Any]:
        batches, total = store.list_batches(limit=5)
        runs, run_total = store.list_runs(limit=200)
        completed = [run for run in runs if run.get("status") == "completed"]
        rewards = [float(run["authoritative_reward"]) for run in completed if isinstance(run.get("authoritative_reward"), (int, float))]
        actions = [int(run["action_count"]) for run in completed if isinstance(run.get("action_count"), int)]
        costs = [float(run["estimated_cost"]) for run in completed if isinstance(run.get("estimated_cost"), (int, float))]
        successes = sum(1 for reward in rewards if reward == 1.0)
        return {
            "status": "ok", "schema_version": store.schema_version,
            "overview": {
                "total_evaluations": total, "total_completed_episodes": len(completed),
                "strict_success_rate": successes / len(rewards) if rewards else None,
                "average_reward": sum(rewards) / len(rewards) if rewards else None,
                "average_actions": sum(actions) / len(actions) if actions else None,
                "average_cost_per_success": sum(costs) / successes if costs and successes else None,
            },
            "recent_batches": batches,
            "recent_failures": [run for run in runs if run.get("status") in {"failed", "interrupted"}][:5],
            "run_total": run_total,
            "environment_commit": batches[0]["environment_commit"] if batches else "abcb015d320d3036d223ec1ba540662503acb588",
            "frozen_v1_tag": "abcb015d320d3036d223ec1ba540662503acb588",
            "scoring_authority": "existing strict verifier",
        }

    @router.get("/providers")
    async def providers() -> dict[str, Any]:
        return {"items": registry.list()}

    @router.get("/providers/{provider}/models")
    async def provider_models(provider: str) -> dict[str, Any]:
        try:
            return {"provider": provider, "items": registry.models(provider)}
        except KeyError:
            raise _not_found("provider")

    @router.post("/evaluations", status_code=202)
    async def create_evaluation(payload: EvaluationCreate) -> dict[str, Any]:
        try:
            batch_id = orchestrator.create(payload)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "provider_unavailable", "message": str(exc)}) from exc
        return {"batch_id": batch_id, "status": "queued"}

    @router.get("/evaluations")
    async def evaluations(
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        items, total = store.list_batches(limit=limit, offset=offset)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @router.get("/evaluations/{batch_id}")
    async def evaluation(
        batch_id: str,
        run_limit: Annotated[int, Query(ge=1, le=200)] = 100,
        run_offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        batch = store.get_batch(batch_id, run_limit=run_limit, run_offset=run_offset)
        if batch is None:
            raise _not_found("batch")
        return batch

    @router.post("/evaluations/{batch_id}/cancel", status_code=202)
    async def cancel_evaluation(batch_id: str) -> dict[str, Any]:
        if not orchestrator.cancel(batch_id):
            raise _not_found("batch")
        return {"batch_id": batch_id, "status": "cancelling"}

    async def event_stream(scope_type: str, scope_id: str, last_id: int, request: Request) -> AsyncIterator[str]:
        cursor = last_id
        idle_ticks = 0
        while not await request.is_disconnected():
            events = store.events_after(scope_type, scope_id, cursor)
            if events:
                idle_ticks = 0
                for event in events:
                    cursor = event.id
                    yield event.sse()
            else:
                idle_ticks += 1
                if idle_ticks % 40 == 0:
                    yield ": keep-alive\n\n"
            record = store.get_batch(scope_id, include_runs=False) if scope_type == "batch" else store.get_run(scope_id)
            terminal = TERMINAL_BATCH if scope_type == "batch" else TERMINAL_RUN
            if record and record.get("status") in terminal and not events:
                break
            await asyncio.sleep(0.25)

    def replay_id(header_value: str | None, query_value: int) -> int:
        if header_value and header_value.isdigit():
            return int(header_value)
        return query_value

    @router.get("/evaluations/{batch_id}/events")
    async def batch_events(
        request: Request, batch_id: str,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
        after: Annotated[int, Query(ge=0)] = 0,
    ) -> StreamingResponse:
        if store.get_batch(batch_id, include_runs=False) is None:
            raise _not_found("batch")
        return StreamingResponse(event_stream("batch", batch_id, replay_id(last_event_id, after), request), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.get("/runs/{run_id}")
    async def run(run_id: str) -> dict[str, Any]:
        result = store.get_run(run_id)
        if result is None:
            raise _not_found("run")
        return result

    @router.get("/runs/{run_id}/events")
    async def run_events(
        request: Request, run_id: str,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
        after: Annotated[int, Query(ge=0)] = 0,
    ) -> StreamingResponse:
        if store.get_run(run_id) is None:
            raise _not_found("run")
        return StreamingResponse(event_stream("run", run_id, replay_id(last_event_id, after), request), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.get("/comparisons")
    async def comparisons(batch: Annotated[list[str], Query()] = []) -> dict[str, Any]:
        if not batch:
            batches, _ = store.list_batches(limit=10)
            batch = [item["batch_id"] for item in batches]
        return compare_batches(store, batch)

    @router.get("/exports/{batch_id}.json")
    async def export_batch(batch_id: str) -> JSONResponse:
        batch = store.get_batch(batch_id, run_limit=10_000)
        if batch is None:
            raise _not_found("batch")
        payload = {"export_version": "2.0.0", "batch": batch}
        if contains_forbidden_public_data(payload):
            raise HTTPException(status_code=500, detail={"code": "export_sanitization_failed", "message": "export failed sanitization"})
        return JSONResponse(
            payload,
            headers={"Content-Disposition": f'attachment; filename="{batch_id}.json"', "X-Content-Type-Options": "nosniff"},
        )

    return router
