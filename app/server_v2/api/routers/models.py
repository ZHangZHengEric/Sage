from fastapi import APIRouter

from app.server_v2.api.deps import CatalogDep, CurrentUser
from app.server_v2.api.schemas import (
    AUTH_ERRORS,
    VALIDATION_ERRORS,
    ApiResponse,
    ModelBody,
    ModelPublic,
)
from app.server_v2.core.errors import success

router = APIRouter(
    prefix="/api/models",
    tags=["models"],
    responses={**AUTH_ERRORS, **VALIDATION_ERRORS},
)


@router.get("", response_model=ApiResponse[list[ModelPublic]])
async def list_models(user: CurrentUser, catalog: CatalogDep):
    return success(
        [item.public_dict() for item in await catalog.list_models(user.user_id)]
    )


@router.post("", response_model=ApiResponse[ModelPublic])
async def upsert_model(body: ModelBody, user: CurrentUser, catalog: CatalogDep):
    record = await catalog.upsert_model(user.user_id, body.model_dump())
    return success(record.public_dict())


@router.delete("/{model_id}", response_model=ApiResponse[None])
async def delete_model(model_id: str, user: CurrentUser, catalog: CatalogDep):
    await catalog.delete_model(user.user_id, model_id)
    return success()
