"""Application factory: settings, stores, routes and the built UI.

The server is deliberately thin: all domain rules live in ``media``,
``projects``, ``peaks`` and ``jobs``; the API package only parses requests and
maps errors. Importing this module must never pull in torch, demucs or the
analysis virtual environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from basseparate import __version__, stems
from basseparate.api import export_routes, import_routes, job_routes, project_routes
from basseparate.api.errors import install_error_handlers
from basseparate.api.import_routes import register_import_job
from basseparate.config import Settings
from basseparate.jobs import JobManager
from basseparate.projects import ProjectStore

LOCAL_UI_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")

UI_PLACEHOLDER = """<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>basseparate</title></head>
  <body>
    <main style="font-family: system-ui, sans-serif; margin: 3rem">
      <h1>basseparate</h1>
      <p>The API is running, but the web UI has not been built yet.</p>
      <p>Run <code>make build</code>, then reload this page.</p>
      <p>Health: <a href="/api/health">/api/health</a></p>
    </main>
  </body>
</html>
"""


def mount_ui(app: FastAPI, web_dir: Path) -> None:
    """Serve the Vite build when it exists; otherwise explain how to build it."""
    web_dir = Path(web_dir)
    if (web_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="ui")
        return

    @app.get("/", include_in_schema=False)
    def ui_placeholder() -> HTMLResponse:
        return HTMLResponse(UI_PLACEHOLDER)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    paths = settings.data_paths.ensure()
    store = ProjectStore(paths.projects)
    jobs = JobManager()
    register_import_job(jobs, settings=settings, paths=paths, store=store)

    app = FastAPI(
        title="basseparate",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.paths = paths
    app.state.projects = store
    app.state.jobs = jobs

    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(LOCAL_UI_ORIGINS),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "data_root": str(paths.root),
            "ui": (Path(settings.web_dir) / "index.html").is_file(),
        }

    @app.get("/api/capabilities", tags=["meta"])
    def capabilities() -> dict[str, Any]:
        from basseparate.peaks import PEAK_BUCKET_SIZES

        return {
            "sample_rates": [44_100, 48_000, 88_200, 96_000],
            "default_sample_rate": settings.sample_rate,
            "peak_bucket_sizes": list(PEAK_BUCKET_SIZES),
            "max_upload_bytes": settings.max_upload_bytes,
            "channels": [1, 2],
            "pcm_format": "f32le interleaved",
        }

    app.include_router(import_routes.router, prefix="/api")
    app.include_router(project_routes.router, prefix="/api")
    app.include_router(job_routes.router, prefix="/api")
    app.include_router(export_routes.router, prefix="/api")
    # The literal /doctor alias requested by the task and an operator-friendly
    # URL for the UI.
    app.include_router(export_routes.alias_router)
    stems.install(app)
    mount_ui(app, settings.web_dir)
    return app


__all__ = ["create_app", "mount_ui"]
