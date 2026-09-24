from __future__ import annotations

from collections.abc import AsyncGenerator

from a2a.server.context import ServerCallContext
from a2a.server.events.event_queue import Event
from a2a.server.request_handlers.request_handler import RequestHandler
from a2a.types.a2a_pb2 import (
    AgentCard,
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigRequest,
    GetExtendedAgentCardRequest,
    GetTaskPushNotificationConfigRequest,
    GetTaskRequest,
    ListTaskPushNotificationConfigsRequest,
    ListTaskPushNotificationConfigsResponse,
    ListTasksRequest,
    ListTasksResponse,
    Message,
    SendMessageRequest,
    SubscribeToTaskRequest,
    Task,
    TaskPushNotificationConfig,
)
from a2a.utils.errors import (
    A2AError,
    InternalError,
    InvalidParamsError,
    PushNotificationNotSupportedError,
    TaskNotCancelableError,
    TaskNotFoundError,
    UnsupportedOperationError,
)

from app.server_v2.adapters.a2a.context import key_from
from app.server_v2.adapters.a2a.service import A2AService
from app.server_v2.core.errors import ServerError

_ERRORS: dict[str, type[A2AError]] = {
    "not_found": TaskNotFoundError,
    "validation": InvalidParamsError,
    "conflict": TaskNotCancelableError,
}


class SageRequestHandler(RequestHandler):
    """Serve A2A methods straight from the Sage runtime.

    The SDK also ships ``DefaultRequestHandler``, which owns a ``TaskStore`` of
    its own. Using it would make the SDK's store a second, competing record of
    what a Run did — and the two would drift the moment a Run was resumed or
    replayed from the canonical event log. This handler keeps Sage as the only
    source of truth and treats A2A purely as a projection.

    Push notification config is the one method group that is not implemented,
    and it raises rather than answering with a plausible empty result: a caller
    told "no configs" when the method simply is not wired up cannot tell the
    difference between an agent with none and a broken one.

    A message that names a ``taskId`` is a reply to a Task waiting on input,
    not a continuation of a finished one: it is routed to the suspended Run's
    pending Interaction, and rejected as invalid params if that Task is not
    actually waiting for anything.
    """

    def __init__(self, service: A2AService) -> None:
        self._service = service

    async def on_message_send(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> Task | Message:
        key = key_from(context)
        config = params.configuration
        with _translated():
            return await self._service.send_message(
                params.message,
                key,
                history_length=config.history_length,
                wait=not config.return_immediately,
            )

    async def on_get_task(
        self, params: GetTaskRequest, context: ServerCallContext
    ) -> Task | None:
        key = key_from(context)
        with _translated():
            return await self._service.get_task(
                params.id, key, history_length=params.history_length
            )

    async def on_message_send_stream(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> AsyncGenerator[Event]:
        key = key_from(context)
        config = params.configuration
        with _translated():
            events = await self._service.stream_message(
                params.message, key, history_length=config.history_length
            )
            async for event in events:
                yield event

    async def on_subscribe_to_task(
        self, params: SubscribeToTaskRequest, context: ServerCallContext
    ) -> AsyncGenerator[Event]:
        key = key_from(context)
        with _translated():
            events = await self._service.subscribe_task(params.id, key)
            async for event in events:
                yield event

    async def on_list_tasks(
        self, params: ListTasksRequest, context: ServerCallContext
    ) -> ListTasksResponse:
        key = key_from(context)
        with _translated():
            tasks, next_page_token = await self._service.list_tasks(
                key,
                context_id=params.context_id,
                state=params.status,
                page_size=params.page_size,
                page_token=params.page_token,
                history_length=params.history_length,
            )
        response = ListTasksResponse(
            next_page_token=next_page_token, page_size=len(tasks)
        )
        response.tasks.extend(tasks)
        return response

    async def on_cancel_task(
        self, params: CancelTaskRequest, context: ServerCallContext
    ) -> Task | None:
        key = key_from(context)
        with _translated():
            return await self._service.cancel_task(params.id, key)

    async def on_get_extended_agent_card(
        self, params: GetExtendedAgentCardRequest, context: ServerCallContext
    ) -> AgentCard:
        # The public card already carries everything this server knows; there is
        # no privileged variant to hand out.
        raise UnsupportedOperationError(
            message="this agent does not publish an extended card"
        )

    async def on_create_task_push_notification_config(
        self, params: TaskPushNotificationConfig, context: ServerCallContext
    ) -> TaskPushNotificationConfig:
        raise PushNotificationNotSupportedError

    async def on_get_task_push_notification_config(
        self, params: GetTaskPushNotificationConfigRequest, context: ServerCallContext
    ) -> TaskPushNotificationConfig:
        raise PushNotificationNotSupportedError

    async def on_list_task_push_notification_configs(
        self,
        params: ListTaskPushNotificationConfigsRequest,
        context: ServerCallContext,
    ) -> ListTaskPushNotificationConfigsResponse:
        raise PushNotificationNotSupportedError

    async def on_delete_task_push_notification_config(
        self,
        params: DeleteTaskPushNotificationConfigRequest,
        context: ServerCallContext,
    ) -> None:
        raise PushNotificationNotSupportedError


class _translated:
    """Turn Sage's own failures into the JSON-RPC errors A2A defines.

    Without this, a missing Task or a malformed Part would reach the dispatcher
    as an unknown exception and be reported as -32603 Internal error, which
    tells a client to retry something that will never succeed. Authorization
    failures are deliberately absent from the table: A2A has no JSON-RPC error
    for them, so scopes are enforced at the HTTP layer, and reaching one here
    means the route's own check was bypassed — an internal error, truthfully.
    """

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if not isinstance(exc, ServerError):
            return False
        factory = _ERRORS.get(exc.reason, InternalError)
        raise factory(message=exc.message) from exc
