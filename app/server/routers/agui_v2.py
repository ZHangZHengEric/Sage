"""Native AG-UI V2 chat endpoint for Sage Server.

The endpoint follows the AG-UI HTTP/SSE shape documented at
https://docs.ag-ui.com/concepts/architecture while keeping Sage's existing
chat endpoints and native stream protocol unchanged.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from ag_ui.core import RunAgentInput
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from common.core.exceptions import SageHTTPException
from common.core.request_identity import get_request_user_id
from common.models.conversation import ConversationDao
from common.schemas.chat import Message, StreamRequest
from common.services import chat_service
from common.services.agui_v2_run_store import (
    AguiRun,
    AguiRunConflict,
    AguiV2RunStore,
    get_agui_v2_run_store,
)
from common.services.agui_v2_service import AguiEventTranslator
from sagents.context.session_context import delete_session_run_lock
from sagents.utils.lock_manager import safe_release

from .chat import _guard_request_multimodal_images, validate_and_prepare_request


agui_v2_router = APIRouter(prefix="/api/v2/agent", tags=["AG-UI V2"])
_BACKGROUND_RUNS: set[asyncio.Task[None]] = set()
_GENERATOR_CLOSE_TIMEOUT_SECONDS = 5.0
_MAX_AGUI_ID_LENGTH = 256


def _forwarded_props(request: RunAgentInput) -> Mapping[str, Any]:
    props = request.forwarded_props
    if props is None:
        return {}
    if not isinstance(props, Mapping):
        raise ValueError("forwardedProps must be an object")
    return props


def _agui_user_content(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    result: list[dict[str, Any]] = []
    for part in content:
        if hasattr(part, "model_dump"):
            value = part.model_dump(by_alias=True, exclude_none=True, mode="json")
        elif isinstance(part, Mapping):
            value = dict(part)
        else:
            continue
        part_type = value.get("type")
        if part_type == "text":
            result.append({"type": "text", "text": str(value.get("text") or "")})
        elif part_type == "image":
            source = value.get("source")
            if (
                isinstance(source, Mapping)
                and source.get("type") == "url"
                and source.get("value")
            ):
                result.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": str(source["value"])},
                    }
                )
    return result


def _optional_mapping(props: Mapping[str, Any], key: str) -> dict[str, Any] | None:
    value = props.get(key)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"forwardedProps.{key} must be an object")
    return dict(value)


def _optional_string_list(props: Mapping[str, Any], key: str) -> list[str] | None:
    value = props.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"forwardedProps.{key} must be an array of strings")
    return list(value)


def _validate_agui_id(value: str, *, field: str, session_id: bool = False) -> str:
    candidate = str(value or "").strip()
    invalid_session_id = session_id and (
        candidate in {".", ".."} or "/" in candidate or "\\" in candidate
    )
    if (
        not candidate
        or len(candidate) > _MAX_AGUI_ID_LENGTH
        or "\x00" in candidate
        or invalid_session_id
    ):
        raise ValueError(f"{field} is invalid")
    return candidate


def _to_stream_request(request: RunAgentInput, *, user_id: str) -> StreamRequest:
    props = _forwarded_props(request)
    thread_id = _validate_agui_id(request.thread_id, field="threadId", session_id=True)
    _validate_agui_id(request.run_id, field="runId")
    agent_id = str(props.get("agentId") or "").strip()
    user_messages = [
        message
        for message in request.messages
        if getattr(message, "role", None) == "user"
    ]
    if not agent_id:
        raise ValueError("forwardedProps.agentId is required")
    if not user_messages:
        raise ValueError("at least one user message is required")

    latest = user_messages[-1]
    return StreamRequest(
        messages=[
            Message(
                message_id=str(getattr(latest, "id", "") or "") or None,
                role="user",
                content=_agui_user_content(getattr(latest, "content", "")),
            )
        ],
        session_id=thread_id,
        user_id=user_id,
        agent_id=agent_id,
        system_context=_optional_mapping(props, "systemContext"),
        provider_id=str(props.get("providerId") or "").strip() or None,
        fast_provider_id=str(props.get("fastProviderId") or "").strip() or None,
        agent_mode=props.get("agentMode"),
        max_loop_count=props.get("maxLoopCount"),
        more_suggest=props.get("moreSuggest"),
        available_sub_agent_ids=_optional_string_list(props, "availableSubAgentIds"),
    )


async def _ensure_thread_access(thread_id: str, user_id: str) -> None:
    conversation = await ConversationDao().get_by_session_id(thread_id)
    if conversation is not None and conversation.user_id != user_id:
        raise SageHTTPException(
            status_code=404,
            detail="Conversation not found",
            error_detail="AG-UI V2 thread is not owned by the authenticated user",
        )


async def _persist_agui_events(
    event_store: AguiV2RunStore,
    run: AguiRun,
    generator,
) -> None:
    """Translate Sage NDJSON into replayable AG-UI events for one run."""

    buffer = ""
    translator = AguiEventTranslator(thread_id=run.thread_id, run_id=run.run_id)
    run_finished = False

    async def publish_source(event: dict[str, Any]) -> None:
        for agui_event in translator.translate(event):
            await event_store.publish(run, agui_event)

    async def finish_once() -> None:
        nonlocal run_finished
        if run_finished:
            return
        for event in translator.run_finished():
            await event_store.publish(run, event)
        await event_store.finish(run, status="completed")
        run_finished = True

    async def handle_line(line: str) -> None:
        if not line.strip():
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            raise ValueError("Sage chat stream event is invalid JSON") from None
        if not isinstance(event, dict):
            raise ValueError("Sage chat stream event must be an object")
        await publish_source(event)
        if str(event.get("type") or "") == "stream_end":
            await finish_once()

    try:
        async for chunk in generator:
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                await handle_line(line)
        if buffer.strip():
            await handle_line(buffer)
        await finish_once()
    except asyncio.CancelledError:
        if not run_finished:
            for event in translator.run_finished(result={"status": "interrupted"}):
                await event_store.publish(run, event)
            await event_store.finish(run, status="stopped")
        raise
    except Exception:
        if run_finished:
            logger.bind(run_id=run.run_id, thread_id=run.thread_id).exception(
                "AG-UI V2 native stream finalizer failed after terminal event"
            )
            return
        for event in translator.run_error(
            "Internal Server Error during stream processing",
            code="STREAM_ERROR",
        ):
            await event_store.publish(run, event)
        await event_store.finish(run, status="failed")
        raise


async def _run_in_background(
    event_store: AguiV2RunStore,
    run: AguiRun,
    stream_service: chat_service.SageStreamService,
    lock: asyncio.Lock,
) -> None:
    generator = chat_service.execute_chat_session(stream_service=stream_service)
    try:
        await _persist_agui_events(event_store, run, generator)
    finally:
        if hasattr(generator, "aclose"):
            try:
                await asyncio.wait_for(
                    generator.aclose(),
                    timeout=_GENERATOR_CLOSE_TIMEOUT_SECONDS,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.bind(run_id=run.run_id, thread_id=run.thread_id).warning(
                    "AG-UI V2 generator cleanup did not complete"
                )
            except Exception:
                logger.bind(run_id=run.run_id, thread_id=run.thread_id).exception(
                    "AG-UI V2 generator cleanup failed"
                )
        await safe_release(lock, run.thread_id, "AG-UI V2 run cleanup")
        delete_session_run_lock(run.thread_id)


def _track_background_task(task: asyncio.Task[None]) -> None:
    _BACKGROUND_RUNS.add(task)

    def done(completed: asyncio.Task[None]) -> None:
        _BACKGROUND_RUNS.discard(completed)
        if completed.cancelled():
            return
        error = completed.exception()
        if error is not None:
            logger.opt(exception=error).error("AG-UI V2 background run failed")

    task.add_done_callback(done)


def _sse_response(event_store: AguiV2RunStore, run: AguiRun, last_event_id: str | None):
    return StreamingResponse(
        event_store.subscribe(run, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Sage-AG-UI-Replay": "process-local",
        },
    )


@agui_v2_router.post("/chat")
async def chat_v2(request: RunAgentInput, http_request: Request):
    """Run Sage through the AG-UI 0.1.19 HTTP/SSE contract."""

    user_id = get_request_user_id(http_request).strip()
    if not user_id:
        raise SageHTTPException(
            status_code=401,
            detail="Authentication required",
            error_detail="missing authenticated Sage user",
        )
    try:
        inner_request = _to_stream_request(request, user_id=user_id)
    except ValueError as error:
        raise SageHTTPException(
            status_code=422,
            detail=str(error),
            error_detail="invalid AG-UI V2 run input",
        ) from error

    await _ensure_thread_access(inner_request.session_id or "", user_id)

    event_store = get_agui_v2_run_store()
    try:
        claim = await event_store.claim_run(
            user_id=user_id,
            thread_id=request.thread_id,
            run_id=request.run_id,
        )
    except AguiRunConflict as error:
        raise SageHTTPException(
            status_code=409,
            detail="runId conflicts with an existing AG-UI thread",
            error_detail="AG-UI V2 run idempotency conflict",
        ) from error

    run = claim.run
    last_event_id = (http_request.headers.get("last-event-id") or "").strip() or None
    if not claim.created:
        return _sse_response(event_store, run, last_event_id)

    translator = AguiEventTranslator(thread_id=run.thread_id, run_id=run.run_id)
    await event_store.publish(run, translator.run_started())
    try:
        validate_and_prepare_request(
            inner_request,
            http_request,
            allow_pending_guidance_flush=True,
        )
        await _guard_request_multimodal_images(inner_request)
        chat_service.mark_request_execution(
            inner_request,
            request_source="api/v2/agent/chat",
        )
        await chat_service.populate_request_from_agent_config(
            inner_request,
            require_agent_id=True,
        )
        stream_service, lock = await chat_service.prepare_session(inner_request)
    except Exception as error:
        for event in translator.run_error(
            "Unable to start Agent run",
            code="RUN_START_ERROR",
        ):
            await event_store.publish(run, event)
        await event_store.finish(run, status="failed")
        if (
            isinstance(error, SageHTTPException)
            and error.message_key == "chat.session_running"
        ):
            raise SageHTTPException(
                status_code=409,
                detail="Another chat run is already active for this thread",
                error_detail="AG-UI V2 thread already has an active Sage run",
            ) from error
        raise

    task = asyncio.create_task(
        _run_in_background(event_store, run, stream_service, lock),
        name=f"agui-v2-{run.run_id}",
    )
    _track_background_task(task)
    return _sse_response(event_store, run, last_event_id)


__all__ = ["agui_v2_router"]
