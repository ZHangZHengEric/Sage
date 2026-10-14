from fastapi import APIRouter

from app.v2.server.routers.deps import ReadUser, CatalogDep, CurrentUser, PackageDep
from app.v2.server.runtime.official import official_tool_catalog
from app.v2.server.routers.render import success
from app.v2.server.routers.schemas.common import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.v2.server.routers.schemas.catalog import AgentBody, AgentPublic, ToolPublic

router = APIRouter(tags=["agents"], responses={**AUTH_ERRORS, **VALIDATION_ERRORS})


@router.get("/api/tools", response_model=ApiResponse[list[ToolPublic]])
async def list_tools(user: CurrentUser, packages: PackageDep, service: CatalogDep):
    from sagents.v2.tool.plugins.agent_management import AgentManagementToolPlugin
    definitions = AgentManagementToolPlugin(packages).definitions
    catalog = await service.get(user.user_id)
    plugin = service.mcp_plugins.get(user.user_id, catalog.mcp_servers)
    external = await plugin.list_tools(run_id="catalog") if plugin is not None else ()
    return success([*official_tool_catalog(), *[
        dict(name=item.name, approval_key=item.approval_key, category="MCP", source="mcp", default=False)
        for item in external], *[
        dict(name=item.name, category="agent-management", source="host", default=False)
        for item in definitions]])


@router.get("/api/agents", response_model=ApiResponse[list[AgentPublic]])
async def list_agents(user: ReadUser, service: CatalogDep):
    agents = (await service.get(user.user_id)).agents
    return success([item.public_dict() for item in agents])


@router.post("/api/agents", response_model=ApiResponse[AgentPublic])
async def create_agent(body: AgentBody, user: CurrentUser, service: CatalogDep):
    record = await service.create_agent(user.user_id, body.model_dump(exclude={"tool_approval"} if "tool_approval" not in body.model_fields_set else set()))
    return success(record.public_dict())


@router.get("/api/agents/{agent_id}", response_model=ApiResponse[AgentPublic])
async def get_agent(agent_id: str, user: ReadUser, service: CatalogDep):
    return success(await service.get_agent(user.user_id, agent_id))


@router.put("/api/agents/{agent_id}", response_model=ApiResponse[AgentPublic])
async def update_agent(
    agent_id: str, body: AgentBody, user: CurrentUser, service: CatalogDep
):
    record = await service.update_agent(
        user.user_id, agent_id, body.model_dump(exclude={"tool_approval"} if "tool_approval" not in body.model_fields_set else set())
    )
    return success(record.public_dict())


@router.delete("/api/agents/{agent_id}", response_model=ApiResponse[None])
async def remove_agent(agent_id: str, user: CurrentUser, service: CatalogDep):
    await service.delete_agent(user.user_id, agent_id)
    return success()
