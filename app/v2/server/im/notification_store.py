"""Run-bound notification intents and messages in the existing IM outbox."""

import time

from sqlalchemy import func, select

from .contracts import NOTIFY_KEY, NotificationRoute
from .orm import BindingRow, DeliveryRow
from .repository import error, key


def notification_key(command, owner):
    return key("run-notification", owner, command.session_id, command.idempotency_key)


class NotificationStore:
    def __init__(self, store):
        self.store = store
        self.database = store.database

    async def find(self, command, owner):
        async with self.database.session() as db:
            return await db.scalar(
                select(DeliveryRow).where(
                    DeliveryRow.source_key == notification_key(command, owner)
                )
            )

    @staticmethod
    async def valid(db, conn, route):
        binding = await db.get(BindingRow, route.binding_id)
        return bool(
            conn.enabled
            and conn.owner_id == route.owner_id
            and conn.id == route.connection_id
            and conn.auth_epoch == route.auth_epoch
            and conn.sender_id == route.sender_id
            and binding is not None
            and binding.connection_id == conn.id
            and binding.generation == route.generation
            and binding.sender_id == route.sender_id
            and binding.chat_id == route.chat_id
        )

    async def track(self, command, owner):
        route = NotificationRoute.model_validate(command.config.metadata[NOTIFY_KEY])
        source = notification_key(command, owner)
        digest = key([item.model_dump(mode="json") for item in command.input])
        async with self.store.locked(route.connection_id, owner=owner) as (db, conn):
            if not await self.valid(db, conn, route):
                raise error(
                    "notification_target_unavailable",
                    "IM 通知连接已停用、重置或尚未配对",
                )
            existing = await db.scalar(
                select(DeliveryRow).where(DeliveryRow.source_key == source)
            )
            if existing is not None:
                if (
                    existing.run_context["route"] != route.model_dump()
                    or existing.run_context["input_digest"] != digest
                ):
                    raise error(
                        "notification_conflict", "该任务已绑定其他通知目标或输入"
                    )
                if existing.state == "prepared":
                    existing.next_attempt = 0
                return existing
            count = await db.scalar(
                select(func.count())
                .select_from(DeliveryRow)
                .where(
                    DeliveryRow.connection_id == conn.id,
                    DeliveryRow.state == "prepared",
                )
            )
            if count >= 1000:
                raise error("notification_capacity", "IM 通知待处理队列已满")
            record = DeliveryRow(
                connection_id=conn.id,
                source_key=source,
                binding_id=route.binding_id,
                generation=route.generation,
                auth_epoch=route.auth_epoch,
                chat_id=route.chat_id,
                text="",
                state="prepared",
                created_at=time.time(),
                run_context={
                    "kind": "intent",
                    "session_id": command.session_id,
                    "idempotency_key": command.idempotency_key,
                    "run_id": "",
                    "route": route.model_dump(),
                    "input_digest": digest,
                    "draft_digest": "",
                },
            )
            db.add(record)
            await db.flush()
            return record

    async def prepare(self, record, run_id, content):
        async with self.store.locked(record.connection_id) as (db, conn):
            current = await db.get(DeliveryRow, record.id)
            route = NotificationRoute.model_validate(current.run_context["route"])
            if not await self.valid(db, conn, route):
                raise error(
                    "notification_target_unavailable", "IM 通知连接已停用或重置"
                )
            info = current.run_context
            digest = key(content)
            if info["run_id"] not in {"", run_id} or info["draft_digest"] not in {
                "",
                digest,
            }:
                raise error(
                    "notification_conflict",
                    "该任务已准备最终通知，请勿重复生成不同正文",
                )
            if not info["draft_digest"] and current.state != "prepared":
                raise error("notification_closed", "任务通知已结束")
            if current.state == "prepared":
                current.text = content
                current.run_context = {**info, "run_id": run_id, "draft_digest": digest}
            return {"notification_id": current.id, "status": "prepared"}

    async def waiting(self, cid):
        async with self.database.session() as db:
            return list(
                (
                    await db.scalars(
                        select(DeliveryRow)
                        .where(
                            DeliveryRow.connection_id == cid,
                            DeliveryRow.state == "prepared",
                            DeliveryRow.next_attempt <= time.time(),
                        )
                        .order_by(DeliveryRow.next_attempt, DeliveryRow.id)
                        .limit(32)
                    )
                ).all()
            )

    async def defer(self, record, worker, run_id="", *, delay=0.5):
        async with self.store.locked(record.connection_id, worker=worker) as (db, conn):
            current = await db.get(DeliveryRow, record.id)
            if current.state == "prepared":
                route = NotificationRoute.model_validate(current.run_context["route"])
                if not await self.valid(db, conn, route):
                    current.state, current.text, current.error = (
                        "projected",
                        "",
                        "notification_target_revoked",
                    )
                    return
                current.next_attempt = time.time() + delay
                if run_id:
                    current.run_context = {**current.run_context, "run_id": run_id}

    async def project(
        self,
        record,
        worker,
        run_id,
        text,
        *,
        final=False,
        completed=False,
        purpose="final",
        abandon="",
    ):
        async with self.store.locked(record.connection_id, worker=worker) as (db, conn):
            current = await db.get(DeliveryRow, record.id)
            if current.state != "prepared":
                return
            info = {**current.run_context, "run_id": run_id}
            route = NotificationRoute.model_validate(info["route"])
            if not abandon and await self.valid(db, conn, route):
                # Read the draft under the same lock as terminal projection. A
                # worker may have read its snapshot before the tool committed.
                content = current.text if completed and current.text else text
                for part, offset in enumerate(range(0, len(content), 2000)):
                    source = key(current.source_key, purpose, part)
                    if not await db.scalar(
                        select(DeliveryRow.id).where(DeliveryRow.source_key == source)
                    ):
                        db.add(
                            DeliveryRow(
                                connection_id=conn.id,
                                source_key=source,
                                binding_id=route.binding_id,
                                generation=route.generation,
                                auth_epoch=route.auth_epoch,
                                chat_id=route.chat_id,
                                text=content[offset : offset + 2000],
                                state="pending",
                                created_at=time.time(),
                                run_context={
                                    **info,
                                    "kind": "delivery",
                                    "purpose": purpose,
                                },
                            )
                        )
            if final or abandon:
                current.state, current.text, current.error = "projected", "", abandon
            current.next_attempt = time.time() + 0.5
            current.run_context = info
