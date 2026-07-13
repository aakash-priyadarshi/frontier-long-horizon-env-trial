"""FastAPI application factory for the local evaluation service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from model_runners.registry import ProviderRegistry

from .api.routes import build_router
from .orchestration import EvaluationOrchestrator
from .persistence import EvaluationStore
from .settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    store = EvaluationStore(settings.database_path, event_replay_limit=settings.event_replay_limit)
    registry = ProviderRegistry()
    orchestrator = EvaluationOrchestrator(store, registry)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store.mark_active_interrupted()
        yield
        store.close()

    app = FastAPI(
        title="Frontier Model Evaluation API", version="2.0.0",
        docs_url="/docs", redoc_url=None, lifespan=lifespan,
    )
    app.state.store = store
    app.state.orchestrator = orchestrator
    app.state.registry = registry
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.dashboard_origin, "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

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

    app.include_router(build_router(store, orchestrator, registry))
    return app


app = create_app()
