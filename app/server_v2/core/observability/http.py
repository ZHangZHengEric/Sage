from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

from app.server_v2.core.observability.metrics import MetricsRegistry


class ReadinessSnapshot(Protocol):
    @property
    def ready(self) -> bool: ...


class ReadinessProvider(Protocol):
    def readiness(self) -> Awaitable[ReadinessSnapshot]: ...


def build_observability_router(
    *,
    resources: ReadinessProvider,
    metrics: MetricsRegistry,
) -> APIRouter:
    router = APIRouter()

    @router.get("/livez", include_in_schema=False)
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/readyz", include_in_schema=False)
    async def ready() -> JSONResponse:
        report = await resources.readiness()
        return JSONResponse(
            status_code=200 if report.ready else 503,
            content={"status": "ok" if report.ready else "not_ready"},
        )

    @router.get("/metrics", include_in_schema=False)
    async def metric_snapshot() -> PlainTextResponse:
        return PlainTextResponse(
            metrics.render_prometheus(),
            media_type="text/plain; version=0.0.4",
        )

    return router
