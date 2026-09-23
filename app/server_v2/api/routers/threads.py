from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.server_v2.api.deps import CurrentUser, ServiceDep
from app.server_v2.schemas import (
    AUTH_ERRORS,
    ApiResponse,
    ThreadEventPage,
    ThreadPublic,
    ThreadResumeBody,
)
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


@router.get("/{thread_id}/events", response_model=ApiResponse[ThreadEventPage])
async def get_thread_events(
    thread_id: str,
    user: CurrentUser,
    service: ServiceDep,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int | None = Query(default=None, ge=0),
):
    return success(
        await service.thread_events(
            thread_id, user.user_id, limit=limit, offset=offset
        )
    )


@router.post(
    "/{thread_id}/resume",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "AG-UI 0.1.19 SSE event stream",
        },
        409: {"description": "thread is not waiting for input"},
        422: {"description": "decision not offered by the pending question"},
    },
)
async def resume_thread(
    thread_id: str,
    body: ThreadResumeBody,
    request: Request,
    user: CurrentUser,
    service: ServiceDep,
):
    """Answer a waiting thread and stream the work the answer releases.

    This is a stream rather than an acknowledgement for the same reason
    ``/api/agent`` is: the answer restarts a Run, and the client wants to watch
    it, not to be told it was accepted and then have to reconnect.
    """

    last_event_id = (request.headers.get("last-event-id") or "").strip() or None
    stream = await service.resume_agui_run(
        thread_id,
        run_id=body.runId,
        user_id=user.user_id,
        decision=body.decision,
        payload=body.payload,
        last_event_id=last_event_id,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Sage-AG-UI-Replay": service.backends()["agui_replay"],
        },
    )


@router.delete("/{thread_id}", response_model=ApiResponse[None])
async def delete_thread(thread_id: str, user: CurrentUser, service: ServiceDep):
    await service.delete_thread(thread_id, user.user_id, admin=user.role == "admin")
    return success()
