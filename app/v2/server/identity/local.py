"""Local password authentication. Independent from login sessions and SSO."""

from app.v2.server.identity.passwords import (
    PasswordExecutor,
    hash_password,
    verify_password,
)
from app.v2.server.identity.repository import UserStore
from app.v2.server.identity.users import (
    PasswordCredential,
    Role,
    UserRecord,
    build_user_record,
    reject_duplicate_username,
    reject_second_admin,
)
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


class LocalPasswordAuth:
    def __init__(self, users: UserStore) -> None:
        self.users = users
        self._passwords = PasswordExecutor()

    async def start(self) -> None:
        if self._passwords.closed:
            await self._passwords.close()
            self._passwords = PasswordExecutor()

    async def close(self) -> None:
        await self._passwords.close()

    async def authenticate(self, username: str, password: str) -> UserRecord:
        user = await self.users.get_by_username(username)
        credential = (
            await self.users.get_password_credential(user.user_id) if user else None
        )
        if credential is None or not await self._passwords.run(
            verify_password, password, credential.password_hash
        ):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.identity.local.unauthenticated",
                    category=ErrorCategory.AUTHENTICATION,
                    message="invalid username or password",
                )
            )
        return user

    async def create(
        self, username: str, password: str, *, role: Role = "user"
    ) -> UserRecord:
        if len(password) < 6:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.identity.local.validation",
                    category=ErrorCategory.VALIDATION,
                    message="password is too short",
                )
            )
        record = build_user_record(username, role=role)
        reject_duplicate_username(await self.users.get_by_username(record.username))
        reject_second_admin(role, await self.users.admin())
        credential = PasswordCredential(
            await self._passwords.run(hash_password, password)
        )
        await self.users.create(record, credential)
        return record

    async def ensure_admin(self, username: str, password: str) -> UserRecord:
        existing = await self.users.admin()
        if existing is not None:
            return existing
        # Never turn a pre-existing unprivileged identity into an administrator.
        named = await self.users.get_by_username(username)
        if named is not None and named.role == "admin":
            return named
        reject_duplicate_username(named)
        if not password:
            raise ValueError(
                "SAGE_SERVER_ADMIN_PASSWORD is required to create the initial administrator"
            )
        try:
            return await self.create(username, password, role="admin")
        except SageV2Error as exc:
            if exc.info.category == ErrorCategory.CONFLICT:
                # Another worker may have created the configured admin first.
                existing = await self.users.admin()
                if existing is not None:
                    return existing
            raise
