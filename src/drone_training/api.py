"""Local-only safe public API routes for Talon simulation and training."""

from __future__ import annotations

import asyncio
import importlib.util
import json
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
from .external_llm_client import openai_compatible_readiness
from .external_llm_schemas import ExternalLLMEvaluationCreate
from .orchestration import TalonOrchestrator
from .persistence import TERMINAL_STATUSES, TalonIdempotencyConflict, TalonImmutableRecordError, TalonStore
from .replay import PublicEpisodeReplay, public_replay_export, verify_public_replay
from .schemas import ApprovalDemoRequest, ComparisonCreate, DatasetCreate, EvaluationCreate, OfflineRLTrainingCreate, TrainingCreate


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

    @router.post("/offline-rl/training-runs", status_code=202)
    async def create_offline_training(
        request: Request,
        payload: OfflineRLTrainingCreate,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, Any]:
        require_local_origin(request)
        try:
            record_id = orchestrator.create_offline_training(payload, idempotency_key=idempotency_key)
        except TalonIdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail={"code": "idempotency_conflict", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "offline_training_unavailable", "message": str(exc)}) from exc
        return {"training_run_id": record_id, "status": store.get(record_id)["status"], "algorithm": "discrete_cql"}

    @router.get("/offline-rl/training-runs")
    async def offline_training_runs(limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> dict[str, Any]:
        records, _ = store.list(kind="training", limit=200, offset=0)
        selected = [record for record in records if record.get("architecture") == "cql_gru" or record.get("algorithm") == "discrete_cql"]
        sliced = selected[offset:offset + limit]
        return {"items": [public_record_summary(record) for record in sliced], "total": len(selected), "limit": limit, "offset": offset}

    @router.get("/offline-rl/training-runs/{record_id}")
    async def offline_training_run(record_id: str) -> JSONResponse:
        record = store.get(record_id)
        if record is None or record.get("kind") != "training" or not (record.get("architecture") == "cql_gru" or record.get("algorithm") == "discrete_cql"):
            raise not_found("offline_training_run")
        return no_store(public_record_detail(record))

    @router.get("/offline-rl/training-runs/{record_id}/checkpoint")
    async def offline_training_checkpoint(record_id: str) -> JSONResponse:
        record = store.get(record_id)
        if record is None or record.get("kind") != "training" or record.get("status") != "completed" or not (record.get("architecture") == "cql_gru" or record.get("algorithm") == "discrete_cql"):
            raise not_found("offline_checkpoint")
        return no_store({
            "training_run_id": record_id,
            "schema_version": record.get("checkpoint_schema_version"),
            "checkpoint_digest": record.get("checkpoint_digest"),
            "artifact_identity": record.get("artifact_identity"),
            "checkpoint_unavailable": bool(record.get("checkpoint_unavailable")),
            "dataset_digest": record.get("offline_dataset_digest"),
            "source_dataset_digest": record.get("dataset_digest"),
            "architecture": record.get("architecture"),
            "algorithm": record.get("algorithm"),
            "action_schema_version": record.get("action_schema_version"),
            "feature_schema": record.get("feature_schema"),
        })

    @router.post("/offline-rl/training-runs/{record_id}/cancel", status_code=202)
    async def cancel_offline_training(request: Request, record_id: str) -> JSONResponse:
        require_local_origin(request)
        if not orchestrator.cancel(record_id):
            raise HTTPException(status_code=409, detail={"code": "not_cancellable", "message": "offline training run is not cancellable"})
        return no_store({"record_id": record_id, "status": "cancelling"}, status_code=202)

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

    @router.post("/offline-rl/evaluations", status_code=202)
    async def create_offline_evaluation(
        request: Request,
        payload: EvaluationCreate,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, Any]:
        require_local_origin(request)
        training = store.get(payload.training_run_id)
        if training is None or not (training.get("architecture") == "cql_gru" or training.get("algorithm") == "discrete_cql"):
            raise HTTPException(status_code=409, detail={"code": "offline_checkpoint_required", "message": "a completed discrete CQL checkpoint is required"})
        try:
            record_id = orchestrator.create_evaluation(payload, idempotency_key=idempotency_key)
        except (TalonIdempotencyConflict, ValueError) as exc:
            raise HTTPException(status_code=409, detail={"code": "offline_evaluation_unavailable", "message": str(exc)}) from exc
        return {"evaluation_id": record_id, "status": store.get(record_id)["status"], "algorithm": "discrete_cql"}

    @router.get("/external-llm/readiness")
    async def external_llm_readiness() -> dict[str, Any]:
        return openai_compatible_readiness()

    @router.post("/external-llm/evaluations", status_code=202)
    async def create_external_llm_evaluation(
        request: Request,
        payload: ExternalLLMEvaluationCreate,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, Any]:
        require_local_origin(request)
        try:
            record_id = orchestrator.create_external_llm_evaluation(payload, idempotency_key=idempotency_key)
        except TalonIdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail={"code": "idempotency_conflict", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "external_evaluation_unavailable", "message": str(exc)}) from exc
        record = store.get(record_id)
        return {
            "evaluation_id": record_id,
            "status": record["status"],
            "policy_kind": payload.policy_kind,
            "provider": payload.provider,
            "simulation_only": True,
        }

    @router.get("/offline-rl/evaluations")
    async def offline_evaluations(limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> dict[str, Any]:
        records, _ = store.list(kind="evaluation", limit=200, offset=0)
        selected = [record for record in records if record.get("algorithm") == "discrete_cql"]
        sliced = selected[offset:offset + limit]
        return {"items": [public_record_summary(record) for record in sliced], "total": len(selected), "limit": limit, "offset": offset}

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

    @router.get("/offline-rl/training-runs/{record_id}/events")
    async def offline_training_events(request: Request, record_id: str, last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None, after: Annotated[int, Query(ge=0)] = 0) -> StreamingResponse:
        return events_response(request, record_id, "talon_training", last_event_id, after)

    @router.get("/evaluations/{record_id}/events")
    async def evaluation_events(request: Request, record_id: str, last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None, after: Annotated[int, Query(ge=0)] = 0) -> StreamingResponse:
        return events_response(request, record_id, "talon_evaluation", last_event_id, after)

    @router.get("/offline-rl/evaluations/{record_id}/events")
    async def offline_evaluation_events(request: Request, record_id: str, last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None, after: Annotated[int, Query(ge=0)] = 0) -> StreamingResponse:
        return events_response(request, record_id, "talon_evaluation", last_event_id, after)

    def find_replay(episode_id: str) -> PublicEpisodeReplay:
        offset = 0
        while True:
            records, total = store.list(kind="evaluation", limit=200, offset=offset)
            for record in records:
                if record.get("status") != "completed":
                    continue
                for episode in record.get("episodes", []):
                    result = episode.get("result", {})
                    if result.get("episode_id") == episode_id and isinstance(episode.get("replay"), dict):
                        return verify_public_replay(PublicEpisodeReplay.model_validate(episode["replay"]))
            offset += len(records)
            if not records or offset >= total:
                break
        raise not_found("episode_replay")

    @router.get("/episodes/{episode_id}/replay")
    async def episode_replay(episode_id: str) -> JSONResponse:
        return no_store(public_replay_export(find_replay(episode_id)))

    @router.get("/episodes/{episode_id}/replay/export.json")
    async def episode_replay_export(episode_id: str) -> JSONResponse:
        payload = public_replay_export(find_replay(episode_id))
        return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="{episode_id}-replay.json"', "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    @router.get("/episodes/{episode_id}/replay/events")
    async def episode_replay_events(episode_id: str, after: Annotated[int, Query(ge=0)] = 0) -> StreamingResponse:
        replay = find_replay(episode_id)

        async def replay_stream() -> AsyncIterator[str]:
            import json

            for step in replay.steps:
                if step.sequence <= after:
                    continue
                data = json.dumps({"replay_id": replay.replay_id, "step": step.model_dump(mode="json")}, sort_keys=True, separators=(",", ":"))
                yield f"id: {step.sequence}\nevent: replay_step\ndata: {data}\n\n"
            terminal = json.dumps({"replay_id": replay.replay_id, "replay_digest": replay.replay_digest}, sort_keys=True, separators=(",", ":"))
            yield f"id: {len(replay.steps) + 1}\nevent: terminal\ndata: {terminal}\n\n"

        return StreamingResponse(replay_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Content-Type-Options": "nosniff"})

    @router.get("/datasets/{record_id}/events")
    async def dataset_events(request: Request, record_id: str, last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None, after: Annotated[int, Query(ge=0)] = 0) -> StreamingResponse:
        return events_response(request, record_id, "talon_dataset", last_event_id, after)

    @router.get("/models")
    async def models() -> dict[str, Any]:
        records, _ = store.list(kind="training", limit=200)
        items = [public_record_summary(record) for record in records if record.get("status") == "completed"]
        return {"items": items, "total": len(items)}

    @router.get("/comparisons")
    async def comparisons(limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> dict[str, Any]:
        records, total = store.list(kind="comparison", limit=limit, offset=offset)
        return {"items": [public_record_summary(record) for record in records], "total": total, "limit": limit, "offset": offset}

    @router.post("/comparisons", status_code=201)
    async def create_comparison(
        request: Request,
        payload: ComparisonCreate,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        require_local_origin(request)
        configuration = payload.model_dump(mode="json")
        existing = store.resolve_idempotency("comparison", idempotency_key, configuration)
        if existing is not None:
            record = store.get(existing)
            if record is None:
                raise HTTPException(status_code=409, detail={"code": "comparison_unavailable", "message": "comparison record is unavailable"})
            return no_store(public_record_detail(record), status_code=200)
        records = []
        domains = []
        versions = []
        for evaluation_id in payload.evaluation_ids:
            record = store.get(evaluation_id)
            if record is None or record.get("kind") != "evaluation" or record.get("status") != "completed":
                raise HTTPException(status_code=409, detail={"code": "completed_evaluation_required", "message": "all comparison inputs must be completed evaluations"})
            private_path = store._private_directory(evaluation_id) / "verification.json"
            try:
                private = json.loads(private_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=409, detail={"code": "comparison_private_binding_unavailable", "message": "evaluation domain binding is unavailable"}) from exc
            episode_domains = []
            action_schemas = []
            for episode in private.get("episodes", []):
                manifest = episode.get("manifest", {})
                digest = manifest.get("evaluation_instance_digest")
                if digest is None:
                    values = manifest.get("evaluation_instance_digests", [])
                    digest = values[0] if values else None
                episode_domains.append(digest)
                action_schemas.append(manifest.get("action_schema_version") or ACTION_SCHEMA_VERSION)
            domains.append(tuple(episode_domains))
            if any(schema != action_schemas[0] for schema in action_schemas[1:]):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "comparison_schema_or_domain_mismatch",
                        "message": "evaluations must use the same action schema",
                    },
                )
            if records and action_schemas and action_schemas[0] != ACTION_SCHEMA_VERSION:
                # Allow historical records that omitted the field only when empty;
                # when present they must match the runtime contract.
                pass
            public_episodes = record.get("episodes", [])
            versions.append(tuple((item.get("environment_version"), item.get("verifier_version")) for item in public_episodes))
            records.append(record)
        if any(domain != domains[0] for domain in domains[1:]) or any(version != versions[0] for version in versions[1:]):
            raise HTTPException(status_code=409, detail={"code": "comparison_schema_or_domain_mismatch", "message": "evaluations must use the same deterministic scenario domain and compatible runtime versions"})
        models = []
        for item in records:
            models.append(
                {
                    "evaluation_id": item["record_id"],
                    "model_id": item.get("model_id"),
                    "algorithm": item.get("algorithm", "behaviour_cloning"),
                    "policy_kind": item.get("policy_kind") or item.get("configuration", {}).get("policy_kind") or item.get("algorithm"),
                    "provider": item.get("provider") or item.get("configuration", {}).get("provider"),
                    "model": item.get("model") or item.get("configuration", {}).get("model"),
                }
            )
        results = [{"evaluation_id": item["record_id"], "aggregate": item.get("aggregate", {})} for item in records]
        episode_count = len(records[0].get("episodes", []))
        aligned_instances = []
        for index in range(episode_count):
            outcomes = []
            for item in records:
                episodes = item.get("episodes", [])
                if index >= len(episodes):
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "comparison_schema_or_domain_mismatch",
                            "message": "evaluations must use the same deterministic scenario domain and compatible runtime versions",
                        },
                    )
                result = episodes[index].get("result", {})
                outcomes.append(
                    {
                        "evaluation_id": item["record_id"],
                        "model_id": item.get("model_id"),
                        "algorithm": item.get("algorithm", "behaviour_cloning"),
                        "policy_kind": item.get("policy_kind") or item.get("configuration", {}).get("policy_kind"),
                        "episode_id": result.get("episode_id"),
                        "strict_success": bool(result.get("strict_success")),
                        "score": result.get("score"),
                        "safety_violation_count": int(result.get("safety_violation_count") or 0),
                        "verdict": result.get("verdict"),
                    }
                )
            aligned_instances.append({"instance_index": index + 1, "outcomes": outcomes})
        comparison_id, created = orchestrator.create_completed_comparison(
            configuration=configuration,
            payload={
            "schema_version": "talon.public-model-comparison/1.0", "application_commit": records[0].get("application_commit"),
            "models": models, "compatibility": {"domain_compatible": True, "runtime_versions_compatible": True},
            },
            results={"results": results, "aligned_instances": aligned_instances},
            depends_on=tuple(payload.evaluation_ids),
            idempotency_key=idempotency_key,
        )
        record = store.get(comparison_id)
        if record is None:
            raise HTTPException(status_code=409, detail={"code": "comparison_unavailable", "message": "comparison record is unavailable"})
        return no_store(public_record_detail(record), status_code=201 if created else 200)

    @router.get("/comparisons/{comparison_id}")
    async def comparison(comparison_id: str) -> JSONResponse:
        record = store.get(comparison_id)
        if record is None or record.get("kind") != "comparison":
            raise not_found("comparison")
        return no_store(public_record_detail(record))

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
