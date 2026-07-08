from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from common.core.request_identity import get_request_user_id
from common.schemas.model_invocation import DirectModelInvokeRequest
from common.services import model_invocation_service

model_router = APIRouter(prefix="/api/model", tags=["Model"])


@model_router.post("/invoke")
async def invoke_model(request: DirectModelInvokeRequest, http_request: Request):
    user_id = get_request_user_id(http_request)
    if request.stream:
        return StreamingResponse(
            model_invocation_service.stream_model(request, user_id=user_id),
            media_type="text/event-stream",
        )
    return await model_invocation_service.invoke_model(request, user_id=user_id)


@model_router.post("/invoke/stream")
async def stream_model(request: DirectModelInvokeRequest, http_request: Request):
    user_id = get_request_user_id(http_request)
    request.stream = True
    return StreamingResponse(
        model_invocation_service.stream_model(request, user_id=user_id),
        media_type="text/event-stream",
    )
