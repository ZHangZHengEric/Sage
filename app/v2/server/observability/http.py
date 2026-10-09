from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

from app.v2.server.observability.metrics import MetricsRegistry


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
        try:
            sink = service.application.service("observability.trace-sink")
        except (KeyError, RuntimeError):
            sink = None
        statistics = getattr(sink, "statistics", None)
        if statistics is not None:
            for name, value in statistics().items():
                metrics.set_gauge(f"trace_{name}", value)
        return PlainTextResponse(
            metrics.render_prometheus(),
            media_type="text/plain; version=0.0.4",
        )

    return router
