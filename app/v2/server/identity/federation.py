"""Trusted SSO adapters bind verified (issuer, subject) to internal user IDs.

This module does not verify provider tokens. No email/username auto-linking or
public binding endpoint is provided: adapters must verify claims and authorize
account linking before calling bind.
"""

import hashlib
import json
from typing import Protocol

from sqlalchemy.exc import IntegrityError

from app.v2.server.database import Database
from app.v2.server.identity.orm import ExternalIdentityRow
from app.v2.server.identity.repository import UserStore
from app.v2.server.identity.users import UserRecord
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


def _identity_key(issuer: str, subject: str) -> str:
    if not issuer or not subject:
        raise ValueError("issuer and subject are required")
    return hashlib.sha256(
        json.dumps([issuer, subject], ensure_ascii=False).encode()
    ).hexdigest()


class ExternalIdentityStore(Protocol):
    async def get_user_id(self, issuer: str, subject: str) -> str | None: ...
    async def bind(self, issuer: str, subject: str, user_id: str) -> None: ...


class DatabaseExternalIdentityStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_user_id(self, issuer: str, subject: str) -> str | None:
        async with self.database.session() as session:
            row = await session.get(ExternalIdentityRow, _identity_key(issuer, subject))
        return row.user_id if row else None

    async def bind(self, issuer: str, subject: str, user_id: str) -> None:
        try:
            async with self.database.transaction() as session:
                session.add(
                    ExternalIdentityRow(
                        identity_key=_identity_key(issuer, subject),
                        issuer=issuer,
                        subject=subject,
                        user_id=user_id,
                    )
                )
        except IntegrityError:
            if await self.get_user_id(issuer, subject) != user_id:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="server.identity.federation.conflict",
                        category=ErrorCategory.CONFLICT,
                        message="external identity is already bound",
                    )
                ) from None


class ExternalIdentityService:
    def __init__(self, users: UserStore, store: ExternalIdentityStore) -> None:
        self.users = users
        self.store = store

    async def resolve(self, issuer: str, subject: str) -> UserRecord | None:
        user_id = await self.store.get_user_id(issuer, subject)
        return await self.users.get_by_id(user_id) if user_id else None

    async def bind(self, issuer: str, subject: str, user_id: str) -> None:
        if await self.users.get_by_id(user_id) is None:
            raise ValueError("cannot bind an unknown user")
        await self.store.bind(issuer, subject, user_id)
