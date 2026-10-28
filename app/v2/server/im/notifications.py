"""Model-authored final notifications, projected from the native Run authority."""

import time

from sqlalchemy import select

from app.v2.server.runtime.policy import EXECUTION_METADATA_KEY, live_execution_policy
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import MessageItemData, TextBlock, Visibility
from sagents.v2.contracts.run_state import RunState, TERMINAL_RUN_STATES
from sagents.v2.runtime.observability.logs import get_logger
from .contracts import NOTIFY_KEY, NotificationRoute
from .notification_store import NotificationStore
from .orm import BindingRow
from .repository import error

LOGGER = get_logger(__name__)


def final_text(run, result, link):
    if run.state == RunState.CANCELLED:
        return "任务已取消。"
    if run.state != RunState.COMPLETED:
        return "任务执行失败，请在 Sage 中查看：" + link
    for item in reversed(result.final_items):
        if (
            item.visibility == Visibility.PUBLIC
            and isinstance(item.data, MessageItemData)
            and item.data.role == "assistant"
        ):
            text = "".join(
                block.text
                for block in item.data.content
                if isinstance(block, TextBlock)
            )
            if text.strip():
                return (
                    text if len(text) <= 20000 else text[:20000] + "\n完整结果：" + link
                )
    return "任务已完成：" + link


class IMNotifications:
    def __init__(self, service):
        self.service = service
        self.host = service.host
        self.store = NotificationStore(service.store)

    async def bind(self, command, owner, connection_id, *, binding_id=None):
        conn = await self.service.store.get(connection_id, owner)
        if (
            not conn.enabled
            or not conn.sender_id
            or self.service.credentials_error(conn.id)
        ):
            raise error(
                "notification_target_unavailable", "请选择本人已启用并配对的 IM 连接"
            )
        async with self.host.database.session() as db:
            stmt = select(BindingRow).where(
                BindingRow.connection_id == conn.id,
                BindingRow.sender_id == conn.sender_id,
            )
            if binding_id is not None:
                stmt = stmt.where(BindingRow.id == binding_id)
            bindings = list((await db.scalars(stmt.limit(2))).all())
        if len(bindings) != 1:
            raise error(
                "notification_target_unavailable", "IM 私聊目标尚未确认，请重新配对"
            )
        binding = bindings[0]
        execution = command.config.metadata.get(EXECUTION_METADATA_KEY, {})
        route = NotificationRoute(
            owner_id=owner,
            agent_id=execution.get("agent_id", command.agent_id),
            connection_id=conn.id,
            binding_id=binding.id,
            generation=binding.generation,
            auth_epoch=conn.auth_epoch,
            sender_id=conn.sender_id,
            chat_id=binding.chat_id,
        )
        if not await self.authorized(command, route):
            raise error(
                "notification_forbidden", "只能为本人有权执行的任务配置 IM 通知"
            )
        metadata = {**command.config.metadata, NOTIFY_KEY: route.model_dump()}
        metadata["system_context"] = {
            **metadata.get("system_context", {}),
            "im_notification": (
                "任务完成前调用 im_notify，为用户准备简洁的最终 IM 通知正文。"
                "工具只准备内容，Run 完成后由服务端发送；不要把 prepared 表述为已送达。"
            ),
        }
        return command.model_copy(
            update={"config": command.config.model_copy(update={"metadata": metadata})}
        )

    async def authorized(self, command, route):
        if command.parent_run_id or route.owner_id != command.config.metadata.get(
            EXECUTION_METADATA_KEY, {}
        ).get("user_id"):
            return False
        context = self.host.contexts.for_user(route.owner_id)
        return (
            await live_execution_policy(
                command,
                users=self.host.users,
                keys=self.host.credentials.keys,
                catalog=self.host.catalog_store,
                settings=self.host.settings,
                user_id=route.owner_id,
                catalog_agent_id=route.agent_id,
                context=context,
                package_authorizer=self.host.agent_management.authorize_package,
                ingress_authorizer=self.service.authorize_run,
            )
            is not None
        )

    async def track(self, command, owner):
        route = NotificationRoute.model_validate(command.config.metadata[NOTIFY_KEY])
        if route.owner_id != owner or command.parent_run_id:
            raise error("notification_forbidden", "通知归属不匹配")
        existing = await self.store.find(command, owner)
        if existing is None:
            # Completed Runs whose delivery/dedupe retention elapsed must not be
            # announced again just because a client repeats an old HTTP request.
            previous = await self._find_run(
                command.session_id, command.idempotency_key, owner
            )
            if previous is not None and previous[0].state in TERMINAL_RUN_STATES:
                return None
        return await self.store.track(command, owner)

    async def _find_run(self, session_id, request_key, owner):
        try:
            return await self.host.conversations.session_access.find_start_run(
                session_id, request_key, self.host.contexts.for_user(owner)
            )
        except SageV2Error as exc:
            if exc.info.code.endswith("not_found"):
                return None
            raise

    async def prepare(self, command, run_id, owner, content):
        if not isinstance(content, str) or not content.strip() or len(content) > 20000:
            raise error("invalid_notification", "通知正文须为 1–20000 字符的非空文本")
        route = NotificationRoute.model_validate(command.config.metadata[NOTIFY_KEY])
        if (
            owner != route.owner_id
            or command.invocation_mode == "plan"
            or not await self.authorized(command, route)
        ):
            raise error("notification_forbidden", "当前任务无权准备 IM 通知")
        record = await self.track(command, owner)
        if record is None:
            raise error("notification_closed", "任务通知已结束")
        return await self.store.prepare(record, run_id, content.strip())

    async def tick(self, conn, worker):
        for record in await self.store.waiting(conn.id):
            try:
                await self._watch(record, worker)
            except Exception:
                LOGGER.warning(
                    "server.im.notification.retry",
                    "Run notification projection will retry",
                    attributes={"connection_id": conn.id, "notification_id": record.id},
                )
                await self.store.defer(record, worker)

    async def observe(self, command, owner, worker):
        """IM ingress already observed a transition; project it without poll delay."""
        record = await self.store.find(command, owner)
        if record is not None and record.state == "prepared":
            await self._watch(record, worker)

    async def _watch(self, record, worker):
        info = record.run_context
        route = NotificationRoute.model_validate(info["route"])
        context = self.host.contexts.for_user(route.owner_id)
        access = self.host.conversations.session_access
        found = await self._find_run(
            info["session_id"], info["idempotency_key"], route.owner_id
        )
        if found is None:
            # Acceptance may be retried after an arbitrarily long outage.
            # Keep the bounded intent, with slower checks for stale attempts.
            await self.store.defer(
                record,
                worker,
                delay=60 if time.time() - record.created_at > 3600 else 0.5,
            )
            return
        run, command = found
        if command.config.metadata.get(NOTIFY_KEY) != info[
            "route"
        ] or not await self.authorized(command, route):
            await self.store.project(
                record, worker, run.run_id, "", abandon="grant_revoked"
            )
            return
        if run.state == RunState.RESUMING and not self.host.execution.driving(
            run.run_id
        ):
            await self.host.conversations.runs.continue_detached_run(
                run.run_id,
                context,
                user_id=route.owner_id,
                session_id=run.session_id,
                label="im-notification",
            )
        if run.state == RunState.SUSPENDED:
            await self.store.project(
                record,
                worker,
                run.run_id,
                "任务需要你的确认或补充，请登录 Sage 继续：\n"
                + self.service.link(run.session_id),
                purpose="interaction:" + run.suspension_id,
            )
        elif run.state in TERMINAL_RUN_STATES:
            result = await access.get_run_result(run.run_id, context)
            await self.store.project(
                record,
                worker,
                run.run_id,
                final_text(run, result, self.service.link(run.session_id)),
                final=True,
                completed=run.state == RunState.COMPLETED,
            )
        else:
            await self.store.defer(record, worker, run.run_id)

    async def authorize_delivery(self, record):
        if not record.run_context:
            return True
        info = record.run_context
        route = NotificationRoute.model_validate(info["route"])
        context = self.host.contexts.for_user(route.owner_id)
        access = self.host.conversations.session_access
        try:
            command = await access.get_start_command(info["run_id"], context)
            if command.config.metadata.get(NOTIFY_KEY) != info[
                "route"
            ] or not await self.authorized(command, route):
                return False
            run = await access.get_run(info["run_id"], context)
            if info["purpose"].startswith("interaction:"):
                return (
                    run.state == RunState.SUSPENDED
                    and info["purpose"] == "interaction:" + run.suspension_id
                )
            return run.state in TERMINAL_RUN_STATES
        except SageV2Error:
            return False
