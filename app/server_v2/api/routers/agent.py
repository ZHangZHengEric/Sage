from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.server_v2.api.deps import CurrentUser, ServiceDep
from app.server_v2.schemas import AUTH_ERRORS, AgentRunBody, ErrorBody

router = APIRouter(prefix="/api", tags=["agent"], responses=AUTH_ERRORS)


@router.post(
    "/agent",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "AG-UI 0.1.19 SSE event stream",
        },
        404: {"model": ErrorBody, "description": "thread not found"},
        422: {"model": ErrorBody, "description": "invalid run input"},
    },
)
async def run_agent(
    body: AgentRunBody, request: Request, user: CurrentUser, service: ServiceDep
):
    last_event_id = (request.headers.get("last-event-id") or "").strip() or None
    stream = await service.start_agui_run(
        body.to_agui(), user_id=user.user_id, last_event_id=last_event_id
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
