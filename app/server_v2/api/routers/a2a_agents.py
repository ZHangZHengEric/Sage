"""CRUD for the remote A2A agents a tenant may delegate to.

This is the outbound half of A2A and is deliberately independent of the
inbound one: it speaks JSON-RPC over httpx and never touches ``a2a-sdk``, so a
deployment that skipped the optional extra can still call other agents even
though it cannot host one.
"""

from app.server_v2.services.catalog_transactions import catalog_transaction
from fastapi import APIRouter

from app.server_v2.api.deps import CurrentUser, ServiceDep
from app.server_v2.core.errors import ServerV2Error, success
from app.server_v2.domain.catalog import delete_a2a_agent, upsert_a2a_agent
from app.server_v2.schemas import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.server_v2.schemas.http import A2AAgentBody, A2AAgentPublic
from app.server_v2.services.a2a_client import discover_a2a_skills, to_a2a_config

router = APIRouter(
    prefix="/api/a2a-agents",
    tags=["a2a-agents"],
    responses={**AUTH_ERRORS, **VALIDATION_ERRORS},
)


@router.get("", response_model=ApiResponse[list[A2AAgentPublic]])
async def list_a2a_agents(user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    return success([item.public_dict() for item in catalog.a2a_agents])


@router.post("", response_model=ApiResponse[A2AAgentPublic])
@catalog_transaction
async def create_a2a_agent(body: A2AAgentBody, user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    record, catalog = upsert_a2a_agent(catalog, body.model_dump())
    await service.catalog.save(user.user_id, catalog)
    return success(record.public_dict())


@router.put("/{name}", response_model=ApiResponse[A2AAgentPublic])
@catalog_transaction
async def update_a2a_agent(
    name: str, body: A2AAgentBody, user: CurrentUser, service: ServiceDep
):
    catalog = await service.catalog.get(user.user_id)
    payload = body.model_dump()
    payload["name"] = name
    record, catalog = upsert_a2a_agent(catalog, payload)
    await service.catalog.save(user.user_id, catalog)
    service.a2a_plugins.invalidate(user.user_id)
    return success(record.public_dict())


@router.delete("/{name}", response_model=ApiResponse[None])
@catalog_transaction
async def remove_a2a_agent(name: str, user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    await service.catalog.save(user.user_id, delete_a2a_agent(catalog, name))
    service.a2a_plugins.invalidate(user.user_id)
    return success()


@router.post("/{name}/refresh", response_model=ApiResponse[A2AAgentPublic])
@catalog_transaction
async def refresh_a2a_agent(name: str, user: CurrentUser, service: ServiceDep):
    """Re-read the peer's Agent Card and record what it advertises now."""

    catalog = await service.catalog.get(user.user_id)
    current = next((item for item in catalog.a2a_agents if item.name == name), None)
    if current is None:
        raise ServerV2Error("not_found", "a2a agent not found")
    skills = await discover_a2a_skills(to_a2a_config(current))
    record = current.model_copy(update={"skills": list(dict.fromkeys(skills))})
    catalog.a2a_agents = [
        record if item.name == name else item for item in catalog.a2a_agents
    ]
    await service.catalog.save(user.user_id, catalog)
    # Refresh is the only verb that asks for a re-read without changing the
    # transport, so the cached plugin would otherwise keep serving the card it
    # saw the first time — including an empty one from a peer that was down.
    service.a2a_plugins.invalidate(user.user_id)
    return success(record.public_dict())
