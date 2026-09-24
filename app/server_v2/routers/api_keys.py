from fastapi import APIRouter

from app.server_v2.routers.deps import CredentialDep, CurrentUser
from app.server_v2.routers.render import success
from app.server_v2.routers.schemas.common import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.server_v2.routers.schemas.identity import ApiKeyBody, ApiKeyCreated, ApiKeyPublic

router = APIRouter(tags=["api-keys"], responses={**AUTH_ERRORS, **VALIDATION_ERRORS})


@router.get("/api/keys", response_model=ApiResponse[list[ApiKeyPublic]])
async def list_keys(user: CurrentUser, service: CredentialDep):
    keys = await service.list_for(user.user_id)
    return success([item.public_dict() for item in keys])


@router.post("/api/keys", response_model=ApiResponse[ApiKeyCreated])
async def create_key(body: ApiKeyBody, user: CurrentUser, service: CredentialDep):
    record, token = await service.create(
        user_id=user.user_id,
        agent_id=body.agent_id or None,
        name=body.name,
        scopes=body.scopes,
    )
    return success({**record.public_dict(), "api_key": token})


@router.delete("/api/keys/{key_id}", response_model=ApiResponse[ApiKeyPublic])
async def revoke_key(key_id: str, user: CurrentUser, service: CredentialDep):
    record = await service.revoke(key_id, user.user_id)
    return success(record.public_dict())
