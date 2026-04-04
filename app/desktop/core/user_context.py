import os
from typing import Any, Dict, Optional

from fastapi import Request


DEFAULT_DESKTOP_USER_ID = os.environ.get("SAGE_DESKTOP_USER_ID", "default_user")
DEFAULT_DESKTOP_USER_ROLE = os.environ.get("SAGE_DESKTOP_USER_ROLE", "admin")


def get_desktop_user_claims() -> Dict[str, Any]:
    return {
        "userid": DEFAULT_DESKTOP_USER_ID,
        "role": DEFAULT_DESKTOP_USER_ROLE,
    }


def get_desktop_user_id(request: Optional[Request] = None) -> str:
    if request is not None:
        claims = getattr(request.state, "user_claims", None) or {}
        user_id = str(claims.get("userid") or "").strip()
        if user_id:
            return user_id
    return DEFAULT_DESKTOP_USER_ID


def get_desktop_user_role(request: Optional[Request] = None) -> str:
    if request is not None:
        claims = getattr(request.state, "user_claims", None) or {}
        role = str(claims.get("role") or "").strip()
        if role:
            return role
    return DEFAULT_DESKTOP_USER_ROLE
