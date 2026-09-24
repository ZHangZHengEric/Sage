"""Account use cases. Password hashing stays here; the user store only persists rows."""

from __future__ import annotations

from app.server_v2.identity.jwt import hash_password, verify_password
from app.server_v2.identity.users import (
    Role,
    UserRecord,
    build_user_record,
    reject_duplicate_username,
    reject_second_admin,
)
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


class IdentityService:
    def __init__(self, users) -> None:
        self.users = users

    async def register(self, username: str, password: str) -> UserRecord:
        return await self._create(username, password, role="user")

    async def authenticate(self, username: str, password: str) -> UserRecord:
        user = await self.users.get_by_username(username)
        if user is None or not verify_password(password, user.password_hash):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.identity.service.unauthenticated",
                    category=ErrorCategory.AUTHENTICATION,
                    message="invalid username or password",
                )
            )
        return user

    async def ensure_admin(self, username: str, password: str) -> UserRecord:
        existing = await self.users.admin()
        if existing is not None:
            return existing
        named = await self.users.get_by_username(username)
        if named is not None:
            upgraded = UserRecord(
                user_id=named.user_id,
                username=named.username,
                password_hash=named.password_hash,
                role="admin",
            )
            await self.users.save(upgraded)
            return upgraded
        return await self._create(username, password, role="admin")

    async def _create(self, username: str, password: str, *, role: Role) -> UserRecord:
        if len(password) < 6:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.identity.service.validation",
                    category=ErrorCategory.VALIDATION,
                    message="password is too short",
                )
            )
        record = build_user_record(username, hash_password(password), role=role)
        reject_duplicate_username(await self.users.get_by_username(record.username))
        reject_second_admin(role, await self.users.admin())
        await self.users.save(record)
        return record
