from __future__ import annotations

import time
from typing import Any

import jwt

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


def create_access_token(
    *,
    user_id: str,
    session_id: str,
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
            "sid": session_id,
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
        claims = jwt.decode(token, secret, algorithms=["HS256"],
                            options={"require": ["exp", "iat", "sub", "userid", "sid"]})
    except jwt.ExpiredSignatureError as exc:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.identity.jwt.unauthenticated",
                category=ErrorCategory.AUTHENTICATION,
                message="session expired",
                metadata={"detail": "token expired"},
            )
        ) from exc
    except Exception as exc:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.identity.jwt.unauthenticated",
                category=ErrorCategory.AUTHENTICATION,
                message="invalid token",
            )
        ) from exc
    if not claims.get("userid") or not claims.get("sid"):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.identity.jwt.unauthenticated",
                category=ErrorCategory.AUTHENTICATION,
                message="invalid token",
            )
        )
    return claims
