from fastapi import APIRouter

from app.server_v2.api.deps import CurrentUser, ServiceDep
from app.server_v2.core.errors import success
from app.server_v2.domain.catalog import delete_agent, require_agent, upsert_agent
from app.server_v2.schemas import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.server_v2.schemas.http import AgentBody, AgentPublic

router = APIRouter(tags=["agents"], responses={**AUTH_ERRORS, **VALIDATION_ERRORS})


@router.get("/api/agents", response_model=ApiResponse[list[AgentPublic]])
async def list_agents(user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    return success([item.public_dict() for item in catalog.agents])


@router.post("/api/agents", response_model=ApiResponse[AgentPublic])
async def create_agent(body: AgentBody, user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    record, catalog = upsert_agent(catalog, body.model_dump())
    await service.catalog.save(user.user_id, catalog)
    return success(record.public_dict())


@router.get("/api/agents/{agent_id}", response_model=ApiResponse[AgentPublic])
async def get_agent(agent_id: str, user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    record = require_agent(catalog, agent_id)
    payload = record.public_dict()
    payload["skills"] = list(
        await service.skill_catalog.bound_names(user.user_id, agent_id)
    )
    return success(payload)


@router.put("/api/agents/{agent_id}", response_model=ApiResponse[AgentPublic])
async def update_agent(
    agent_id: str, body: AgentBody, user: CurrentUser, service: ServiceDep
):
    catalog = await service.catalog.get(user.user_id)
    require_agent(catalog, agent_id)
    payload = body.model_dump()
    payload["id"] = agent_id
    record, catalog = upsert_agent(catalog, payload)
    await service.catalog.save(user.user_id, catalog)
    return success(record.public_dict())


@router.delete("/api/agents/{agent_id}", response_model=ApiResponse[None])
async def remove_agent(agent_id: str, user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    await service.catalog.save(user.user_id, delete_agent(catalog, agent_id))
    return success()
