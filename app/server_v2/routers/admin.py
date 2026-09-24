from fastapi import APIRouter, Query

from app.server_v2.routers.deps import AdminDep, ConversationDep, AdminUser
from app.server_v2.routers.schemas.common import ADMIN_ERRORS, ApiResponse
from app.server_v2.routers.schemas.admin import AdminModelPublic, AdminThreadPublic
from app.server_v2.routers.schemas.conversations import ThreadEventPage
from app.server_v2.routers.schemas.identity import UserPublic
from app.server_v2.routers.render import success

router = APIRouter(prefix="/api/admin", tags=["admin"], responses=ADMIN_ERRORS)


@router.get("/users", response_model=ApiResponse[list[UserPublic]])
async def admin_users(_: AdminUser, service: AdminDep):
    return success(await service.list_users())


@router.get("/threads", response_model=ApiResponse[list[AdminThreadPublic]])
async def admin_threads(_: AdminUser, service: AdminDep):
    return success(await service.list_threads())


@router.get("/models", response_model=ApiResponse[list[AdminModelPublic]])
async def admin_models(_: AdminUser, service: AdminDep):
    return success(await service.list_models())


@router.get(
    "/threads/{thread_id}/events",
    response_model=ApiResponse[ThreadEventPage],
)
async def admin_thread_events(
    thread_id: str,
    user: AdminUser,
    service: ConversationDep,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int | None = Query(
        default=None,
        ge=0,
        description="Session sequence already delivered. Omit for the newest page.",
    ),
):
    return success(
        await service.events(
            thread_id, user.user_id, limit=limit, offset=offset, admin=True
        )
    )
