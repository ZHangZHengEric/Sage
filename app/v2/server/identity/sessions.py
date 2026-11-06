"""Durable, revocable login sessions shared by password and future SSO logins."""

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import delete, update

from app.v2.server.database import Database
from app.v2.server.identity.jwt import create_access_token, decode_access_token
from app.v2.server.identity.orm import LoginSessionRow
from app.v2.server.identity.users import UserRecord
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


@dataclass(frozen=True, slots=True)
class LoginSession:
    session_id: str
    user_id: str
    expires_at: int
    revoked: bool = False


class LoginSessionStore(Protocol):
    async def create(self, record: LoginSession) -> None: ...
    async def get(self, session_id: str) -> LoginSession | None: ...
    async def revoke(self, session_id: str) -> None: ...


class DatabaseLoginSessionStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(self, record: LoginSession) -> None:
        async with self.database.transaction() as session:
            await session.execute(
                delete(LoginSessionRow).where(
                    LoginSessionRow.expires_at <= int(time.time())
                )
            )
            session.add(
                LoginSessionRow(
                    session_id=record.session_id,
                    user_id=record.user_id,
                    expires_at=record.expires_at,
                    revoked=record.revoked,
                )
            )

    async def get(self, session_id: str) -> LoginSession | None:
        async with self.database.session() as session:
            row = await session.get(LoginSessionRow, session_id)
        return (
            LoginSession(row.session_id, row.user_id, row.expires_at, row.revoked)
            if row
            else None
        )

    async def revoke(self, session_id: str) -> None:
        async with self.database.transaction() as session:
            await session.execute(
                update(LoginSessionRow)
                .where(LoginSessionRow.session_id == session_id)
                .values(revoked=True)
            )


class LoginSessions:
    def __init__(
        self, store: LoginSessionStore, *, secret: str, expire_hours: int
    ) -> None:
        self.store = store
        self._secret = secret
        self._expire_hours = expire_hours

    async def issue(self, user: UserRecord) -> tuple[str, int]:
        session_id = new_id("login")
        token, expires_in = create_access_token(
            user_id=user.user_id,
            username=user.username,
            role=user.role,
            session_id=session_id,
            secret=self._secret,
            expire_hours=self._expire_hours,
        )
        claims = decode_access_token(token, secret=self._secret)
        await self.store.create(
            LoginSession(session_id, user.user_id, int(claims["exp"]))
        )
        return token, expires_in

    async def authenticate(self, token: str) -> LoginSession:
        claims = decode_access_token(token, secret=self._secret)
        record = await self.store.get(str(claims["sid"]))
        if (
            record is None
            or record.revoked
            or record.expires_at <= int(time.time())
            or record.user_id != claims["userid"]
        ):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.identity.sessions.unauthenticated",
                    category=ErrorCategory.AUTHENTICATION,
                    message="session expired or revoked",
                )
            )
        return record

    def csrf_token(self, token: str) -> str:
        claims = decode_access_token(token, secret=self._secret)
        return hmac.new(
            self._secret.encode(),
            ("csrf:" + str(claims["sid"])).encode(),
            hashlib.sha256,
        ).hexdigest()

    async def revoke(self, token: str) -> None:
        record = await self.authenticate(token)
        await self.store.revoke(record.session_id)
