from __future__ import annotations

from typing import Protocol

from app.server_v2.core.database import Database
from sqlalchemy import select

from app.server_v2.db.models import ThreadRow
from app.server_v2.domain.threads import (
    ThreadRecord,
    apply_thread_upsert,
    require_owned_thread,
)


class ThreadIndex(Protocol):
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

    async def list_all(self) -> list[ThreadRecord]:
        async with self.database.session() as session:
            rows = list((await session.execute(select(ThreadRow))).scalars().all())
        return sorted(
            [_thread_from_row(row) for row in rows],
            key=lambda item: item.updated_at,
            reverse=True,
        )

    async def list_for(self, user_id: str) -> list[ThreadRecord]:
        async with self.database.session() as session:
            rows = list(
                (
                    await session.execute(
                        select(ThreadRow).where(ThreadRow.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
        return sorted(
            [_thread_from_row(row) for row in rows],
            key=lambda item: item.updated_at,
            reverse=True,
        )

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
