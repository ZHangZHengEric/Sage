from typing import Optional

from fastapi import Request


def get_request_claims(request: Request) -> dict:
    return getattr(request.state, "user_claims", {}) or {}


def get_request_user_id(request: Request, default: str = "") -> str:
    claims = get_request_claims(request)
    return claims.get("userid") or default


def get_request_role(request: Request, default: str = "user") -> str:
    claims = get_request_claims(request)
    return claims.get("role") or default


def get_target_user_id_for_role(
    request: Request,
    *,
    fallback_user_id: Optional[str] = None,
) -> Optional[str]:
    role = get_request_role(request)
    if role == "admin":
        return None
    return get_request_user_id(request, fallback_user_id or "")
