from fastapi import APIRouter, Query

from app.server_v2.api.deps import AdminDep, AdminUser
from app.server_v2.api.schemas import (
    ADMIN_ERRORS,
    AdminModelPublic,
    AdminThreadPublic,
    ApiResponse,
    ThreadEventPage,
    UserPublic,
)
from app.server_v2.core.errors import success

router = APIRouter(prefix="/api/admin", tags=["admin"], responses=ADMIN_ERRORS)


@router.get("/users", response_model=ApiResponse[list[UserPublic]])
async def admin_users(_: AdminUser, admin: AdminDep):
    return success(await admin.list_users())


@router.get("/threads", response_model=ApiResponse[list[AdminThreadPublic]])
async def admin_threads(_: AdminUser, admin: AdminDep):
    return success(await admin.list_threads())


@router.get("/models", response_model=ApiResponse[list[AdminModelPublic]])
async def admin_models(_: AdminUser, admin: AdminDep):
    return success(await admin.list_models())


@router.get(
    "/threads/{thread_id}/events",
    response_model=ApiResponse[ThreadEventPage],
)
async def admin_thread_events(
    thread_id: str,
    user: AdminUser,
    admin: AdminDep,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int | None = Query(
        default=None,
        ge=0,
        description="Session sequence already delivered. Omit for the newest page.",
    ),
):
    return success(
        await admin.thread_events(
            thread_id, user.user_id, limit=limit, offset=offset
        )
    )
