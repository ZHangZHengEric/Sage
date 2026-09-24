from fastapi import APIRouter

from app.server_v2.routers.deps import ServiceDep, CurrentUser
from app.server_v2.routers.schemas.common import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.server_v2.routers.schemas.catalog import McpBody, McpPublic
from app.server_v2.routers.render import success

router = APIRouter(tags=["mcp"], responses={**AUTH_ERRORS, **VALIDATION_ERRORS})


@router.get("/api/mcp", response_model=ApiResponse[list[McpPublic]])
async def list_mcp(user: CurrentUser, service: ServiceDep):
    servers = (await service.catalog_store.get(user.user_id)).mcp_servers
    return success([item.public_dict() for item in servers])


@router.post("/api/mcp", response_model=ApiResponse[McpPublic])
async def create_mcp(body: McpBody, user: CurrentUser, service: ServiceDep):
    record = await service.catalog.create_mcp(user.user_id, body.model_dump())
    return success(record.public_dict())


@router.put("/api/mcp/{name}", response_model=ApiResponse[McpPublic])
async def update_mcp(name: str, body: McpBody, user: CurrentUser, service: ServiceDep):
    record = await service.catalog.update_mcp(user.user_id, name, body.model_dump())
    return success(record.public_dict())


@router.delete("/api/mcp/{name}", response_model=ApiResponse[None])
async def remove_mcp(name: str, user: CurrentUser, service: ServiceDep):
    await service.catalog.delete_mcp(user.user_id, name)
    return success()


@router.post("/api/mcp/{name}/refresh", response_model=ApiResponse[McpPublic])
async def refresh_mcp(name: str, user: CurrentUser, service: ServiceDep):
    record = await service.catalog.refresh_mcp(user.user_id, name)
    return success(record.public_dict())
