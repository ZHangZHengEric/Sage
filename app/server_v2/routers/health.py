from fastapi import APIRouter

from app.server_v2.routers.deps import ServiceDep
from app.server_v2.routers.schemas.common import ApiResponse, HealthPayload
from app.server_v2.routers.render import success

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResponse[HealthPayload])
@router.get("/active", response_model=ApiResponse[HealthPayload])
async def health(service: ServiceDep):
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
