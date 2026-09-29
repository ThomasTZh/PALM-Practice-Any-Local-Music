"""Application factory and lifecycle (M0.6).

``create_app(config)`` builds a FastAPI instance with:
- Lifespan-managed startup/shutdown.
- Storage initialization.
- Database initialization and migration.
- Session token creation.
- Request tracing middleware.
- API routes.

No filesystem mutations, background workers, browser opens, or network
requests occur at module import time.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from basseparate import API_VERSION
from basseparate.api.errors import ApiError, create_error_response
from basseparate.api.idempotency import IdempotencyStore
from basseparate.api.middleware import RequestTracingMiddleware
from basseparate.api.routes import router
from basseparate.config import AppConfig
from basseparate.storage import (
    ProjectRepository,
    initialize_database,
    initialize_storage_paths,
    resolve_storage_paths,
)

log = logging.getLogger(__name__)


def create_app(config: AppConfig) -> FastAPI:
    """Build a FastAPI application from an explicit configuration.

    Safe to call multiple times for isolated test instances.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # --- Startup ---
        paths = resolve_storage_paths(config.storage_root)
        initialize_storage_paths(paths)
        initialize_database(paths.database_path)

        app.state.config = config
        app.state.storage_paths = paths
        app.state.repository = ProjectRepository(paths.database_path)
        app.state.idempotency_store = IdempotencyStore()
        app.state.session_token = secrets.token_urlsafe(32)
        app.state.ready = True
        log.info("basseparate service ready (api v%d)", API_VERSION)

        yield

        # --- Shutdown ---
        app.state.ready = False
        app.state.idempotency_store.clear()
        log.info("basseparate service stopped")

    app = FastAPI(
        title="basseparate",
        version=str(API_VERSION),
        lifespan=lifespan,
    )

    # Request tracing (outermost middleware).
    app.add_middleware(RequestTracingMiddleware)

    # API error handler.
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> object:
        request_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(request, exc, request_id)

    # Routes.
    app.include_router(router)

    return app
