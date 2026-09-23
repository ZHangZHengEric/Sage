from fastapi import APIRouter

from app.server_v2.api.deps import CurrentUser, ServiceDep
from app.server_v2.core.errors import success
from app.server_v2.domain.catalog import require_agent
from app.server_v2.schemas import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.server_v2.schemas.http import ApiKeyBody, ApiKeyCreated, ApiKeyPublic

router = APIRouter(tags=["api-keys"], responses={**AUTH_ERRORS, **VALIDATION_ERRORS})


@router.get("/api/keys", response_model=ApiResponse[list[ApiKeyPublic]])
async def list_keys(user: CurrentUser, service: ServiceDep):
    keys = await service.api_keys.list_for(user.user_id)
    return success([item.public_dict() for item in keys])


@router.post("/api/keys", response_model=ApiResponse[ApiKeyCreated])
async def create_key(body: ApiKeyBody, user: CurrentUser, service: ServiceDep):
    catalog = await service.catalog.get(user.user_id)
    # Resolve now rather than at call time: a key naming an Agent that does not
    # exist would otherwise be issued happily and fail on every A2A request.
    agent = require_agent(catalog, body.agent_id or None)
    record, token = await service.api_keys.create(
        owner_user_id=user.user_id,
        agent_id=agent.id,
        name=body.name,
        scopes=body.scopes,
    )
    return success({**record.public_dict(), "api_key": token})


@router.delete("/api/keys/{key_id}", response_model=ApiResponse[ApiKeyPublic])
async def revoke_key(key_id: str, user: CurrentUser, service: ServiceDep):
    record = await service.api_keys.revoke(key_id, user.user_id)
    return success(record.public_dict())
