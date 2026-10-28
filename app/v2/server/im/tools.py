"""Run-scoped native tool: model writes content, the host owns the destination."""

from sagents.v2.contracts.items import JsonBlock
from sagents.v2.tool import tool, ToolInvocation, SideEffectLevel
from sagents.v2.tool.contracts import (
    IdempotencyStrategy,
    ResumeStrategy,
    ReconcileResult,
    ReconcileState,
    ToolExecutionResult,
)
from .contracts import NOTIFY_KEY
from .repository import error, key


class IMNotificationTools:
    def __init__(self, notifications, command, run_id):
        self.notifications = notifications
        self.command = command
        self.run_id = run_id
        self.owner = command.config.metadata[NOTIFY_KEY]["owner_id"]

    def authorize(self, call, context):
        if (
            call.owner_run_id != self.run_id
            or self.command.parent_run_id
            or context.actor.principal_id != self.owner
            or context.actor.tenant_id != self.owner
            or call.owner_session_id not in {None, self.command.session_id}
        ):
            raise error("notification_forbidden", "只能为当前本人任务准备通知")

    @tool(
        description=(
            "Prepare the final IM notification for this task. Call once after completing the work. "
            "Write a concise user-facing result summary in content. The destination is already bound by the user. "
            "The host sends it only after the Run completes; prepared does not mean delivered. "
            "Keep the detailed answer in your normal final reply."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "minLength": 1, "maxLength": 20000}
            },
            "required": ["content"],
            "additionalProperties": False,
        },
        side_effect_level=SideEffectLevel.WRITE,
        idempotency_strategy=IdempotencyStrategy.NATIVE_KEY,
        resume_strategy=ResumeStrategy.RECONCILE,
        supports_reconciliation=True,
    )
    async def im_notify(self, content: str, invocation: ToolInvocation):
        self.authorize(invocation.call, invocation.request_context)
        return await self.notifications.prepare(
            self.command, self.run_id, self.owner, content
        )

    async def reconcile_im_notify(self, call, context):
        self.authorize(call, context)
        record = await self.notifications.store.find(self.command, self.owner)
        if (
            record is None
            or record.run_context.get("run_id") != self.run_id
            or record.run_context.get("draft_digest")
            != key(str(call.arguments.get("content", "")).strip())
        ):
            return ReconcileResult(
                operation_id=call.operation_id, state=ReconcileState.UNKNOWN
            )
        return ReconcileResult(
            operation_id=call.operation_id,
            state=ReconcileState.SUCCEEDED,
            result=ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(
                    JsonBlock(
                        value={"notification_id": record.id, "status": "prepared"}
                    ),
                ),
            ),
        )
