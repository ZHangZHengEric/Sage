"""Account use cases. Password hashing stays here; the user store only persists rows."""

from __future__ import annotations

from app.server_v2.core.errors import ServerV2Error
from app.server_v2.core.jwt import hash_password, verify_password
from app.server_v2.domain.users import (
    Role,
    UserRecord,
    build_user_record,
    reject_duplicate_username,
    reject_second_admin,
)


class IdentityService:
    def __init__(self, users) -> None:
        self.users = users

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        return await self.users.get_by_id(user_id)

    async def register(self, username: str, password: str) -> UserRecord:
        return await self._create(username, password, role="user")

    async def authenticate(self, username: str, password: str) -> UserRecord:
        user = await self.users.get_by_username(username)
        if user is None or not verify_password(password, user.password_hash):
            raise ServerV2Error("unauthenticated", "invalid username or password")
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

    async def _create(
        self, username: str, password: str, *, role: Role
    ) -> UserRecord:
        if len(password) < 6:
            raise ServerV2Error("validation", "password is too short")
        record = build_user_record(username, hash_password(password), role=role)
        reject_duplicate_username(await self.users.get_by_username(record.username))
        reject_second_admin(role, await self.users.admin())
        await self.users.save(record)
        return record
