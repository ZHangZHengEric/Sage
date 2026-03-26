import json
import re
import secrets
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import Request
from loguru import logger

from ..core import config
from ..core.exceptions import SageHTTPException
from ..models.user import User, UserDao, UserExternalIdentity, UserExternalIdentityDao
from ..services.user import build_user_claims, hash_password
from ..utils.id import gen_id

_METADATA_CACHE: dict[str, dict[str, Any]] = {}
_METADATA_TTL_SECONDS = 3600


def _csv_to_set(raw: Optional[str]) -> set[str]:
    if not raw:
        return set()
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _is_truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}


def _extract_claim(data: Dict[str, Any], claim_name: Optional[str]) -> Optional[Any]:
    if not claim_name:
        return None
    value = data.get(claim_name)
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
    return value or None


def _extract_string(data: Dict[str, Any], *claim_names: Optional[str]) -> str:
    for claim_name in claim_names:
        value = _extract_claim(data, claim_name)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                item_str = str(item).strip()
                if item_str:
                    return item_str
            continue
        value_str = str(value).strip()
        if value_str:
            return value_str
    return ""


def _normalize_provider_id(value: Optional[str], fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return normalized or fallback


def _normalize_next_url(next_url: Optional[str]) -> str:
    fallback = "/agent/chat"
    if not next_url:
        return fallback
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        path = parsed.path or "/"
        if not path.startswith("/"):
            path = f"/{path}"
        query = f"?{parsed.query}" if parsed.query else ""
        fragment = f"#{parsed.fragment}" if parsed.fragment else ""
        return f"{path}{query}{fragment}"
    return next_url if next_url.startswith("/") else fallback


def _normalize_redirect_uri(
    request: Request,
    provider_id: str,
    redirect_uri: Optional[str],
) -> str:
    if redirect_uri:
        parsed = urlparse(redirect_uri)
        request_host = (request.headers.get("host") or request.url.netloc or "").strip().lower()
        redirect_host = (parsed.netloc or "").strip().lower()
        if parsed.scheme and redirect_host and redirect_host == request_host:
            return redirect_uri
        raise SageHTTPException(
            status_code=400,
            detail="OAuth 回调地址非法",
            error_detail="redirect_uri host mismatch",
        )

    callback_path = f"/api/user/oauth/callback/{provider_id}"
    return str(request.base_url).rstrip("/") + callback_path


def _default_local_provider() -> Dict[str, Any]:
    return {
        "id": "local",
        "type": "local",
        "name": "账号密码",
        "button_text": "使用账号密码登录",
        "description": "输入 Sage 本地账号和密码进入工作台",
        "icon": "key-round",
        "enabled": True,
    }


def _normalize_provider(raw: Dict[str, Any], seen_ids: set[str]) -> Optional[Dict[str, Any]]:
    provider_type = str(raw.get("type") or "oidc").strip().lower()
    if provider_type not in {"local", "oidc"}:
        return None

    fallback_id = "local" if provider_type == "local" else f"provider-{len(seen_ids) + 1}"
    provider_id = _normalize_provider_id(raw.get("id") or raw.get("name"), fallback_id)
    if provider_type == "local" and "local" in seen_ids:
        return None
    if provider_id in seen_ids:
        provider_id = f"{provider_id}-{len(seen_ids) + 1}"
    seen_ids.add(provider_id)

    provider = {
        "id": provider_id,
        "type": provider_type,
        "name": str(raw.get("name") or provider_id).strip(),
        "button_text": str(raw.get("button_text") or "").strip(),
        "description": str(raw.get("description") or "").strip(),
        "icon": str(raw.get("icon") or "").strip(),
        "enabled": bool(raw.get("enabled", True)),
    }

    if provider_type == "oidc":
        provider.update(
            {
                "client_id": raw.get("client_id"),
                "client_secret": raw.get("client_secret"),
                "discovery_url": raw.get("discovery_url"),
                "authorize_url": raw.get("authorize_url"),
                "token_url": raw.get("token_url"),
                "userinfo_url": raw.get("userinfo_url"),
                "scope": raw.get("scope") or "openid profile email",
                "username_claim": raw.get("username_claim") or "preferred_username",
                "email_claim": raw.get("email_claim") or "email",
                "name_claim": raw.get("name_claim") or "name",
                "subject_claim": raw.get("subject_claim") or "sub",
                "role_claim": raw.get("role_claim"),
                "default_role": raw.get("default_role") or "user",
                "admin_emails": raw.get("admin_emails") or "",
                "admin_usernames": raw.get("admin_usernames") or "",
                "link_by_email": raw.get("link_by_email", True),
            }
        )
    return provider


def _load_json_auth_providers(cfg: config.StartupConfig) -> list[dict[str, Any]]:
    if not cfg.auth_providers_json:
        return []
    try:
        parsed = json.loads(cfg.auth_providers_json)
    except json.JSONDecodeError as exc:
        raise SageHTTPException(
            status_code=500,
            detail="认证 Providers 配置解析失败",
            error_detail=str(exc),
        ) from exc
    if not isinstance(parsed, list):
        raise SageHTTPException(
            status_code=500,
            detail="认证 Providers 配置格式错误",
            error_detail="SAGE_AUTH_PROVIDERS must be a JSON array",
        )
    return [item for item in parsed if isinstance(item, dict)]


def get_auth_providers(include_internal: bool = False) -> list[Dict[str, Any]]:
    cfg = config.get_startup_config()
    raw_providers = _load_json_auth_providers(cfg)
    raw_providers = [_default_local_provider(), *raw_providers]

    seen_ids: set[str] = set()
    providers: list[Dict[str, Any]] = []
    for raw_provider in raw_providers:
        provider = _normalize_provider(raw_provider, seen_ids)
        if not provider or not provider.get("enabled", True):
            continue
        providers.append(provider)

    providers.sort(key=lambda item: (0 if item["type"] == "local" else 1, item["name"].lower()))

    if include_internal:
        return providers

    public_providers = []
    for provider in providers:
        public_providers.append(
            {
                "id": provider["id"],
                "type": provider["type"],
                "name": provider["name"],
                "button_text": provider["button_text"] or f"使用{provider['name']}登录",
                "description": provider["description"],
                "icon": provider["icon"],
            }
        )
    return public_providers


def get_auth_public_config() -> Dict[str, Any]:
    providers = get_auth_providers(include_internal=False)
    oidc_provider = next((provider for provider in providers if provider["type"] == "oidc"), None)
    return {
        "auth_mode": "providers",
        "auth_providers": providers,
        "default_auth_provider": providers[0]["id"] if providers else None,
        "has_local_auth": any(provider["type"] == "local" for provider in providers),
        "has_oauth_auth": any(provider["type"] == "oidc" for provider in providers),
        "oauth_enabled": oidc_provider is not None,
        "oauth_provider_name": oidc_provider["name"] if oidc_provider else None,
    }


def is_local_auth_enabled() -> bool:
    return any(provider["type"] == "local" for provider in get_auth_providers(include_internal=True))


def get_oidc_provider(provider_id: str) -> Dict[str, Any]:
    for provider in get_auth_providers(include_internal=True):
        if provider["id"] == provider_id and provider["type"] == "oidc":
            return provider
    raise SageHTTPException(
        status_code=404,
        detail="OAuth Provider 不存在",
        error_detail=provider_id,
    )


def get_default_oidc_provider() -> Optional[Dict[str, Any]]:
    for provider in get_auth_providers(include_internal=True):
        if provider["type"] == "oidc":
            return provider
    return None


async def get_oauth_provider_metadata(provider_id: str) -> Dict[str, Any]:
    provider = get_oidc_provider(provider_id)

    cache_key = provider["id"]
    cached = _METADATA_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached.get("fetched_at", 0) < _METADATA_TTL_SECONDS:
        return cached["metadata"]

    if provider.get("discovery_url"):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(provider["discovery_url"])
                response.raise_for_status()
                metadata = response.json()
        except httpx.HTTPError as exc:
            raise SageHTTPException(
                status_code=502,
                detail="获取 OAuth Provider 元数据失败",
                error_detail=str(exc),
            ) from exc
    else:
        metadata = {
            "issuer": provider["id"],
            "authorization_endpoint": provider.get("authorize_url"),
            "token_endpoint": provider.get("token_url"),
            "userinfo_endpoint": provider.get("userinfo_url"),
        }

    if not metadata.get("authorization_endpoint") or not metadata.get("token_endpoint") or not metadata.get("userinfo_endpoint"):
        raise SageHTTPException(
            status_code=500,
            detail="OAuth Provider 元数据不完整",
            error_detail=f"provider={provider_id}",
        )

    _METADATA_CACHE[cache_key] = {"fetched_at": now, "metadata": metadata}
    return metadata


async def build_oauth_authorize_url(
    request: Request,
    provider_id: str,
    next_url: Optional[str] = None,
    redirect_uri: Optional[str] = None,
) -> str:
    provider = get_oidc_provider(provider_id)
    metadata = await get_oauth_provider_metadata(provider_id)
    safe_next_url = _normalize_next_url(next_url)
    safe_redirect_uri = _normalize_redirect_uri(request, provider_id, redirect_uri)
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    request.session["oauth_flow"] = {
        "provider_id": provider["id"],
        "state": state,
        "nonce": nonce,
        "next_url": safe_next_url,
        "redirect_uri": safe_redirect_uri,
        "created_at": int(time.time()),
    }
    params = {
        "response_type": "code",
        "client_id": provider["client_id"],
        "redirect_uri": safe_redirect_uri,
        "scope": provider.get("scope") or "openid profile email",
        "state": state,
        "nonce": nonce,
    }
    return f"{metadata['authorization_endpoint']}?{urlencode(params)}"


def _resolve_oauth_role(
    userinfo: Dict[str, Any],
    provider: Dict[str, Any],
    current_role: Optional[str] = None,
) -> str:
    if current_role == "admin":
        return "admin"

    username = _extract_string(
        userinfo,
        provider.get("username_claim"),
        "preferred_username",
        "name",
        "email",
    ).lower()
    email = _extract_string(userinfo, provider.get("email_claim"), "email").lower()
    if email and email in _csv_to_set(provider.get("admin_emails")):
        return "admin"
    if username and username in _csv_to_set(provider.get("admin_usernames")):
        return "admin"

    role_claim_value = _extract_claim(userinfo, provider.get("role_claim"))
    if isinstance(role_claim_value, (list, tuple, set)):
        role_values = {str(item).strip().lower() for item in role_claim_value if str(item).strip()}
        if "admin" in role_values:
            return "admin"
    elif role_claim_value and str(role_claim_value).strip().lower() == "admin":
        return "admin"

    return provider.get("default_role") or "user"


async def _find_or_create_oauth_user(userinfo: Dict[str, Any], provider: Dict[str, Any]) -> User:
    dao = UserDao()
    identity_dao = UserExternalIdentityDao()

    subject = _extract_string(userinfo, provider.get("subject_claim"), "sub")
    if not subject:
        raise SageHTTPException(
            status_code=400,
            detail="OAuth 用户信息缺少 subject",
            error_detail="missing oauth subject",
        )

    email = _extract_string(userinfo, provider.get("email_claim"), "email")
    username = _extract_string(
        userinfo,
        provider.get("username_claim"),
        "preferred_username",
        "name",
        "email",
    )
    display_name = _extract_string(
        userinfo,
        provider.get("name_claim"),
        "name",
        provider.get("username_claim"),
        "preferred_username",
    )
    avatar_url = _extract_string(userinfo, "picture", "avatar_url", "avatar")

    if not username and email:
        username = email.split("@", 1)[0]
    if not username:
        username = f"user_{subject[:12]}"
    username = username.strip()

    provider_key = provider["id"]
    identity = await identity_dao.get_by_provider_subject(provider_key, subject)
    user = await dao.get_by_id(identity.user_id) if identity else None

    email_verified = userinfo.get("email_verified")
    email_can_bind = email and (email_verified is None or _is_truthy(email_verified))
    if not user and provider.get("link_by_email", True) and email_can_bind:
        user = await dao.get_by_email(email)

    if not user:
        unique_username = username
        existing = await dao.get_by_username(unique_username)
        while existing:
            unique_username = f"{username}_{gen_id()[:6]}"
            existing = await dao.get_by_username(unique_username)

        user = User(
            user_id=gen_id(),
            username=unique_username,
            nickname=display_name or unique_username,
            email=email or None,
            password_hash=hash_password(secrets.token_urlsafe(24)),
            role=_resolve_oauth_role(userinfo, provider),
            avatar_url=avatar_url or None,
        )
    else:
        if not user.nickname and display_name:
            user.nickname = display_name
        if not user.email and email:
            user.email = email
        if not user.avatar_url and avatar_url:
            user.avatar_url = avatar_url
        user.role = _resolve_oauth_role(userinfo, provider, current_role=user.role)

    await dao.save(user)

    if not identity:
        identity = UserExternalIdentity(
            identity_id=gen_id(),
            user_id=user.user_id,
            provider_id=provider_key,
            provider_subject=subject,
        )

    identity.user_id = user.user_id
    identity.provider_username = username or None
    identity.provider_email = email or None
    identity.profile = userinfo
    await identity_dao.save(identity)
    return user


async def complete_oauth_login(
    request: Request,
    provider_id: str,
    code: str,
    state: str,
) -> tuple[Dict[str, Any], str]:
    flow = request.session.get("oauth_flow") or {}
    if not flow:
        raise SageHTTPException(
            status_code=400,
            detail="OAuth 登录状态已失效",
            error_detail="missing oauth session state",
        )
    if flow.get("provider_id") != provider_id:
        raise SageHTTPException(
            status_code=400,
            detail="OAuth Provider 不匹配",
            error_detail="oauth provider mismatch",
        )
    if flow.get("state") != state:
        raise SageHTTPException(
            status_code=400,
            detail="OAuth 登录状态校验失败",
            error_detail="oauth state mismatch",
        )

    provider = get_oidc_provider(provider_id)
    metadata = await get_oauth_provider_metadata(provider_id)
    token_payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": flow.get("redirect_uri"),
        "client_id": provider["client_id"],
        "client_secret": provider["client_secret"],
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_response = await client.post(
                metadata["token_endpoint"],
                data=token_payload,
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            token_data = token_response.json()

            access_token = token_data.get("access_token")
            if not access_token:
                raise SageHTTPException(
                    status_code=400,
                    detail="OAuth Token 交换失败",
                    error_detail="missing access_token",
                )

            userinfo_response = await client.get(
                metadata["userinfo_endpoint"],
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            userinfo_response.raise_for_status()
            userinfo = userinfo_response.json()
    except SageHTTPException:
        raise
    except httpx.HTTPError as exc:
        raise SageHTTPException(
            status_code=502,
            detail="从 OAuth Provider 获取用户信息失败",
            error_detail=str(exc),
        ) from exc

    user = await _find_or_create_oauth_user(userinfo, provider)
    claims = build_user_claims(user)
    request.session.pop("oauth_flow", None)
    request.session["user_claims"] = claims
    logger.info(f"OAuth 登录成功: {user.username} ({provider['id']})")
    return claims, _normalize_next_url(flow.get("next_url"))


def clear_auth_session(request: Request) -> None:
    request.session.pop("oauth_flow", None)
    request.session.pop("user_claims", None)
