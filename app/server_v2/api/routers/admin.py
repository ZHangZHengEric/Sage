from typing import Any

from fastapi import APIRouter

from app.server_v2.api.deps import AdminUser, ServiceDep
from app.server_v2.schemas import (
    ADMIN_ERRORS,
    AdminModelPublic,
    AdminThreadPublic,
    ApiResponse,
    UserPublic,
)
from app.server_v2.core.errors import success

router = APIRouter(prefix="/api/admin", tags=["admin"], responses=ADMIN_ERRORS)


@router.get("/users", response_model=ApiResponse[list[UserPublic]])
async def admin_users(_: AdminUser, service: ServiceDep):
    return success([user.public_dict() for user in await service.users.list_users()])


@router.get("/threads", response_model=ApiResponse[list[AdminThreadPublic]])
async def admin_threads(_: AdminUser, service: ServiceDep):
    return success(
        [
            {
                **item.model_dump(mode="json"),
                "username": await service.username_for(item.user_id),
            }
            for item in await service.threads.list_all()
        ]
    )


@router.get("/models", response_model=ApiResponse[list[AdminModelPublic]])
async def admin_models(_: AdminUser, service: ServiceDep):
    users = await service.users.list_users()
    return success(
        [
            {
                **model.public_dict(),
                "user_id": user_id,
                "username": await service.username_for(user_id),
            }
            for user_id, model in await service.catalog.list_all_models(
                [user.user_id for user in users]
            )
        ]
    )


@router.get(
    "/threads/{thread_id}/events",
    response_model=ApiResponse[list[dict[str, Any]]],
)
async def admin_thread_events(thread_id: str, admin: AdminUser, service: ServiceDep):
    return success(await service.thread_events(thread_id, admin.user_id, admin=True))
