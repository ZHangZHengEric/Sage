from __future__ import annotations

import argparse
import sys
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.server_v2.api import register_routers
from app.server_v2.bootstrap import ServerHost
from app.server_v2.core.http import register_exception_handlers
from app.server_v2.core.lifecycle import ResourceRegistry
from app.server_v2.core.observability import (
    LoggingSettings,
    MetricsRegistry,
    RequestIdMiddleware,
    build_observability_router,
    init_logging,
)
from app.server_v2.core.settings import ServerSettings


def create_app(service: ServerHost) -> FastAPI:
    settings = service.settings
    database = service.database
    init_logging(
        LoggingSettings(
            level=settings.log_level,
            format=settings.log_format,
            directory=settings.log_directory,
        ),
        service_name="sage-server",
    )
    registry = ResourceRegistry(
        (database,) if database is not None else (),
        probe_timeout_seconds=1.0,
        stop_timeout_seconds=10.0,
    )
    metrics = MetricsRegistry("sage-server")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await registry.start()
        try:
            await service.start()
            yield
        finally:
            try:
                await service.close()
            finally:
                await registry.stop()

    app = FastAPI(
        title="Sage Server v2",
        version="0.1.0",
        lifespan=lifespan,
        description="Multi-user AG-UI host for sagents.v2.",
    )
    app.state.service = service
    app.state.resources = registry
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(build_observability_router(resources=registry, metrics=metrics))
    register_routers(app, jaeger=bool(settings.jaeger_url))
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sage Server v2")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-root", type=Path, default=None)
    args = parser.parse_args(argv)

    load_dotenv(Path(__file__).with_name(".env"), override=False)
    settings = ServerSettings.from_env(data_root=args.data_root)
    settings = replace(
        settings,
        host=args.host or settings.host,
        port=args.port or settings.port,
    )
    from app.server_v2.infrastructure.database import Database, DatabaseSettings

    database = Database(DatabaseSettings(url=settings.database_url()))
    service = ServerHost(settings, database=database)
    uvicorn.run(
        create_app(service),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
