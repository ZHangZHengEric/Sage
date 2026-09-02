from typing import Any

from fastapi import APIRouter

from app.server_v2.api.deps import CurrentUser, ServiceDep
from app.server_v2.schemas import AUTH_ERRORS, ApiResponse, ThreadPublic
from app.server_v2.core.errors import success

router = APIRouter(
    prefix="/api/threads",
    tags=["threads"],
    responses={
        **AUTH_ERRORS,
        404: {"description": "thread not found"},
    },
)


@router.get("", response_model=ApiResponse[list[ThreadPublic]])
async def list_threads(user: CurrentUser, service: ServiceDep):
    return success(
        [item.model_dump(mode="json") for item in await service.threads.list_for(user.user_id)]
    )


@router.get("/{thread_id}/events", response_model=ApiResponse[list[dict[str, Any]]])
async def get_thread_events(thread_id: str, user: CurrentUser, service: ServiceDep):
    return success(await service.thread_events(thread_id, user.user_id))


@router.delete("/{thread_id}", response_model=ApiResponse[None])
async def delete_thread(thread_id: str, user: CurrentUser, service: ServiceDep):
    await service.delete_thread(thread_id, user.user_id, admin=user.role == "admin")
    return success()
