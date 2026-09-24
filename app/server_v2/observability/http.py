from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

from app.server_v2.observability.metrics import MetricsRegistry


def build_observability_router(
    *,
    service,
    metrics: MetricsRegistry,
) -> APIRouter:
    router = APIRouter()

    @router.get("/livez", include_in_schema=False)
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/readyz", include_in_schema=False)
    async def ready() -> JSONResponse:
        ready = await service.ready()
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ok" if ready else "not_ready"},
        )

    @router.get("/metrics", include_in_schema=False)
    async def metric_snapshot() -> PlainTextResponse:
        return PlainTextResponse(
            metrics.render_prometheus(),
            media_type="text/plain; version=0.0.4",
        )

    return router
