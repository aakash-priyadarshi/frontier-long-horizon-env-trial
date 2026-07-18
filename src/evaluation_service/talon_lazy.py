"""Lazy Talon ASGI component that cannot prevent Frontier startup."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .settings import dashboard_origins


class LazyTalonService:
    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.store: Any | None = None
        self.orchestrator: Any | None = None
        self.application: Any | None = None
        self.last_error_category: str | None = None
        self._lock: asyncio.Lock | None = None

    async def initialize(self) -> bool:
        if self.application is not None:
            return True
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self.application is not None:
                return True
            store = None
            try:
                # Optional Talon and Torch-facing modules are imported only here.
                from drone_training.api import build_talon_router
                from drone_training.orchestration import TalonOrchestrator
                from drone_training.persistence import TalonStore

                data_dir = self.settings.talon_data_dir or self.settings.data_dir / "talon"
                store = TalonStore(
                    self.settings.talon_database_path or data_dir / "talon.sqlite3",
                    event_replay_limit=self.settings.event_replay_limit,
                )
                store.mark_active_interrupted()
                if self.settings.talon_retention_days:
                    store.prune_expired(self.settings.talon_retention_days)
                orchestrator = TalonOrchestrator(store)
                application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
                application.add_middleware(
                    CORSMiddleware,
                    allow_origins=list(dashboard_origins(self.settings.dashboard_origin)),
                    allow_credentials=False,
                    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                    allow_headers=["Content-Type", "Last-Event-ID", "Idempotency-Key"],
                )
                application.include_router(build_talon_router(store, orchestrator, self.settings))
                self.store = store
                self.orchestrator = orchestrator
                self.application = application
                self.last_error_category = None
                return True
            except Exception:
                if store is not None:
                    try:
                        store.close()
                    except Exception:
                        pass
                self.store = None
                self.orchestrator = None
                self.application = None
                self.last_error_category = "talon_initialization_failed"
                return False

    async def dispatch(self, scope: Any, receive: Any, send: Any) -> None:
        if await self.initialize() and self.application is not None:
            await self.application(scope, receive, send)
            return
        payload = json.dumps(
            {
                "error": {
                    "code": "talon_service_unavailable",
                    "message": "the optional Talon component is temporarily unavailable",
                }
            },
            separators=(",", ":"),
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})

    async def close(self) -> None:
        if self.orchestrator is not None:
            await self.orchestrator.shutdown()
        if self.store is not None:
            self.store.close()
        self.application = None
        self.orchestrator = None
        self.store = None

    def component_health(self) -> dict[str, Any]:
        return {
            "status": "available" if self.application is not None else ("unavailable" if self.last_error_category else "not_initialized"),
            "error_category": self.last_error_category,
        }


class LazyTalonMiddleware:
    def __init__(self, app: Any, service: LazyTalonService) -> None:
        self.app = app
        self.service = service

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and str(scope.get("path", "")).startswith("/api/drone"):
            await self.service.dispatch(scope, receive, send)
            return
        await self.app(scope, receive, send)
