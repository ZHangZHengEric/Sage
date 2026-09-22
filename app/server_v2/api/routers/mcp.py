from app.server_v2.services.catalog_transactions import catalog_transaction
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
@catalog_transaction
async def create_mcp(body: McpBody, user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    record, catalog = upsert_mcp(catalog, body.model_dump())
    await service.catalog.save(user.user_id, catalog)
    return success(record.public_dict())


@router.put("/api/mcp/{name}", response_model=ApiResponse[McpPublic])
@catalog_transaction
async def update_mcp(name: str, body: McpBody, user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    payload = body.model_dump()
    payload["name"] = name
    record, catalog = upsert_mcp(catalog, payload)
    await service.catalog.save(user.user_id, catalog)
    return success(record.public_dict())


@router.delete("/api/mcp/{name}", response_model=ApiResponse[None])
@catalog_transaction
async def remove_mcp(name: str, user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    await service.catalog.save(user.user_id, delete_mcp(catalog, name))
    return success()


@router.post("/api/mcp/{name}/refresh", response_model=ApiResponse[McpPublic])
@catalog_transaction
async def refresh_mcp(name: str, user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    current = next((item for item in catalog.mcp_servers if item.name == name), None)
    if current is None:
        raise ServerV2Error("not_found", "mcp server not found")
    tools = await discover_mcp_tools(to_mcp_config(current))
    record = current.model_copy(update={"tools": list(dict.fromkeys(tools))})
    catalog.mcp_servers = [
        record if item.name == name else item for item in catalog.mcp_servers
    ]
    await service.catalog.save(user.user_id, catalog)
    # Refresh is the only verb that asks for rediscovery without changing the
    # transport, so the cached plugin would otherwise keep serving the Tools it
    # saw the first time — including an empty list from a server that was down.
    service.mcp_plugins.invalidate(user.user_id)
    return success(record.public_dict())
