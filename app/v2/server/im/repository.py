"""Bounded durable inbox/outbox with connection-level serialization and fencing."""

import hashlib
import hmac
import json
import secrets
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from .orm import BindingRow, ConnectionRow, DeliveryRow, InboxRow


def key(*values):
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def error(code, message, category=ErrorCategory.VALIDATION):
    return SageV2Error(
        RuntimeErrorInfo(code="server.im." + code, message=message, category=category)
    )


class IMStore:
    def __init__(self, database):
        self.database = database

    @asynccontextmanager
    async def locked(self, cid, *, owner=None, worker=None):
        async with self.database.transaction() as db:
            # SQLite has no row-level FOR UPDATE; a harmless write acquires its
            # writer lock before any read. MySQL uses a row lock instead.
            if db.bind.dialect.name == "sqlite":
                from sqlalchemy import update

                await db.execute(
                    update(ConnectionRow).where(ConnectionRow.id == cid).values(id=cid)
                )
            conn = await db.scalar(
                select(ConnectionRow).where(ConnectionRow.id == cid).with_for_update()
            )
            if conn is None or (owner is not None and conn.owner_id != owner):
                raise error("not_found", "IM connection not found")
            if worker is not None and (
                conn.lease_token != worker or conn.lease_until <= time.time()
            ):
                raise error(
                    "lease_lost", "IM worker lease expired", ErrorCategory.CONFLICT
                )
            yield db, conn

    async def get(self, cid, owner=None):
        async with self.database.session() as db:
            row = await db.get(ConnectionRow, cid)
            if row is None or (owner is not None and row.owner_id != owner):
                raise error("not_found", "IM connection not found")
            return row

    async def list_connections(self, owner=None):
        async with self.database.session() as db:
            stmt = select(ConnectionRow).order_by(ConnectionRow.id).limit(200)
            if owner is not None:
                stmt = stmt.where(ConnectionRow.owner_id == owner)
            return list((await db.scalars(stmt)).all())

    async def create(self, owner, agent, name, config):
        row = ConnectionRow(
            id="im_" + uuid4().hex,
            owner_id=owner,
            agent_id=agent,
            name=name,
            account_key=key("feishu", config["app_id"], config["tenant_key"]),
            config=config,
        )
        try:
            async with self.database.transaction() as db:
                db.add(row)
                await db.flush()
        except IntegrityError:
            raise error(
                "account_conflict",
                "This Feishu app is already configured",
                ErrorCategory.CONFLICT,
            ) from None
        return row

    async def set_enabled(self, cid, owner, revision, enabled):
        async with self.locked(cid, owner=owner) as (_, conn):
            if conn.revision != revision:
                raise error(
                    "revision_conflict",
                    "Connection changed; refresh before saving",
                    ErrorCategory.CONFLICT,
                )
            conn.enabled = enabled
            conn.revision += 1
            conn.auth_epoch += 1
            return conn

    async def pairing(self, cid, owner):
        code = secrets.token_urlsafe(24)
        async with self.locked(cid, owner=owner) as (_, conn):
            if not conn.enabled:
                raise error("disabled", "Enable this connection before pairing")
            if conn.sender_id:
                raise error(
                    "already_paired",
                    "Connection is already paired",
                    ErrorCategory.CONFLICT,
                )
            conn.pairing_hash = key(code)
            conn.pairing_until = time.time() + 600
            conn.pairing_attempts = 0
        return {"code": code, "expires_in": 600, "command": "/pair " + code}

    async def accept(self, cid, event):
        async with self.locked(cid) as (db, conn):
            if not conn.enabled:
                return
            mk, ek = key(cid, event.message_id), key(cid, event.event_id)
            # Event IDs can change on delivery; message identity is independent.
            digest = key(event.message_id, event.sender_id, event.chat_id, event.text)
            existing = await db.scalar(
                select(InboxRow).where(
                    or_(InboxRow.message_key == mk, InboxRow.event_key == ek)
                )
            )
            if existing is not None:
                if existing.digest != digest:
                    raise error(
                        "event_conflict",
                        "Event identity has conflicting content",
                        ErrorCategory.CONFLICT,
                    )
                return
            pairing = event.text.startswith("/pair ")
            if pairing:
                if (
                    conn.sender_id
                    or conn.pairing_until < time.time()
                    or conn.pairing_attempts >= 5
                ):
                    return
                conn.pairing_attempts += 1
                if not hmac.compare_digest(
                    conn.pairing_hash, key(event.text[6:].strip())
                ):
                    return
                conn.sender_id = event.sender_id
                conn.pairing_hash, conn.pairing_until = "", 0
                conn.auth_epoch += 1
            if not conn.sender_id or conn.sender_id != event.sender_id:
                return
            bid = key(cid, event.sender_id, event.chat_id)
            binding = await db.get(BindingRow, bid)
            if binding is None:
                binding = BindingRow(
                    id=bid,
                    connection_id=cid,
                    chat_id=event.chat_id,
                    sender_id=event.sender_id,
                    session_id="im_session_" + uuid4().hex,
                    generation=1,
                )
                db.add(binding)
            if event.text.strip() == "/new":
                binding.session_id = "im_session_" + uuid4().hex
                binding.generation += 1
            count = await db.scalar(
                select(func.count())
                .select_from(InboxRow)
                .where(
                    InboxRow.connection_id == cid,
                    InboxRow.state.in_(["pending", "watching"]),
                )
            )
            if count >= 1000 and not event.text.strip().startswith("/"):
                raise error(
                    "busy", "IM pending queue is full", ErrorCategory.RATE_LIMITED
                )
            kind = "message"
            reply = ""
            if pairing:
                kind, reply = "pair", "身份绑定成功，可以开始私聊。"
            elif event.text.strip() == "/new":
                kind, reply = "new", "已开启新会话。"
            elif event.text.strip() == "/stop":
                kind = "stop"
                target = await db.scalar(
                    select(InboxRow)
                    .where(
                        InboxRow.connection_id == cid,
                        InboxRow.session_id == binding.session_id,
                        InboxRow.state.in_(["pending", "watching"]),
                    )
                    .order_by((InboxRow.state == "watching").desc(), InboxRow.id)
                    .limit(1)
                )
                if target:
                    target.cancel_requested = True
                reply = "取消请求已提交。" if target else "当前没有运行中的任务。"
            elif event.text.strip().startswith("/"):
                kind, reply = "help", "命令：/new 新会话；/stop 取消当前任务。"
            row = InboxRow(
                connection_id=cid,
                message_key=mk,
                event_key=ek,
                digest=digest,
                binding_id=bid,
                session_id=binding.session_id,
                generation=binding.generation,
                auth_epoch=conn.auth_epoch,
                sender_id=event.sender_id,
                chat_id=event.chat_id,
                kind=kind,
                text=event.text if kind == "message" else "",
                state="pending" if kind == "message" else "complete",
                created_at=time.time(),
            )
            db.add(row)
            await db.flush()
            if reply:
                await self.enqueue(db, row, "command", reply)

    async def claim(self, cid, worker):
        async with self.locked(cid) as (db, conn):
            now = time.time()
            if not conn.enabled or (
                conn.lease_until > now and conn.lease_token != worker
            ):
                return False
            if conn.lease_token != worker or conn.lease_until <= now:
                rows = await db.scalars(
                    select(DeliveryRow).where(
                        DeliveryRow.connection_id == cid, DeliveryRow.state == "sending"
                    )
                )
                for row in rows:
                    row.state, row.error = "unknown", "worker_lost_during_send"
                    row.revision += 1
            conn.lease_token, conn.lease_until = worker, now + 60
            return True

    async def inboxes(self, cid, active=False):
        async with self.database.session() as db:
            stmt = (
                select(InboxRow)
                .where(InboxRow.connection_id == cid)
                .order_by(InboxRow.id)
            )
            if active:
                stmt = stmt.where(
                    InboxRow.state.in_(["pending", "watching"]),
                    InboxRow.next_attempt <= time.time(),
                )
            return list(
                (await db.scalars(stmt.limit(1000 if not active else 32))).all()
            )

    async def binding(self, bid):
        async with self.database.session() as db:
            return await db.get(BindingRow, bid)

    async def change_inbox(self, row, worker, **values):
        async with self.locked(row.connection_id, worker=worker) as (db, _):
            current = await db.get(InboxRow, row.id)
            for name, value in values.items():
                setattr(current, name, value)

    async def enqueue(self, db, source, purpose, text):
        # Freeze chunk boundaries and UUIDs once; retries never re-render.
        for part, start in enumerate(range(0, len(text), 2000)):
            source_key = key(source.message_key, purpose, part)
            if await db.scalar(
                select(DeliveryRow.id).where(DeliveryRow.source_key == source_key)
            ):
                continue
            db.add(
                DeliveryRow(
                    connection_id=source.connection_id,
                    source_key=source_key,
                    binding_id=source.binding_id,
                    generation=source.generation,
                    auth_epoch=source.auth_epoch,
                    chat_id=source.chat_id,
                    text=text[start : start + 2000],
                    state="pending",
                    created_at=time.time(),
                )
            )

    async def project(self, row, worker, purpose, text, *, final=False):
        async with self.locked(row.connection_id, worker=worker) as (db, conn):
            current = await db.get(InboxRow, row.id)
            binding = await db.get(BindingRow, row.binding_id)
            valid = (
                conn.enabled
                and conn.auth_epoch == row.auth_epoch
                and binding is not None
                and binding.generation == row.generation
            )
            if valid and text:
                await self.enqueue(db, current, purpose, text)
            if final:
                current.state = "complete" if valid else "superseded"
                current.text, current.command = "", None

    async def next_delivery(self, cid, worker):
        async with self.locked(cid, worker=worker) as (db, conn):
            # Unknown/failed pieces hold subsequent pieces for this destination.
            rows = await db.scalars(
                select(DeliveryRow)
                .where(
                    DeliveryRow.connection_id == cid,
                    DeliveryRow.state.in_(["pending", "sending", "unknown", "failed"]),
                )
                .order_by(DeliveryRow.id)
                .limit(100)
            )
            blocked = set()
            for row in rows:
                binding = await db.get(BindingRow, row.binding_id)
                if (
                    not conn.enabled
                    or conn.auth_epoch != row.auth_epoch
                    or binding is None
                    or binding.generation != row.generation
                ):
                    row.state, row.text = "superseded", ""
                    row.revision += 1
                    continue
                if row.chat_id in blocked:
                    continue
                blocked.add(row.chat_id)
                if row.state != "pending" or row.next_attempt > time.time():
                    continue
                row.state = "sending"
                row.revision += 1
                row.attempts += 1
                await db.flush()
                return row

    async def finish_delivery(
        self, row, worker, state, *, code="", receipt="", delay=0
    ):
        async with self.locked(row.connection_id, worker=worker) as (db, _):
            current = await db.get(DeliveryRow, row.id)
            current.state, current.error, current.receipt = state, code, receipt
            current.revision += 1
            current.next_attempt = time.time() + delay
            if state in ("platform_accepted", "superseded"):
                current.text = ""

    async def deliveries(self, cid, *, after=0, limit=50):
        async with self.database.session() as db:
            return list(
                (
                    await db.scalars(
                        select(DeliveryRow)
                        .where(DeliveryRow.connection_id == cid, DeliveryRow.id > after)
                        .order_by(DeliveryRow.id)
                        .limit(limit)
                    )
                ).all()
            )

    async def cleanup(self, cid, worker):
        async with self.locked(cid, worker=worker) as (db, _):
            cutoff = time.time() - 7 * 86400
            # Retain dedupe identities seven days, independent of conversation resets.
            await db.execute(
                delete(InboxRow).where(
                    InboxRow.connection_id == cid,
                    InboxRow.created_at < cutoff,
                    InboxRow.state.in_(["complete", "superseded", "failed"]),
                )
            )
            await db.execute(
                delete(DeliveryRow).where(
                    DeliveryRow.connection_id == cid,
                    DeliveryRow.created_at < cutoff,
                    DeliveryRow.state.in_(["platform_accepted", "superseded"]),
                )
            )
