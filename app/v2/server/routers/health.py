from fastapi import APIRouter

from app.v2.server.routers.deps import HostDep
from app.v2.server.routers.schemas.common import ApiResponse, HealthPayload
from app.v2.server.routers.render import success

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResponse[HealthPayload])
@router.get("/active", response_model=ApiResponse[HealthPayload])
async def health(service: HostDep):
    ready = await service.ready()
    return success(
        {
            "status": "ok" if ready else "not_ready",
            "protocol": "ag-ui",
            "protocol_version": "0.1.19",
            "runtime": "sagents.v2",
            "trace_enabled": bool(service.settings.jaeger_url),
        }
    )
