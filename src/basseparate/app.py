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
from pathlib import Path

from fastapi import FastAPI, Request
from starlette.staticfiles import StaticFiles

from basseparate import API_VERSION
from basseparate.api.errors import ApiError, create_error_response
from basseparate.api.idempotency import IdempotencyStore
from basseparate.api.middleware import RequestTracingMiddleware
from basseparate.api.routes import router
from basseparate.api.security import SecurityMiddleware
from basseparate.config import AppConfig
from basseparate.storage import (
    ProjectRepository,
    initialize_database,
    initialize_storage_paths,
    resolve_storage_paths,
)

log = logging.getLogger(__name__)


def _static_dir() -> Path | None:
    """Locate the built frontend assets.

    Prefers package data (wheel install layout ``basseparate/web/static``)
    and falls back to the source tree ``frontend/dist`` for development.
    """
    package_static = Path(__file__).resolve().parent / "web" / "static"
    if (package_static / "index.html").is_file():
        return package_static
    source_static = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if (source_static / "index.html").is_file():
        return source_static
    return None


def create_app(config: AppConfig) -> FastAPI:
    """Build a FastAPI application from an explicit configuration.

    Safe to call multiple times for isolated test instances.
    """

    # Generate session token at creation time so middleware can use it.
    session_token = secrets.token_urlsafe(32)

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
        app.state.session_token = session_token
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
    app.state.session_token = session_token

    # Request tracing (outermost middleware).
    app.add_middleware(RequestTracingMiddleware)

    # Security: bearer auth, Host/Origin validation, rate limiting.
    app.add_middleware(SecurityMiddleware, session_token=session_token)

    # API error handler.
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> object:
        request_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(request, exc, request_id)

    # Routes.
    app.include_router(router)

    # Static frontend shell, served from the backend origin (M0.8).
    # Mounted after the API router so /api/* routes take precedence.
    static_dir = _static_dir()
    if static_dir is not None:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
