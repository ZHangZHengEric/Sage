from fastapi import APIRouter

from app.server_v2.routers.deps import ServiceDep, CurrentUser
from app.server_v2.routers.schemas.common import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.server_v2.routers.schemas.catalog import ModelBody, ModelPublic
from app.server_v2.routers.render import success

router = APIRouter(
    prefix="/api/models",
    tags=["models"],
    responses={**AUTH_ERRORS, **VALIDATION_ERRORS},
)


@router.get("", response_model=ApiResponse[list[ModelPublic]])
async def list_models(user: CurrentUser, service: ServiceDep):
    return success(
        [item.public_dict() for item in (await service.catalog_store.get(user.user_id)).models]
    )


@router.post("", response_model=ApiResponse[ModelPublic])
async def upsert_model(body: ModelBody, user: CurrentUser, service: ServiceDep):
    record = await service.catalog.upsert_model(user.user_id, body.model_dump())
    return success(record.public_dict())


@router.delete("/{model_id}", response_model=ApiResponse[None])
async def delete_model(model_id: str, user: CurrentUser, service: ServiceDep):
    await service.catalog.delete_model(user.user_id, model_id)
    return success()
