"""Account use cases. Password hashing stays here; the user store only persists rows."""

from __future__ import annotations

from app.server_v2.identity.jwt import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.server_v2.identity.users import (
    Role,
    UserRecord,
    build_user_record,
    reject_duplicate_username,
    reject_second_admin,
)
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


class IdentityService:
    def __init__(self, users, *, jwt_secret: str, jwt_expire_hours: int) -> None:
        self.users = users
        self._jwt_secret = jwt_secret
        self._jwt_expire_hours = jwt_expire_hours

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        return await self.users.get_by_id(user_id)

    async def from_token(self, token: str) -> UserRecord | None:
        claims = decode_access_token(token, secret=self._jwt_secret)
        return await self.get_by_id(str(claims.get("userid") or ""))

    def issue_token(self, user: UserRecord) -> tuple[str, int]:
        return create_access_token(
            user_id=user.user_id,
            username=user.username,
            role=user.role,
            secret=self._jwt_secret,
            expire_hours=self._jwt_expire_hours,
        )

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
