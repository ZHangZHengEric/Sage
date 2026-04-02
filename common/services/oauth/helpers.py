from typing import Dict

from argon2 import PasswordHasher

from common.models.user import User

_PASSWORD_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    return _PASSWORD_HASHER.hash(password)


def build_user_claims(user: User) -> Dict[str, str]:
    return {
        "userid": user.user_id,
        "username": user.username,
        "nickname": user.nickname or user.username,
        "phonenum": user.phonenum or "",
        "email": user.email or "",
        "role": user.role,
        "avatar": user.avatar_url or "",
        "avatar_url": user.avatar_url or "",
    }


__all__ = [
    "build_user_claims",
    "hash_password",
]
