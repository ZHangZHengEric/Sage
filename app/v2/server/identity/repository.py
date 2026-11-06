from __future__ import annotations

from typing import Protocol

from app.v2.server.database import Database
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.v2.server.identity.orm import PasswordCredentialRow, UserRow
from app.v2.server.identity.users import (
    PasswordCredential, UserRecord, default_user_execution_policy,
    reject_duplicate_username, username_key,
)
from app.v2.server.runtime.policy import ExecutionPolicy


class UserStore(Protocol):
    async def list_users(self) -> list[UserRecord]: ...
    async def get_by_username(self, username: str) -> UserRecord | None: ...
    async def get_by_id(self, user_id: str) -> UserRecord | None: ...
    async def admin(self) -> UserRecord | None: ...
    async def save(self, user: UserRecord) -> None: ...
    async def create(self, user: UserRecord, credential: PasswordCredential | None = None) -> None: ...
    async def get_password_credential(self, user_id: str) -> PasswordCredential | None: ...


class DatabaseUserStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def list_users(self) -> list[UserRecord]:
        async with self.database.session() as session:
            rows = list((await session.execute(select(UserRow))).scalars().all())
        return [_user_from_row(row) for row in rows]

    async def get_by_username(self, username: str) -> UserRecord | None:
        async with self.database.session() as session:
            row = await session.scalar(select(UserRow).where(UserRow.username_key == username_key(username)))
        return None if row is None else _user_from_row(row)

    async def create(self, user: UserRecord, credential: PasswordCredential | None = None) -> None:
        try:
            async with self.database.transaction() as session:
                session.add(_user_row(user))
                if credential is not None:
                    session.add(PasswordCredentialRow(user_id=user.user_id, password_hash=credential.password_hash))
        except IntegrityError:
            # Also covers legacy MySQL collations whose username comparison is
            # stricter than our casefold key (for example accent-insensitive).
            reject_duplicate_username(user)

    async def get_password_credential(self, user_id: str) -> PasswordCredential | None:
        async with self.database.session() as session:
            row = await session.get(PasswordCredentialRow, user_id)
        return PasswordCredential(row.password_hash) if row is not None else None

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        async with self.database.session() as session:
            row = await session.get(UserRow, user_id)
        return None if row is None else _user_from_row(row)

    async def admin(self) -> UserRecord | None:
        async with self.database.session() as session:
            row = await session.scalar(select(UserRow).where(UserRow.role == "admin").limit(1))
        return None if row is None else _user_from_row(row)

    async def save(self, user: UserRecord) -> None:
        async with self.database.transaction() as session:
            row = await session.get(UserRow, user.user_id)
            if row is None:
                session.add(_user_row(user))
            else:
                row.username = user.username
                row.username_key = username_key(user.username)
                row.role = user.role
                row.execution_policy = user.execution_policy.model_dump_json()


def _user_row(user: UserRecord) -> UserRow:
    return UserRow(user_id=user.user_id, username=user.username, username_key=username_key(user.username),
                   role=user.role, execution_policy=user.execution_policy.model_dump_json())


def _user_from_row(row: UserRow) -> UserRecord:
    return UserRecord(
        user_id=row.user_id,
        username=row.username,
        role="admin" if row.role == "admin" else "user",
        execution_policy=(ExecutionPolicy.model_validate_json(row.execution_policy)
                          if row.execution_policy and row.execution_policy != "{}"
                          else default_user_execution_policy()),
    )
