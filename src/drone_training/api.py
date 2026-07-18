"""Local-only safe public API routes for Talon simulation and training."""

from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from drone_decision_ground.actions import ACTION_SCHEMA_VERSION, DecisionAction
from drone_decision_ground.authority import POLICY_PROFILES
from drone_decision_ground.policy_gate import POLICY_GATE_VERSION
from drone_decision_ground.scenarios import list_public_capabilities
from evaluation_service.settings import Settings, dashboard_origins

from .exports import public_evaluation_export, public_record_detail, public_record_summary
from .orchestration import TalonOrchestrator
from .persistence import TERMINAL_STATUSES, TalonIdempotencyConflict, TalonImmutableRecordError, TalonStore
from .schemas import ApprovalDemoRequest, DatasetCreate, EvaluationCreate, TrainingCreate


def build_talon_router(store: TalonStore, orchestrator: TalonOrchestrator, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/drone", tags=["Talon simulation"])

    def not_found(kind: str) -> HTTPException:
        return HTTPException(status_code=404, detail={"code": f"{kind}_not_found", "message": f"{kind} was not found"})

    def no_store(value: dict[str, Any], *, status_code: int = 200) -> JSONResponse:
        return JSONResponse(value, status_code=status_code, headers={"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"})

    def require_local_origin(request: Request) -> None:
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise HTTPException(status_code=403, detail={"code": "local_request_required", "message": "Talon controls are available only on loopback"})
        if request.headers.get("origin", "").rstrip("/") not in dashboard_origins(settings.dashboard_origin):
            raise HTTPException(status_code=403, detail={"code": "origin_not_allowed", "message": "local control request origin is not allowed"})

    async def event_stream(scope_type: str, scope_id: str, after: int, request: Request) -> AsyncIterator[str]:
        last = after
        idle_ticks = 0
        while True:
            if await request.is_disconnected():
                break
            events = store.events_after(scope_type, scope_id, last)
            if events:
                idle_ticks = 0
                for event in events:
                    last = event.id
                    yield event.sse()
            else:
                idle_ticks += 1
                if idle_ticks % 40 == 0:
                    yield ": keep-alive\n\n"
            record = store.get(scope_id)
            if record and record.get("status") in TERMINAL_STATUSES and not events:
                break
            await asyncio.sleep(0.25)

    def replay_id(header: str | None, query: int) -> int:
        return int(header) if header and header.isdigit() else query

    @router.get("/health")
    async def health() -> dict[str, Any]:
        records, total = store.list(limit=200)
        completed_evaluations = sum(
            1 for record in records if record.get("kind") == "evaluation" and record.get("status") == "completed"
        )
        return {
            "status": "ok",
            "schema_version": store.schema_version,
            "simulation_only": True,
            "decision_support_only": True,
            "physical_response_controls": False,
            "human_approval_mandatory": True,
            "torch_available": importlib.util.find_spec("torch") is not None,
            "total_records": total,
            "active_records": sum(1 for record in records if record.get("status") not in TERMINAL_STATUSES),
            "completed_evaluations": completed_evaluations,
            "retention_days": settings.talon_retention_days,
        }

    @router.get("/policy")
    async def policy() -> dict[str, Any]:
        return {
            "policy_gate_version": POLICY_GATE_VERSION,
            "action_schema_version": ACTION_SCHEMA_VERSION,
            "actions": [action.value for action in DecisionAction],
            "policy_profiles": [profile.model_dump(mode="json") for profile in POLICY_PROFILES.values()],
            "constraints": {
                "simulation_only": True,
                "decision_support_only": True,
                "external_effect": False,
                "human_approval_mandatory": True,
                "physical_countermeasure_selection": False,
            },
        }

    @router.post("/policy/approval-demo")
    async def approval_demo(request: Request, payload: ApprovalDemoRequest) -> dict[str, Any]:
        """Exercise the real one-time approval authority without an evaluation."""

        require_local_origin(request)
        from drone_decision_ground.actions import DecisionRecommendation
        from drone_decision_ground.observation import PublicObservation
        from drone_decision_ground.policy_gate import PolicyGate
        from drone_decision_ground.scenarios import ScenarioConfig
        from drone_decision_verifier.approval import SimulatedApprovalAuthority
        from drone_decision_verifier.hidden_scenarios import build_environment

        authority = SimulatedApprovalAuthority()
        episode_id = "ep_" + "d" * 24
        approval = authority.issue(
            now_ms=1_000,
            ttl_ms=3_000,
            episode_id=episode_id,
            track_id="T-DEMO",
            requested_action=DecisionAction.RECOMMEND_AUTHORISED_MITIGATION,
            authority_profile="uk_monitor_and_escalate",
            authority_profile_version="2.0",
            approver_scope="simulated_incident_commander",
            state_revision=2,
        )
        arguments = {
            "approval_id": approval.approval_id,
            "episode_id": episode_id,
            "track_id": "T-DEMO",
            "requested_action": DecisionAction.RECOMMEND_AUTHORISED_MITIGATION,
            "authority_profile": "uk_monitor_and_escalate",
            "authority_profile_version": "2.0",
            "state_revision": 2,
            "now_ms": 2_000,
        }
        first = authority.consume(**arguments)
        replay = authority.consume(**arguments) if payload.mode == "replay" else None
        # The same response includes a real fail-closed gate decision over an
        # opaque public observation. No private scenario metadata is returned.
        config = ScenarioConfig(family_id="bird_false_positive", partition="evaluation")
        environment = build_environment(config)
        raw_observation, _ = environment.reset(seed=0, options={"scenario_config": config})
        observation = PublicObservation.model_validate(raw_observation)
        rejected = PolicyGate(POLICY_PROFILES["uk_monitor_and_escalate"]).evaluate(
            DecisionRecommendation(
                recommended_action=DecisionAction.RECOMMEND_AUTHORISED_MITIGATION,
                target_track_id=observation.track_id,
                valid_until_ms=observation.timestamp_ms + 1_000,
                action_confidence=0.9,
                threat_probability=0.9,
                uncertainty=0.1,
                missing_evidence=(),
                reason_codes=("gate_demo",),
            ),
            observation,
        )
        result = {
            "demo_version": "talon.public-approval-demo/1.0",
            "mode": payload.mode,
            "external_effect": False,
            "first_use": first.model_dump(mode="json"),
            "replay": replay.model_dump(mode="json") if replay else None,
            "gate_rejection": rejected.model_dump(mode="json"),
        }
        from drone_decision_verifier.leak_detection import assert_public_safe

        assert_public_safe(result)
        return result

    @router.get("/scenarios")
    async def scenarios() -> dict[str, Any]:
        items = list_public_capabilities()
        return {"items": items, "total": len(items)}

    @router.post("/datasets/generate", status_code=202)
    async def generate(
        request: Request,
        payload: DatasetCreate,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, Any]:
        require_local_origin(request)
        try:
            dataset_id = orchestrator.create_dataset(payload, idempotency_key=idempotency_key)
        except TalonIdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail={"code": "idempotency_conflict", "message": str(exc)}) from exc
        return {"dataset_id": dataset_id, "status": store.get(dataset_id)["status"]}

    @router.get("/datasets")
    async def datasets(limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> dict[str, Any]:
        records, total = store.list(kind="dataset", limit=limit, offset=offset)
        return {"items": [public_record_summary(record) for record in records], "total": total, "limit": limit, "offset": offset}

    @router.get("/datasets/{dataset_id}")
    async def dataset(dataset_id: str) -> JSONResponse:
        record = store.get(dataset_id)
        if record is None or record.get("kind") != "dataset":
            raise not_found("dataset")
        return no_store(public_record_detail(record))

    @router.post("/training-runs", status_code=202)
    async def create_training(
        request: Request,
        payload: TrainingCreate,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, Any]:
        require_local_origin(request)
        try:
            record_id = orchestrator.create_training(payload, idempotency_key=idempotency_key)
        except TalonIdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail={"code": "idempotency_conflict", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "training_unavailable", "message": str(exc)}) from exc
        return {"training_run_id": record_id, "status": store.get(record_id)["status"]}

    @router.get("/training-runs")
    async def training_runs(limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> dict[str, Any]:
        records, total = store.list(kind="training", limit=limit, offset=offset)
        return {"items": [public_record_summary(record) for record in records], "total": total, "limit": limit, "offset": offset}

    @router.get("/training-runs/{record_id}")
    async def training_run(record_id: str) -> JSONResponse:
        record = store.get(record_id)
        if record is None or record.get("kind") != "training":
            raise not_found("training_run")
        return no_store(public_record_detail(record))

    @router.post("/training-runs/{record_id}/cancel", status_code=202)
    async def cancel_training(request: Request, record_id: str) -> JSONResponse:
        require_local_origin(request)
        if not orchestrator.cancel(record_id):
            raise HTTPException(status_code=409, detail={"code": "not_cancellable", "message": "training run is not cancellable"})
        return no_store({"record_id": record_id, "status": "cancelling"}, status_code=202)

    @router.post("/datasets/{record_id}/cancel", status_code=202)
    async def cancel_dataset(request: Request, record_id: str) -> JSONResponse:
        require_local_origin(request)
        if not orchestrator.cancel(record_id):
            raise HTTPException(status_code=409, detail={"code": "not_cancellable", "message": "dataset job is not cancellable"})
        return no_store({"record_id": record_id, "status": "cancelling"}, status_code=202)

    @router.post("/evaluations", status_code=202)
    async def create_evaluation(
        request: Request,
        payload: EvaluationCreate,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, Any]:
        require_local_origin(request)
        try:
            record_id = orchestrator.create_evaluation(payload, idempotency_key=idempotency_key)
        except TalonIdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail={"code": "idempotency_conflict", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "evaluation_unavailable", "message": str(exc)}) from exc
        return {"evaluation_id": record_id, "status": store.get(record_id)["status"]}

    @router.get("/evaluations")
    async def evaluations(limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> dict[str, Any]:
        records, total = store.list(kind="evaluation", limit=limit, offset=offset)
        return {"items": [public_record_summary(record) for record in records], "total": total, "limit": limit, "offset": offset}

    @router.get("/evaluations/{record_id}")
    async def evaluation(record_id: str) -> JSONResponse:
        record = store.get(record_id)
        if record is None or record.get("kind") != "evaluation":
            raise not_found("evaluation")
        return no_store(public_record_detail(record))

    @router.post("/evaluations/{record_id}/cancel", status_code=202)
    async def cancel_evaluation(request: Request, record_id: str) -> JSONResponse:
        require_local_origin(request)
        if not orchestrator.cancel(record_id):
            raise HTTPException(status_code=409, detail={"code": "not_cancellable", "message": "evaluation is not cancellable"})
        return no_store({"record_id": record_id, "status": "cancelling"}, status_code=202)

    def events_response(request: Request, record_id: str, scope: str, last_event_id: str | None, after: int) -> StreamingResponse:
        if store.get(record_id) is None:
            raise not_found("record")
        return StreamingResponse(
            event_stream(scope, record_id, replay_id(last_event_id, after), request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Content-Type-Options": "nosniff"},
        )

    @router.get("/training-runs/{record_id}/events")
    async def training_events(request: Request, record_id: str, last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None, after: Annotated[int, Query(ge=0)] = 0) -> StreamingResponse:
        return events_response(request, record_id, "talon_training", last_event_id, after)

    @router.get("/evaluations/{record_id}/events")
    async def evaluation_events(request: Request, record_id: str, last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None, after: Annotated[int, Query(ge=0)] = 0) -> StreamingResponse:
        return events_response(request, record_id, "talon_evaluation", last_event_id, after)

    @router.get("/datasets/{record_id}/events")
    async def dataset_events(request: Request, record_id: str, last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None, after: Annotated[int, Query(ge=0)] = 0) -> StreamingResponse:
        return events_response(request, record_id, "talon_dataset", last_event_id, after)

    @router.get("/models")
    async def models() -> dict[str, Any]:
        records, _ = store.list(kind="training", limit=200)
        items = [public_record_summary(record) for record in records if record.get("status") == "completed"]
        return {"items": items, "total": len(items)}

    @router.get("/comparisons")
    async def comparisons() -> dict[str, Any]:
        records, _ = store.list(kind="evaluation", limit=200)
        return {"items": [{"evaluation_id": record["record_id"], "aggregate": record.get("aggregate"), "status": record.get("status")} for record in records]}

    @router.get("/exports/{record_id}.json")
    async def export(record_id: str) -> JSONResponse:
        record = store.get(record_id)
        if record is None:
            raise not_found("record")
        try:
            payload = public_evaluation_export(record)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "export_unavailable", "message": str(exc)}) from exc
        return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="{record_id}.json"', "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    @router.delete("/records/{record_id}", status_code=204)
    async def delete_record(request: Request, record_id: str) -> Response:
        require_local_origin(request)
        try:
            removed = store.delete_terminal(record_id)
        except TalonImmutableRecordError as exc:
            raise HTTPException(status_code=409, detail={"code": "record_referenced_or_active", "message": str(exc)}) from exc
        if not removed:
            raise not_found("record")
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    return router
