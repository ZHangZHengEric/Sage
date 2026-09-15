"""AgentManagement store over the Server database; single-writer host contract."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager

from sqlalchemy import select

from app.server_v2.db.models import ManagedRecordRow as Row
from sagents.v2.agent.management import AgentPackageBundle


def key(owner, kind, *parts):
    return hashlib.sha256(json.dumps([owner, kind, *parts]).encode()).hexdigest()


class DatabasePackageStore:
    def __init__(self, database):
        self.database = database
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def transaction(self):
        # The Server's SessionStore enforces one writer process. Serialize CAS
        # and first inserts inside this host; do not claim distributed locking.
        async with self._lock:
            async with self.database.transaction() as db:
                yield db

    async def _get(self, db, owner, kind, *parts):
        return await db.get(Row, key(owner, kind, *parts))

    async def _put(self, db, owner, kind, parts, payload, **indices):
        await db.merge(
            Row(
                key=key(owner, kind, *parts),
                owner=owner,
                kind=kind,
                payload=payload,
                **indices,
            )
        )
        await db.flush()

    async def version_ref(self, owner, package, version):
        async with self.transaction() as db:
            row = await self._get(db, owner, "version", package, version)
            return row.payload["ref"] if row else None

    async def save(self, owner, bundle):
        meta, ref = bundle.manifest.metadata, bundle.content_hash
        async with self.transaction() as db:
            old = await self._get(db, owner, "version", meta.id, meta.version)
            if old and old.payload["ref"] != ref:
                raise ValueError("package version is immutable; choose a new version")
            await self._put(db, owner, "version", [meta.id, meta.version], {"ref": ref})
            await self._put(
                db,
                owner,
                "bundle",
                [ref],
                bundle.model_dump(mode="json"),
                ref=ref,
                name=f"{meta.id}:{meta.version}",
            )
        return ref

    async def get(self, owner, ref):
        async with self.transaction() as db:
            row = await self._get(db, owner, "bundle", ref)
            if row is None:
                raise ValueError("agent package not found in caller scope")
            return AgentPackageBundle.model_validate(row.payload)

    async def list(self, owner, *, limit=50, offset=0):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid inventory pagination")
        async with self.transaction() as db:
            rows = (
                await db.scalars(
                    select(Row)
                    .where(Row.owner == owner, Row.kind == "bundle")
                    .order_by(Row.name, Row.key)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            result = []
            for row in rows:
                meta = row.payload["manifest"]["metadata"]
                active = await self._get(db, owner, "active", meta["id"])
                result.append(
                    dict(
                        ref=row.ref,
                        package=meta["id"],
                        version=meta["version"],
                        active=bool(active and active.payload["ref"] == row.ref),
                        active_ref=active.payload["ref"] if active else None,
                    )
                )
            return result

    async def activate(self, owner, ref, expected_ref):
        async with self.transaction() as db:
            bundle = await self._get(db, owner, "bundle", ref)
            if bundle is None:
                raise ValueError("agent package not found in caller scope")
            package = bundle.payload["manifest"]["metadata"]["id"]
            old = await self._get(db, owner, "active", package)
            current = old.payload["ref"] if old else None
            if current != expected_ref:
                raise ValueError(
                    "active version conflict; refresh inventory before retrying"
                )
            await self._put(db, owner, "active", [package], {"ref": ref})
            return dict(ref=ref, previous_ref=current, package=package)

    async def invocation(
        self, owner, operation, ref=None, agent=None, request=None, handle=None
    ):
        async with self.transaction() as db:
            row = await self._get(db, owner, "invocation", operation)
            value = dict(row.payload) if row else None
            if (
                value
                and request is not None
                and (value["ref"], value["agent"], value["request"])
                != (ref, agent, request)
            ):
                raise ValueError("operation key reused with different invocation")
            if value is None:
                if request is None:
                    raise ValueError("invocation not found in caller scope")
                value = dict(
                    owner=owner,
                    operation=operation,
                    ref=ref,
                    agent=agent,
                    request=request,
                    handle=None,
                )
            if handle is not None:
                value["handle"] = handle
            if request is not None or handle is not None:
                await self._put(
                    db,
                    owner,
                    "invocation",
                    [operation],
                    value,
                    name=operation,
                    ref=value["ref"],
                    agent=value["agent"],
                    session_key=hashlib.sha256(
                        value["handle"]["session_id"].encode()
                    ).hexdigest()
                    if value["handle"]
                    else "",
                )
            return value

    async def reply_command(self, owner, operation, interaction, request, command=None):
        async with self.transaction() as db:
            parts = [operation, interaction, request]
            row = await self._get(db, owner, "reply", *parts)
            if row:
                return row.payload
            if command is not None:
                await self._put(db, owner, "reply", parts, command)
            return command

    async def discard_stale_reply(
        self, owner, operation, interaction, request, command
    ):
        async with self.transaction() as db:
            row = await self._get(db, owner, "reply", operation, interaction, request)
            if row and row.payload == command:
                await db.delete(row)

    async def owns_session(self, owner, ref, agent, session_id):
        async with self.transaction() as db:
            statement = (
                select(Row.key)
                .where(
                    Row.owner == owner,
                    Row.kind == "invocation",
                    Row.ref == ref,
                    Row.agent == agent,
                    Row.session_key == hashlib.sha256(session_id.encode()).hexdigest(),
                )
                .limit(1)
            )
            return (await db.scalar(statement)) is not None

    async def terminal_status(self, owner, operation, *, value=None):
        async with self.transaction() as db:
            if value is not None:
                row = await self._get(db, owner, "invocation", operation)
                record = row.payload if row else {}
                handle = record.get("handle") or {}
                if (
                    not value.get("terminal")
                    or value.get("operation") != operation
                    or value.get("ref") != record.get("ref")
                    or value.get("run", {}).get("run_id") != handle.get("run_id")
                    or not handle
                ):
                    raise ValueError("terminal result does not match invocation")
                await self._put(
                    db, owner, "terminal", [operation], value, name=operation
                )
            row = await self._get(db, owner, "terminal", operation)
            return row.payload if row else None

    async def unarchived_invocations(self, owner, ref, agent, *, after="", limit=100):
        if not 1 <= limit <= 100:
            raise ValueError("invalid invocation page size")
        from sqlalchemy.orm import aliased

        terminal = aliased(Row)
        async with self.transaction() as db:
            archived = (
                select(terminal.key)
                .where(
                    terminal.owner == Row.owner,
                    terminal.kind == "terminal",
                    terminal.name == Row.name,
                )
                .exists()
            )
            statement = (
                select(Row)
                .where(
                    Row.owner == owner,
                    Row.kind == "invocation",
                    Row.ref == ref,
                    Row.agent == agent,
                    Row.name > after,
                    Row.session_key != "",
                    ~archived,
                )
                .order_by(Row.name)
                .limit(limit)
            )
            return [row.payload for row in (await db.scalars(statement)).all()]

    async def history_location(self, owner, ref, agent, *, root=None):
        async with self.transaction() as db:
            if root is not None:
                await self._put(db, owner, "history", [ref, agent], {"root": str(root)})
            row = await self._get(db, owner, "history", ref, agent)
            return row.payload["root"] if row else None

    async def list_invocations(self, owner, *, limit=50, offset=0):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid invocation pagination")
        async with self.transaction() as db:
            rows = (
                await db.scalars(
                    select(Row)
                    .where(Row.owner == owner, Row.kind == "invocation")
                    .order_by(Row.name.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return [
                {
                    field: row.payload[field]
                    for field in ("operation", "ref", "agent", "handle")
                }
                for row in rows
            ]
