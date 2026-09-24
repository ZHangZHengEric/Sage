from fastapi import APIRouter

from app.server_v2.routers.deps import ServiceDep, CurrentUser, PackageDep
from app.server_v2.runtime.official import official_tool_catalog
from app.server_v2.routers.render import success
from app.server_v2.routers.schemas.common import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.server_v2.routers.schemas.catalog import AgentBody, AgentPublic, ToolPublic

router = APIRouter(tags=["agents"], responses={**AUTH_ERRORS, **VALIDATION_ERRORS})


@router.get("/api/tools", response_model=ApiResponse[list[ToolPublic]])
async def list_tools(_: CurrentUser, packages: PackageDep):
    from sagents.v2.tool.plugins.agent_management import AgentManagementToolPlugin
    definitions = AgentManagementToolPlugin(packages).definitions
    return success([*official_tool_catalog(), *[
        dict(name=item.name, category="agent-management", source="host", default=False)
        for item in definitions]])


@router.get("/api/agents", response_model=ApiResponse[list[AgentPublic]])
async def list_agents(user: CurrentUser, service: ServiceDep):
    agents = (await service.catalog_store.get(user.user_id)).agents
    return success([item.public_dict() for item in agents])


@router.post("/api/agents", response_model=ApiResponse[AgentPublic])
async def create_agent(body: AgentBody, user: CurrentUser, service: ServiceDep):
    record = await service.catalog.create_agent(user.user_id, body.model_dump())
    return success(record.public_dict())


@router.get("/api/agents/{agent_id}", response_model=ApiResponse[AgentPublic])
async def get_agent(agent_id: str, user: CurrentUser, service: ServiceDep):
    return success(await service.catalog.get_agent(user.user_id, agent_id))


@router.put("/api/agents/{agent_id}", response_model=ApiResponse[AgentPublic])
async def update_agent(
    agent_id: str, body: AgentBody, user: CurrentUser, service: ServiceDep
):
    record = await service.catalog.update_agent(
        user.user_id, agent_id, body.model_dump()
    )
    return success(record.public_dict())


@router.delete("/api/agents/{agent_id}", response_model=ApiResponse[None])
async def remove_agent(agent_id: str, user: CurrentUser, service: ServiceDep):
    await service.catalog.delete_agent(user.user_id, agent_id)
    return success()
