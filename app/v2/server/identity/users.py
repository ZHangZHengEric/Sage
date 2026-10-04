from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from app.v2.server.runtime.policy import ExecutionPolicy

from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

Role = Literal["admin", "user"]


@dataclass(frozen=True, slots=True)
class UserRecord:
    user_id: str
    username: str
    password_hash: str
    role: Role = "user"
    execution_policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)

    def public_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "execution_policy": self.execution_policy.model_dump(),
        }


def build_user_record(
    username: str, password_hash: str, *, role: Role = "user"
) -> UserRecord:
    name = username.strip()
    if len(name) < 2:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.identity.users.validation",
                category=ErrorCategory.VALIDATION,
                message="username is too short",
            )
        )
    return UserRecord(
        user_id=new_id("user"),
        username=name,
        password_hash=password_hash,
        role=role,
    )


def reject_duplicate_username(existing: UserRecord | None) -> None:
    if existing is not None:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.identity.users.conflict",
                category=ErrorCategory.CONFLICT,
                message="username already exists",
            )
        )


def reject_second_admin(role: Role, existing: UserRecord | None) -> None:
    if role == "admin" and existing is not None:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.identity.users.conflict",
                category=ErrorCategory.CONFLICT,
                message="admin already exists",
            )
        )
