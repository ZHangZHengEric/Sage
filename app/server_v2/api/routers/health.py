from fastapi import APIRouter, Request

from app.server_v2.api.deps import ServiceDep
from app.server_v2.schemas import ApiResponse, HealthPayload
from app.server_v2.core.errors import success

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResponse[HealthPayload])
@router.get("/active", response_model=ApiResponse[HealthPayload])
async def health(request: Request, service: ServiceDep):
    report = None
    registry = getattr(request.app.state, "resources", None)
    if registry is not None:
        report = await registry.readiness()
    ready = True if report is None else report.ready
    return success(
        {
            "status": "ok" if ready else "not_ready",
            "protocol": "ag-ui",
            "protocol_version": "0.1.19",
            "runtime": "sagents.v2",
            "backends": service.backends(),
        }
    )
