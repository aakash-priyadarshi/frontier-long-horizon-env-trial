"""FastAPI application factory for the local evaluation service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from model_runners.registry import ProviderRegistry
from model_runners.configuration import RuntimeProviderSettings
from .api.routes import build_router
from .orchestration import EvaluationOrchestrator
from .persistence import EvaluationStore
from .settings import Settings, dashboard_origins
from .talon_lazy import LazyTalonMiddleware, LazyTalonService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    store = EvaluationStore(settings.database_path, event_replay_limit=settings.event_replay_limit)
    # Explicit production settings use the repository .env; injected test/local
    # settings remain isolated beneath their data directory.
    local_env_path = settings.local_env_path or settings.data_dir / ".env"
    provider_state_path = settings.provider_state_path or settings.data_dir / "provider-state.json"
    registry = ProviderRegistry(
        RuntimeProviderSettings(local_env_path=local_env_path),
        state_path=provider_state_path,
    )
    orchestrator = EvaluationOrchestrator(store, registry)
    talon_service = LazyTalonService(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store.mark_active_interrupted()
        yield
        await talon_service.close()
        store.close()

    app = FastAPI(
        title="Frontier Model Evaluation API", version="2.0.0",
        docs_url="/docs", redoc_url=None, lifespan=lifespan,
    )
    app.state.store = store
    app.state.orchestrator = orchestrator
    app.state.registry = registry
    app.state.talon_service = talon_service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(dashboard_origins(settings.dashboard_origin)),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Last-Event-ID", "Idempotency-Key"],
    )
    app.add_middleware(LazyTalonMiddleware, service=talon_service)

    @app.middleware("http")
    async def protect_local_control_responses(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        if request.method == "DELETE" or (
            request.url.path.startswith("/api/providers/") and request.method == "POST"
        ):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"location": ".".join(str(item) for item in error["loc"]), "message": error["msg"], "type": error["type"]} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "request validation failed", "details": errors}})

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "http_error", "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content={"error": detail}, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "the evaluation service could not complete the request"}})

    app.include_router(build_router(store, orchestrator, registry, settings))

    @app.get("/api/health/components")
    async def component_health() -> dict[str, object]:
        return {
            "status": "ok",
            "frontier": {"status": "available"},
            "talon": talon_service.component_health(),
        }

    return app


app = create_app()
