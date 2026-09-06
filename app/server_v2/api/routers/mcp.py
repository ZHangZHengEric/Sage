from fastapi import APIRouter

from app.server_v2.api.deps import CurrentUser, ServiceDep
from app.server_v2.core.errors import ServerV2Error, success
from app.server_v2.domain.catalog import delete_mcp, upsert_mcp
from app.server_v2.schemas import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.server_v2.schemas.http import McpBody, McpPublic
from app.server_v2.services.mcp import discover_mcp_tools, to_mcp_config

router = APIRouter(tags=["mcp"], responses={**AUTH_ERRORS, **VALIDATION_ERRORS})


@router.get("/api/mcp", response_model=ApiResponse[list[McpPublic]])
async def list_mcp(user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    return success([item.public_dict() for item in catalog.mcp_servers])


@router.post("/api/mcp", response_model=ApiResponse[McpPublic])
async def create_mcp(body: McpBody, user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    record, catalog = upsert_mcp(catalog, body.model_dump())
    await service.catalog.save(user.user_id, catalog)
    return success(record.public_dict())


@router.put("/api/mcp/{name}", response_model=ApiResponse[McpPublic])
async def update_mcp(name: str, body: McpBody, user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    payload = body.model_dump()
    payload["name"] = name
    record, catalog = upsert_mcp(catalog, payload)
    await service.catalog.save(user.user_id, catalog)
    return success(record.public_dict())


@router.delete("/api/mcp/{name}", response_model=ApiResponse[None])
async def remove_mcp(name: str, user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    await service.catalog.save(user.user_id, delete_mcp(catalog, name))
    return success()


@router.post("/api/mcp/{name}/refresh", response_model=ApiResponse[McpPublic])
async def refresh_mcp(name: str, user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    current = next((item for item in catalog.mcp_servers if item.name == name), None)
    if current is None:
        raise ServerV2Error("not_found", "mcp server not found")
    tools = await discover_mcp_tools(to_mcp_config(current))
    record, catalog = upsert_mcp(
        catalog,
        {
            **current.public_dict(),
            "api_key": (
                current.api_key.get_secret_value() if current.api_key is not None else ""
            ),
            "tools": tools,
        },
    )
    await service.catalog.save(user.user_id, catalog)
    return success(record.public_dict())
