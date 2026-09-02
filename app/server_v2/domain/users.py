from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sagents.v2.contracts.common import new_id

from app.server_v2.core.errors import ServerV2Error
from app.server_v2.core.jwt import hash_password, verify_password

Role = Literal["admin", "user"]


@dataclass(frozen=True, slots=True)
class UserRecord:
    user_id: str
    username: str
    password_hash: str
    role: Role = "user"

    def public_dict(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
        }


def build_user_record(
    username: str, password: str, *, role: Role = "user"
) -> UserRecord:
    name = username.strip()
    if len(name) < 2:
        raise ServerV2Error("validation", "username is too short")
    if len(password) < 6:
        raise ServerV2Error("validation", "password is too short")
    return UserRecord(
        user_id=new_id("user"),
        username=name,
        password_hash=hash_password(password),
        role=role,
    )


def reject_duplicate_username(existing: UserRecord | None) -> None:
    if existing is not None:
        raise ServerV2Error("conflict", "username already exists")


def reject_second_admin(role: Role, existing: UserRecord | None) -> None:
    if role == "admin" and existing is not None:
        raise ServerV2Error("conflict", "admin already exists")


def require_valid_password(user: UserRecord | None, password: str) -> UserRecord:
    if user is None or not verify_password(password, user.password_hash):
        raise ServerV2Error("unauthenticated", "invalid username or password")
    return user
