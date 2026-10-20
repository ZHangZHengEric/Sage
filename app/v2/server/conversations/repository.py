from __future__ import annotations

from typing import Protocol

from app.v2.server.database import Database
from sqlalchemy import select, and_, or_, func
from sqlalchemy.exc import IntegrityError

from app.v2.server.conversations.bindings import SessionBinding, WorkspaceSessionPage, require_binding

from app.v2.server.conversations.orm import ThreadRow, SessionBindingRow
from app.v2.server.conversations.records import (
    ThreadRecord, ThreadPage, thread_cursor, parse_thread_cursor,
    apply_thread_upsert,
    require_owned_thread,
)


class ThreadIndex(Protocol):
    async def binding(self, session_id: str) -> SessionBinding | None: ...
    async def bind(self, binding: SessionBinding) -> None: ...
    async def page(self, *, user_id: str | None = None, limit: int = 50, cursor: str | None = None, search: str = "", agent_id: str = "", matching_agent_ids: tuple[str, ...] = ()) -> ThreadPage: ...
    async def scan_snapshot(self) -> tuple[str | None, int]: ...
    async def scan(self, *, limit: int = 100, cursor: str | None = None, user_id: str | None = None, through: str | None = None) -> ThreadPage: ...
    async def workspace_session_page(self, tenant_id: str, agent_id: str, *, owner_id: str, cursor: str | None = None, limit: int = 200) -> WorkspaceSessionPage: ...
    async def list_all(self) -> list[ThreadRecord]: ...
    async def list_for(self, user_id: str) -> list[ThreadRecord]: ...
    async def find(self, thread_id: str) -> ThreadRecord | None: ...
    async def upsert(
        self,
        thread_id: str,
        user_id: str,
        *,
        title: str = "",
        agent_id: str | None = None,
    ) -> ThreadRecord: ...
    async def remove(self, thread_id: str, user_id: str) -> None: ...


class DatabaseThreadIndex:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def binding(self, session_id: str) -> SessionBinding | None:
        async with self.database.session() as session:
            row = await session.get(SessionBindingRow, session_id)
            return None if row is None else SessionBinding(
                row.session_id, row.owner_id, row.tenant_id, row.agent_id,
            )

    async def bind(self, binding: SessionBinding) -> None:
        existing = await self.binding(binding.session_id)
        if existing is not None:
            require_binding(existing, binding)
            return
        try:
            async with self.database.transaction() as session:
                session.add(SessionBindingRow(**vars(binding)))
        except IntegrityError:
            # A concurrent claimant won. Never overwrite their identity.
            existing = await self.binding(binding.session_id)
            if existing is None:
                raise
            require_binding(existing, binding)

    async def page(self, *, user_id=None, limit=50, cursor=None, search="", agent_id="", matching_agent_ids=()):
        limit = max(1, min(int(limit), 200))
        statement = select(ThreadRow)
        if user_id is not None:
            statement = statement.where(ThreadRow.user_id == user_id)
        if agent_id:
            statement = statement.where(ThreadRow.agent_id == agent_id)
        if search.strip():
            needle = search.strip().lower().replace("/", "//").replace("%", "/%").replace("_", "/_")
            statement = statement.where(or_(
                func.lower(ThreadRow.title).like(f"%{needle}%", escape="/"),
                func.lower(ThreadRow.agent_id).like(f"%{needle}%", escape="/"),
                ThreadRow.agent_id.in_(matching_agent_ids),
            ))
        values = parse_thread_cursor(cursor)
        if values:
            updated_at, thread_id = values
            statement = statement.where(or_(ThreadRow.updated_at < updated_at,
                and_(ThreadRow.updated_at == updated_at, ThreadRow.thread_id < thread_id)))
        statement = statement.order_by(ThreadRow.updated_at.desc(), ThreadRow.thread_id.desc()).limit(limit + 1)
        async with self.database.session() as session:
            rows = [_thread_from_row(row) for row in (await session.execute(statement)).scalars()]
        return ThreadPage(items=rows[:limit], next_cursor=thread_cursor(rows[limit - 1]) if len(rows) > limit else None)

    async def scan_snapshot(self):
        """Freeze a scan's range and finite work allowance in one statement."""
        async with self.database.session() as session:
            row = (await session.execute(select(func.max(ThreadRow.thread_id), func.count()))).one()
            return row[0], int(row[1])

    async def scan(self, *, limit=100, cursor=None, user_id=None, through=None):
        """Stable primary-key traversal for maintenance, independent of updates."""
        limit = max(1, min(int(limit), 200))
        statement = select(ThreadRow)
        if user_id is not None:
            statement = statement.where(ThreadRow.user_id == user_id)
        if through is not None:
            statement = statement.where(ThreadRow.thread_id <= through)
        values = parse_thread_cursor(cursor, scan=True)
        if values:
            statement = statement.where(ThreadRow.thread_id > values[0])
        statement = statement.order_by(ThreadRow.thread_id).limit(limit + 1)
        async with self.database.session() as session:
            rows = [_thread_from_row(row) for row in (await session.execute(statement)).scalars()]
        return ThreadPage(items=rows[:limit], next_cursor=thread_cursor(rows[limit - 1], scan=True) if len(rows) > limit else None)

    async def workspace_session_page(self, tenant_id, agent_id, *, owner_id, cursor=None, limit=200):
        """Traverse claims, then bounded legacy candidates with an opaque cursor.

        Advance over claimed Thread rows as well: filtering them before LIMIT
        would rescan an entire empty legacy tail on every claim page.
        """
        limit = max(1, min(int(limit), 200))
        phase, _, after = (cursor or 'claims:').partition(':')
        if phase not in {'claims', 'legacy'}:
            raise ValueError('invalid workspace cursor')
        claimed = []
        async with self.database.session() as session:
            if phase == 'claims':
                statement = select(SessionBindingRow.session_id).where(
                    SessionBindingRow.owner_id == owner_id, SessionBindingRow.tenant_id == tenant_id,
                    SessionBindingRow.agent_id == agent_id, SessionBindingRow.session_id > after,
                ).order_by(SessionBindingRow.session_id).limit(limit + 1)
                rows = list((await session.execute(statement)).scalars())
                claimed = rows[:limit]
                if len(rows) > limit:
                    return WorkspaceSessionPage(claimed, [], 'claims:' + claimed[-1])
                after = ''
                if len(claimed) == limit:
                    return WorkspaceSessionPage(claimed, [], 'legacy:')
            remaining = limit - len(claimed)
            bound = select(SessionBindingRow.session_id).where(
                SessionBindingRow.session_id == ThreadRow.thread_id).exists()
            statement = select(ThreadRow.thread_id, bound.label('bound')).where(
                ThreadRow.user_id == owner_id, ThreadRow.agent_id == agent_id, ThreadRow.thread_id > after,
            ).order_by(ThreadRow.thread_id).limit(remaining + 1)
            rows = list((await session.execute(statement)).all())
        candidates = rows[:remaining]
        return WorkspaceSessionPage(claimed, [row.thread_id for row in candidates if not row.bound],
            'legacy:' + candidates[-1].thread_id if len(rows) > remaining else None)

    async def list_all(self) -> list[ThreadRecord]:
        async with self.database.session() as session:
            rows = list((await session.execute(select(ThreadRow).order_by(ThreadRow.updated_at.desc(), ThreadRow.thread_id.desc()))).scalars().all())
        return [_thread_from_row(row) for row in rows]

    async def list_for(self, user_id: str) -> list[ThreadRecord]:
        async with self.database.session() as session:
            rows = list(
                (
                    await session.execute(
                        select(ThreadRow).where(ThreadRow.user_id == user_id).order_by(ThreadRow.updated_at.desc(), ThreadRow.thread_id.desc())
                    )
                )
                .scalars()
                .all()
            )
        return [_thread_from_row(row) for row in rows]

    async def find(self, thread_id: str) -> ThreadRecord | None:
        async with self.database.session() as session:
            row = await session.get(ThreadRow, thread_id)
        return None if row is None else _thread_from_row(row)

    async def upsert(
        self,
        thread_id: str,
        user_id: str,
        *,
        title: str = "",
        agent_id: str | None = None,
    ) -> ThreadRecord:
        existing = await self.find(thread_id)
        record = apply_thread_upsert(
            existing,
            thread_id=thread_id,
            user_id=user_id,
            title=title,
            agent_id=agent_id,
        )
        async with self.database.transaction() as session:
            await session.merge(
                ThreadRow(
                    thread_id=record.thread_id,
                    user_id=record.user_id,
                    title=record.title,
                    agent_id=record.agent_id,
                    updated_at=record.updated_at,
                )
            )
        return record

    async def remove(self, thread_id: str, user_id: str) -> None:
        require_owned_thread(await self.find(thread_id), user_id)
        async with self.database.transaction() as session:
            row = await session.get(ThreadRow, thread_id)
            if row is not None:
                await session.delete(row)


def _thread_from_row(row: ThreadRow) -> ThreadRecord:
    return ThreadRecord(
        thread_id=row.thread_id,
        user_id=row.user_id,
        title=row.title,
        agent_id=getattr(row, "agent_id", "") or "",
        updated_at=row.updated_at,
    )
