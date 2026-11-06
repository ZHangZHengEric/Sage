"""Identity facade: providers resolve internal users; sessions carry no authority."""

from dataclasses import replace

from app.v2.server.identity.federation import (
    ExternalIdentityService,
    ExternalIdentityStore,
)
from app.v2.server.identity.local import LocalPasswordAuth
from app.v2.server.identity.repository import UserStore
from app.v2.server.identity.sessions import LoginSessions, LoginSessionStore
from app.v2.server.identity.users import UserRecord
from app.v2.server.runtime.policy import ExecutionPolicy
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


class IdentityService:
    def __init__(
        self,
        users: UserStore,
        *,
        sessions: LoginSessionStore,
        external_identities: ExternalIdentityStore,
        jwt_secret: str,
        jwt_expire_hours: int,
    ) -> None:
        self.users = users
        self.local = LocalPasswordAuth(users)
        self.external = ExternalIdentityService(users, external_identities)
        self.sessions = LoginSessions(
            sessions, secret=jwt_secret, expire_hours=jwt_expire_hours
        )

    async def start(self) -> None:
        await self.local.start()

    async def close(self) -> None:
        await self.local.close()

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        return await self.users.get_by_id(user_id)

    async def set_execution_policy(
        self, user_id: str, policy: ExecutionPolicy
    ) -> UserRecord:
        user = await self.get_by_id(user_id)
        if user is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.identity.not_found",
                    category=ErrorCategory.AUTHORIZATION,
                    message="User no longer exists",
                )
            )
        updated = replace(user, execution_policy=policy)
        await self.users.save(updated)
        return updated

    async def from_token(self, token: str) -> UserRecord | None:
        session = await self.sessions.authenticate(token)
        return await self.get_by_id(session.user_id)

    async def issue_token(self, user: UserRecord) -> tuple[str, int]:
        return await self.sessions.issue(user)

    async def register(self, username: str, password: str) -> UserRecord:
        return await self.local.create(username, password)

    async def authenticate(self, username: str, password: str) -> UserRecord:
        return await self.local.authenticate(username, password)

    async def ensure_admin(self, username: str, password: str) -> UserRecord:
        return await self.local.ensure_admin(username, password)
