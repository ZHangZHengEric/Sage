"""CRUD for the remote A2A agents a tenant may delegate to.

This is the outbound half of A2A and is deliberately independent of the
inbound one: it speaks JSON-RPC over httpx and never touches ``a2a-sdk``, so a
deployment that skipped the optional extra can still call other agents even
though it cannot host one.
"""

from fastapi import APIRouter

from app.server_v2.api.deps import CatalogDep, CurrentUser
from app.server_v2.api.schemas import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.server_v2.api.schemas.http import A2AAgentBody, A2AAgentPublic
from app.server_v2.core.errors import success

router = APIRouter(
    prefix="/api/a2a-agents",
    tags=["a2a-agents"],
    responses={**AUTH_ERRORS, **VALIDATION_ERRORS},
)


@router.get("", response_model=ApiResponse[list[A2AAgentPublic]])
async def list_a2a_agents(user: CurrentUser, catalog: CatalogDep):
    agents = await catalog.list_a2a_agents(user.user_id)
    return success([item.public_dict() for item in agents])


@router.post("", response_model=ApiResponse[A2AAgentPublic])
async def create_a2a_agent(body: A2AAgentBody, user: CurrentUser, catalog: CatalogDep):
    record = await catalog.create_a2a_agent(user.user_id, body.model_dump())
    return success(record.public_dict())


@router.put("/{name}", response_model=ApiResponse[A2AAgentPublic])
async def update_a2a_agent(
    name: str, body: A2AAgentBody, user: CurrentUser, catalog: CatalogDep
):
    record = await catalog.update_a2a_agent(
        user.user_id, name, body.model_dump()
    )
    return success(record.public_dict())


@router.delete("/{name}", response_model=ApiResponse[None])
async def remove_a2a_agent(name: str, user: CurrentUser, catalog: CatalogDep):
    await catalog.delete_a2a_agent(user.user_id, name)
    return success()


@router.post("/{name}/refresh", response_model=ApiResponse[A2AAgentPublic])
async def refresh_a2a_agent(name: str, user: CurrentUser, catalog: CatalogDep):
    """Re-read the peer's Agent Card and record what it advertises now."""

    record = await catalog.refresh_a2a_agent(user.user_id, name)
    return success(record.public_dict())
