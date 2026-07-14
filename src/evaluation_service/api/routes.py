"""Typed local-only evaluation API routes."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from model_runners.errors import ProviderConfigurationError
from model_runners.registry import ProviderRegistry

from ..comparison import compare_batches
from ..orchestration import EvaluationOrchestrator
from ..persistence import EvaluationStore, canonical_json
from ..sanitization import contains_forbidden_public_data
from ..schemas import EvaluationCreate, ProviderSessionConfiguration, ProviderToolProbeRequest
from ..settings import Settings, dashboard_origins
from ..tool_use_debug import analyze_tool_use


TERMINAL_BATCH = {"completed", "completed_with_errors", "cancelled", "interrupted"}
TERMINAL_RUN = {"completed", "failed", "cancelled", "interrupted"}


def _not_found(kind: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": f"{kind}_not_found", "message": f"{kind} was not found"})


def build_router(
    store: EvaluationStore,
    orchestrator: EvaluationOrchestrator,
    registry: ProviderRegistry,
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    def no_store(value: dict[str, Any], *, status_code: int = 200) -> JSONResponse:
        return JSONResponse(
            value,
            status_code=status_code,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"},
        )

    def validate_provider_control_request(request: Request) -> None:
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise HTTPException(
                status_code=403,
                detail={"code": "local_request_required", "message": "provider settings are available only on loopback"},
            )
        origin = request.headers.get("origin", "").rstrip("/")
        if origin not in dashboard_origins(settings.dashboard_origin):
            raise HTTPException(
                status_code=403,
                detail={"code": "origin_not_allowed", "message": "provider settings request origin is not allowed"},
            )

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

    @router.get("/providers/ollama/tool-support")
    async def ollama_tool_support() -> JSONResponse:
        return no_store(registry.ollama_tool_support())

    @router.get("/providers/{provider}/models")
    async def provider_models(provider: str) -> dict[str, Any]:
        try:
            status = registry.status(provider)
            return {"provider": provider, "items": status["models"], "model_discovery": status["model_discovery"]}
        except KeyError:
            raise _not_found("provider")

    @router.post("/providers/{provider}/credentials")
    async def configure_provider(
        request: Request,
        provider: str,
        payload: ProviderSessionConfiguration,
    ) -> JSONResponse:
        validate_provider_control_request(request)
        try:
            credential = payload.credential.get_secret_value() if payload.credential is not None else None
            status = registry.set_session_configuration(
                provider,
                credential=credential,
                base_url=payload.base_url,
                update_base_url="base_url" in payload.model_fields_set,
            )
        except KeyError:
            raise _not_found("provider")
        except ProviderConfigurationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        return no_store({"provider": status})

    @router.delete("/providers/{provider}/credentials")
    async def clear_provider_credential(request: Request, provider: str) -> JSONResponse:
        validate_provider_control_request(request)
        try:
            status = registry.clear_session_credential(provider)
        except KeyError:
            raise _not_found("provider")
        return no_store({"provider": status})

    @router.post("/providers/{provider}/connection-test")
    async def test_provider_connection(request: Request, provider: str) -> JSONResponse:
        validate_provider_control_request(request)
        try:
            status = await registry.discover_models(provider)
        except KeyError:
            raise _not_found("provider")
        return no_store({"provider": status})

    @router.post("/providers/{provider}/tool-probe")
    async def test_provider_tool_call(
        request: Request,
        provider: str,
        payload: ProviderToolProbeRequest,
    ) -> JSONResponse:
        validate_provider_control_request(request)
        try:
            result = await registry.probe_tool_call(
                provider,
                payload.model,
                options=payload.options.model_dump() if payload.options is not None else None,
            )
            status = registry.status(provider)
        except KeyError:
            raise _not_found("provider")
        except ProviderConfigurationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        return no_store({"provider": status, "tool_compatibility": result})

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

    def run_summary(value: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "run_id", "batch_id", "status", "provider", "model", "split", "seed", "attempt",
            "instance_id", "current_step", "current_tool", "authoritative_reward",
            "authoritative_verdict", "action_count", "model_call_count", "input_tokens",
            "output_tokens", "reasoning_tokens", "cached_tokens", "estimated_cost", "elapsed_ms",
            "provider_latency_ms", "termination_reason", "error_category", "created_at", "updated_at",
            "started_at", "ended_at",
        )
        return {field: value.get(field) for field in fields}

    @router.get("/evaluations/{batch_id}/events")
    async def batch_events(
        request: Request, batch_id: str,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
        after: Annotated[int, Query(ge=0)] = 0,
    ) -> StreamingResponse:
        if store.get_batch(batch_id, include_runs=False) is None:
            raise _not_found("batch")
        return StreamingResponse(event_stream("batch", batch_id, replay_id(last_event_id, after), request), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.get("/runs")
    async def runs(
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        items, total = store.list_runs(limit=limit, offset=offset)
        return {
            "items": [run_summary(item) for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @router.get("/runs/{run_id}")
    async def run(run_id: str) -> dict[str, Any]:
        result = store.get_run(run_id)
        if result is None:
            raise _not_found("run")
        # Computed on read so historical episodes gain the debug panel without re-running.
        return {**result, "tool_use_debug": analyze_tool_use(result)}

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
