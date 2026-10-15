from fastapi import APIRouter, Response

from app.v2.server.routers.deps import ReadUser, CatalogDep, CurrentUser
from app.v2.server.routers.schemas.common import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.v2.server.routers.schemas.catalog import ModelBody, ModelDetail, ModelPublic
from app.v2.server.routers.render import success
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

router = APIRouter(
    prefix="/api/models",
    tags=["models"],
    responses={**AUTH_ERRORS, **VALIDATION_ERRORS},
)


@router.get("", response_model=ApiResponse[list[ModelPublic]])
async def list_models(user: ReadUser, service: CatalogDep):
    return success(
        [item.public_dict() for item in (await service.get(user.user_id)).models]
    )


@router.post("", response_model=ApiResponse[ModelPublic])
async def upsert_model(body: ModelBody, user: CurrentUser, service: CatalogDep):
    record = await service.upsert_model(user.user_id, body.model_dump(exclude_unset=True))
    return success(record.public_dict())


@router.post("/probe")
async def probe_model(
    body: ModelBody, user: CurrentUser, service: CatalogDep, response: Response
):
    from app.v2.server.catalog.records import apply_upsert
    from app.v2.server.runtime.models import (
        create_catalog_provider,
        close_model_provider,
    )
    from sagents.v2.model.capability_contracts import ModelCapabilityProbeRequest

    # Resolve blank keys only within the caller's own catalog; probing never saves a draft.
    catalog = (await service.get(user.user_id)).model_copy(deep=True)
    record, _ = apply_upsert(
        catalog, {**body.model_dump(exclude_unset=True), "capability_profile": None}
    )
    async with service.model_probe_slot(user.user_id):
        provider = await create_catalog_provider(record)
        response.headers["Cache-Control"] = "no-store"
        try:
            profile = await provider.probe_capabilities(
                ModelCapabilityProbeRequest(
                    model_binding=record.id,
                    route_fingerprint=record.fingerprint(),
                    max_output_tokens=record.request.max_output_tokens
                    or record.limits.max_output_tokens
                    or 8192,
                )
            )
            return success(profile.model_dump(mode="json"))
        finally:
            await close_model_provider(provider)


@router.get("/{model_id}", response_model=ApiResponse[ModelDetail])
async def get_model(
    model_id: str, user: ReadUser, service: CatalogDep, response: Response
):
    catalog = await service.get(user.user_id)
    record = next((item for item in catalog.models if item.id == model_id), None)
    if record is None:
        raise SageV2Error(RuntimeErrorInfo(
            code="server.routers.models.not_found",
            category=ErrorCategory.VALIDATION,
            message="model not found",
        ))
    response.headers["Cache-Control"] = "no-store"
    return success({**record.public_dict(), "api_key": record.api_key.get_secret_value()})


@router.delete("/{model_id}", response_model=ApiResponse[None])
async def delete_model(model_id: str, user: CurrentUser, service: CatalogDep):
    await service.delete_model(user.user_id, model_id)
    return success()
