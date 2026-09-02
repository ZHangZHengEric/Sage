from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any

import jwt

from app.server_v2.core.errors import ServerV2Error


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 210_000
    ).hex()
    return f"pbkdf2$210000${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt, digest = encoded.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), int(iterations)
    ).hex()
    return hmac.compare_digest(candidate, digest)


def create_access_token(
    *,
    user_id: str,
    username: str,
    role: str,
    secret: str,
    expire_hours: int,
) -> tuple[str, int]:
    expires_in = expire_hours * 3600
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": user_id,
            "userid": user_id,
            "username": username,
            "role": role,
            "iat": now,
            "exp": now + expires_in,
        },
        secret,
        algorithm="HS256",
    )
    return token, expires_in


def decode_access_token(token: str, *, secret: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise ServerV2Error(
            "unauthenticated", "session expired", detail="token expired"
        ) from exc
    except Exception as exc:
        raise ServerV2Error("unauthenticated", "invalid token") from exc
    if not claims.get("userid"):
        raise ServerV2Error("unauthenticated", "invalid token")
    return claims
