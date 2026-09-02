from __future__ import annotations

from typing import Protocol

from app.server_v2.core.database import Database
from sqlalchemy import select

from app.server_v2.db.models import UserRow
from app.server_v2.domain.users import (
    Role,
    UserRecord,
    build_user_record,
    reject_duplicate_username,
    reject_second_admin,
    require_valid_password,
)


class UserStore(Protocol):
    async def list_users(self) -> list[UserRecord]: ...
    async def get_by_username(self, username: str) -> UserRecord | None: ...
    async def get_by_id(self, user_id: str) -> UserRecord | None: ...
    async def admin(self) -> UserRecord | None: ...
    async def create(
        self, username: str, password: str, *, role: Role = "user"
    ) -> UserRecord: ...
    async def ensure_admin(self, username: str, password: str) -> UserRecord: ...
    async def authenticate(self, username: str, password: str) -> UserRecord: ...


class DatabaseUserStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def list_users(self) -> list[UserRecord]:
        async with self.database.session() as session:
            rows = list((await session.execute(select(UserRow))).scalars().all())
        return [_user_from_row(row) for row in rows]

    async def get_by_username(self, username: str) -> UserRecord | None:
        needle = username.strip().lower()
        return next(
            (user for user in await self.list_users() if user.username.lower() == needle),
            None,
        )

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        async with self.database.session() as session:
            row = await session.get(UserRow, user_id)
        return None if row is None else _user_from_row(row)

    async def admin(self) -> UserRecord | None:
        return next((user for user in await self.list_users() if user.role == "admin"), None)

    async def create(self, username: str, password: str, *, role: Role = "user") -> UserRecord:
        record = build_user_record(username, password, role=role)
        reject_duplicate_username(await self.get_by_username(record.username))
        reject_second_admin(role, await self.admin())
        await self._save(record)
        return record

    async def ensure_admin(self, username: str, password: str) -> UserRecord:
        existing = await self.admin()
        if existing is not None:
            return existing
        named = await self.get_by_username(username)
        if named is not None:
            upgraded = UserRecord(
                user_id=named.user_id,
                username=named.username,
                password_hash=named.password_hash,
                role="admin",
            )
            await self._save(upgraded)
            return upgraded
        return await self.create(username, password, role="admin")

    async def authenticate(self, username: str, password: str) -> UserRecord:
        return require_valid_password(await self.get_by_username(username), password)

    async def _save(self, user: UserRecord) -> None:
        async with self.database.transaction() as session:
            await session.merge(
                UserRow(
                    user_id=user.user_id,
                    username=user.username,
                    password_hash=user.password_hash,
                    role=user.role,
                )
            )


def _user_from_row(row: UserRow) -> UserRecord:
    return UserRecord(
        user_id=row.user_id,
        username=row.username,
        password_hash=row.password_hash,
        role="admin" if row.role == "admin" else "user",
    )
