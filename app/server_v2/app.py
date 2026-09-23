from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.server_v2.api import register_routers
from app.server_v2.core.fastapi import install_core_exception_handlers
from app.server_v2.core.lifecycle import ResourceRegistry
from app.server_v2.core.observability import (
    LoggingSettings,
    MetricsRegistry,
    RequestIdMiddleware,
    build_observability_router,
    init_logging,
)
from app.server_v2.core.settings import ServerV2Settings
from app.server_v2.services.runtime import ServerV2Service

WEB_DIST = Path(__file__).resolve().parent / "web" / "dist"
SERVICE_NAME = "sage-server"
_LOGGING_READY = False
_LOGGING_SIGNATURE: tuple[str, str, str | None] | None = None


def _ensure_logging(settings: ServerV2Settings) -> None:
    global _LOGGING_READY, _LOGGING_SIGNATURE
    signature = (settings.log_level, settings.log_format, settings.log_directory)
    if _LOGGING_READY and _LOGGING_SIGNATURE == signature:
        return
    init_logging(
        LoggingSettings(
            level=settings.log_level,
            format=settings.log_format,
            directory=settings.log_directory,
        ),
        service_name=SERVICE_NAME,
    )
    _LOGGING_READY = True
    _LOGGING_SIGNATURE = signature


def required_resources(settings: ServerV2Settings):
    url = settings.database_url()
    if not url:
        raise ValueError("SAGE_SERVER_MYSQL_URL is required")
    from app.server_v2.core.database import Database, DatabaseSettings

    return (Database(DatabaseSettings(url=url)),)


def create_app(
    service: ServerV2Service | None = None,
    settings: ServerV2Settings | None = None,
) -> FastAPI:
    if service is not None:
        runtime = service
        settings = service.settings
        database = service.database
    else:
        settings = settings or ServerV2Settings.from_env()
        (database,) = required_resources(settings)
        runtime = ServerV2Service(settings, database=database)
    _ensure_logging(settings)
    resources = tuple(item for item in (database,) if item is not None)
    registry = ResourceRegistry(
        resources,
        probe_timeout_seconds=1.0,
        stop_timeout_seconds=10.0,
    )
    metrics = MetricsRegistry(SERVICE_NAME)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = runtime
        app.state.resources = registry
        await registry.start()
        try:
            await runtime.start()
            yield
        finally:
            try:
                await runtime.close()
            finally:
                await registry.stop()

    app = FastAPI(
        title="Sage Server v2",
        version="0.1.0",
        lifespan=lifespan,
        description="Multi-user AG-UI host for sagents.v2.",
    )
    app.state.service = runtime
    app.state.resources = registry
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)
    install_core_exception_handlers(app)
    app.include_router(build_observability_router(resources=registry, metrics=metrics))
    register_routers(app, jaeger=bool(runtime.settings.jaeger_url))
    _mount_spa(app)
    return app


def _mount_spa(app: FastAPI) -> None:
    if not WEB_DIST.is_dir():
        return
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    # Prefixes owned by the backend. A machine protocol swallowed by the SPA
    # fallback answers 200 with HTML instead of 404, which a client reports as
    # an unparseable response rather than a missing route.
    reserved = ("api/", "a2a/", ".well-known/")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        root = WEB_DIST.resolve()
        candidate = (root / full_path).resolve()
        if not candidate.is_relative_to(root) or full_path.startswith(reserved):
            raise HTTPException(status_code=404, detail="not found")
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(root / "index.html")
