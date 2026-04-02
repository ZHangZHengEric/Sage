import base64
import binascii
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import quote

from authlib.common.security import generate_token
from authlib.common.urls import add_params_to_uri
from authlib.oauth2.rfc6750 import BearerTokenGenerator, BearerTokenValidator
from authlib.oauth2.rfc6750.errors import InvalidTokenError
from fastapi import Request

from common.core import config
from common.core.exceptions import SageHTTPException
from common.models.oauth2 import (
    OAuth2AuthorizationCode,
    OAuth2AuthorizationCodeDao,
    OAuth2Client,
    OAuth2ClientDao,
    OAuth2Token,
    OAuth2TokenDao,
)
from common.models.user import User, UserDao
from common.utils.id import gen_id


class OAuth2ProtocolError(Exception):
    def __init__(self, error: str, description: str, status_code: int = 400):
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


@dataclass
class AuthorizationRequestContext:
    client: OAuth2Client
    redirect_uri: str
    scope: str
    state: Optional[str]
    nonce: Optional[str]
    code_challenge: Optional[str]
    code_challenge_method: Optional[str]


class SageBearerTokenValidator(BearerTokenValidator):
    def authenticate_token(self, token_string):
        raise NotImplementedError("Use async DAO lookup before validate_token")


_BEARER_TOKEN_VALIDATOR = SageBearerTokenValidator(realm="sage")
_CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{2,128}$")


def _oauth2_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}


def _normalize_client_id(value: Any, fallback: str) -> str:
    raw = str(value or "").strip()
    if raw and _CLIENT_ID_PATTERN.match(raw):
        return raw
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-")
    return normalized or fallback


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[\s,]+", value.strip())
        return [item for item in parts if item]
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            item_str = str(item or "").strip()
            if item_str:
                items.append(item_str)
        return items
    item_str = str(value).strip()
    return [item_str] if item_str else []


def _normalize_redirect_uris(value: Any) -> list[str]:
    items = value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, list):
                items = decoded
            else:
                items = [stripped]
        else:
            items = [part for part in re.split(r"[\s,]+", stripped) if part]

    redirect_uris: list[str] = []
    for item in _normalize_string_list(items):
        if item.startswith("http://") or item.startswith("https://"):
            redirect_uris.append(item)
    return redirect_uris


def _normalize_scope(value: Any, default: str = "openid profile email") -> str:
    scopes = _normalize_string_list(value)
    if not scopes:
        scopes = _normalize_string_list(default)
    return " ".join(dict.fromkeys(scopes))


def _load_json_oauth2_clients(cfg: config.StartupConfig) -> list[dict[str, Any]]:
    if not cfg.oauth2_clients_json:
        return []
    try:
        parsed = json.loads(cfg.oauth2_clients_json)
    except json.JSONDecodeError as exc:
        raise SageHTTPException(
            status_code=500,
            detail="OAuth2 Clients 配置解析失败",
            error_detail=str(exc),
        ) from exc

    if not isinstance(parsed, list):
        raise SageHTTPException(
            status_code=500,
            detail="OAuth2 Clients 配置格式错误",
            error_detail="SAGE_OAUTH2_CLIENTS must be a JSON array",
        )
    return [item for item in parsed if isinstance(item, dict)]


def get_oauth2_client_configs() -> list[dict[str, Any]]:
    cfg = config.get_startup_config()
    raw_clients = _load_json_oauth2_clients(cfg)
    configs: list[dict[str, Any]] = []
    seen_client_ids: set[str] = set()

    for raw in raw_clients:
        fallback_id = f"oauth-client-{len(seen_client_ids) + 1}"
        client_id = _normalize_client_id(
            raw.get("client_id") or raw.get("id"),
            fallback_id,
        )
        if client_id in seen_client_ids:
            client_id = f"{client_id}-{len(seen_client_ids) + 1}"
        seen_client_ids.add(client_id)

        redirect_uris = _normalize_redirect_uris(
            raw.get("redirect_uris") or raw.get("redirect_uri")
        )
        if not redirect_uris:
            raise SageHTTPException(
                status_code=500,
                detail="OAuth2 Client 缺少 redirect_uris",
                error_detail=client_id,
            )

        client_secret = str(raw.get("client_secret") or "").strip()
        token_endpoint_auth_method = str(
            raw.get("token_endpoint_auth_method")
            or ("client_secret_basic" if client_secret else "none")
        ).strip() or "none"

        if token_endpoint_auth_method not in {
            "client_secret_basic",
            "client_secret_post",
            "none",
        }:
            raise SageHTTPException(
                status_code=500,
                detail="OAuth2 Client token_endpoint_auth_method 非法",
                error_detail=f"{client_id}:{token_endpoint_auth_method}",
            )
        if token_endpoint_auth_method != "none" and not client_secret:
            raise SageHTTPException(
                status_code=500,
                detail="OAuth2 Client 缺少 client_secret",
                error_detail=client_id,
            )

        configs.append(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "name": str(raw.get("name") or client_id).strip(),
                "description": str(raw.get("description") or "").strip(),
                "enabled": _oauth2_bool(raw.get("enabled"), True),
                "skip_consent": _oauth2_bool(raw.get("skip_consent"), True),
                "grant_types": _normalize_string_list(
                    raw.get("grant_types") or ["authorization_code", "refresh_token"]
                ),
                "response_types": _normalize_string_list(
                    raw.get("response_types") or ["code"]
                ),
                "redirect_uris": redirect_uris,
                "scope": _normalize_scope(raw.get("scope")),
                "token_endpoint_auth_method": token_endpoint_auth_method,
                "extra_config": {
                    key: value
                    for key, value in raw.items()
                    if key
                    not in {
                        "id",
                        "client_id",
                        "client_secret",
                        "name",
                        "description",
                        "enabled",
                        "skip_consent",
                        "grant_types",
                        "response_types",
                        "redirect_uris",
                        "redirect_uri",
                        "scope",
                        "token_endpoint_auth_method",
                    }
                },
            }
        )
    return configs


async def sync_oauth2_clients() -> None:
    configs = get_oauth2_client_configs()
    dao = OAuth2ClientDao()
    existing_clients = {item.client_id: item for item in await dao.get_all_clients()}
    active_client_ids: set[str] = set()
    now = int(time.time())

    for item in configs:
        active_client_ids.add(item["client_id"])
        client = existing_clients.get(item["client_id"])
        if not client:
            client = OAuth2Client(
                id=gen_id(),
                name=item["name"],
                description=item["description"],
                enabled=item["enabled"],
                skip_consent=item["skip_consent"],
                extra_config=item["extra_config"],
            )
            client.client_id = item["client_id"]
            client.client_id_issued_at = now
            client.client_secret_expires_at = 0

        client.client_secret = item["client_secret"]
        client.name = item["name"]
        client.description = item["description"]
        client.enabled = item["enabled"]
        client.skip_consent = item["skip_consent"]
        client.extra_config = item["extra_config"]
        client.set_client_metadata(
            {
                "client_name": item["name"],
                "grant_types": item["grant_types"],
                "response_types": item["response_types"],
                "redirect_uris": item["redirect_uris"],
                "scope": item["scope"],
                "token_endpoint_auth_method": item["token_endpoint_auth_method"],
            }
        )
        await dao.save(client)

    for client_id, client in existing_clients.items():
        if client_id not in active_client_ids and client.enabled:
            client.enabled = False
            await dao.save(client)


async def get_oauth2_client(client_id: str) -> Optional[OAuth2Client]:
    client = await OAuth2ClientDao().get_by_client_id(client_id)
    if not client or not client.enabled:
        return None
    return client


def _ensure_requested_scope_allowed(client: OAuth2Client, requested_scope: str) -> str:
    normalized_scope = _normalize_scope(
        requested_scope or client.scope,
        default=client.scope or "openid profile email",
    )
    allowed_scope = client.get_allowed_scope(normalized_scope)
    requested_set = set(_normalize_string_list(normalized_scope))
    allowed_set = set(_normalize_string_list(allowed_scope))
    if requested_set and requested_set != allowed_set:
        raise OAuth2ProtocolError("invalid_scope", "requested scope is not allowed")
    return allowed_scope


def _normalize_code_challenge_method(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    method = str(value).strip()
    if method in {"plain", "S256"}:
        return method
    raise OAuth2ProtocolError("invalid_request", "unsupported code_challenge_method")


async def build_authorization_context(
    query_params: Mapping[str, Any]
) -> AuthorizationRequestContext:
    response_type = str(query_params.get("response_type") or "").strip()
    if response_type != "code":
        raise OAuth2ProtocolError(
            "unsupported_response_type",
            "only response_type=code is supported",
        )

    client_id = str(query_params.get("client_id") or "").strip()
    if not client_id:
        raise OAuth2ProtocolError("invalid_request", "missing client_id")

    client = await get_oauth2_client(client_id)
    if not client:
        raise OAuth2ProtocolError(
            "invalid_client",
            "unknown oauth2 client",
            status_code=401,
        )
    if not client.check_response_type("code"):
        raise OAuth2ProtocolError(
            "unauthorized_client",
            "client does not allow response_type=code",
            status_code=403,
        )
    if not client.check_grant_type("authorization_code"):
        raise OAuth2ProtocolError(
            "unauthorized_client",
            "client does not allow authorization_code",
            status_code=403,
        )

    redirect_uri = (
        str(query_params.get("redirect_uri") or "").strip()
        or client.get_default_redirect_uri()
    )
    if not redirect_uri or not client.check_redirect_uri(redirect_uri):
        raise OAuth2ProtocolError("invalid_request", "redirect_uri is invalid")

    scope = _ensure_requested_scope_allowed(
        client,
        str(query_params.get("scope") or "").strip(),
    )
    state = str(query_params.get("state") or "").strip() or None
    nonce = str(query_params.get("nonce") or "").strip() or None
    code_challenge = str(query_params.get("code_challenge") or "").strip() or None
    code_challenge_method = _normalize_code_challenge_method(
        str(query_params.get("code_challenge_method") or "").strip() or None
    )
    if code_challenge and not code_challenge_method:
        code_challenge_method = "plain"

    if client.token_endpoint_auth_method == "none" and not code_challenge:
        raise OAuth2ProtocolError("invalid_request", "public clients must use PKCE")

    return AuthorizationRequestContext(
        client=client,
        redirect_uri=redirect_uri,
        scope=scope,
        state=state,
        nonce=nonce,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )


async def create_authorization_code(
    context: AuthorizationRequestContext,
    user: User,
) -> str:
    code = generate_token(48)
    authorization_code = OAuth2AuthorizationCode(
        code_id=gen_id(),
        user_id=user.user_id,
    )
    authorization_code.code = code
    authorization_code.client_id = context.client.client_id
    authorization_code.redirect_uri = context.redirect_uri
    authorization_code.scope = context.scope
    authorization_code.response_type = "code"
    authorization_code.nonce = context.nonce
    authorization_code.code_challenge = context.code_challenge
    authorization_code.code_challenge_method = context.code_challenge_method
    await OAuth2AuthorizationCodeDao().save(authorization_code)
    return code


def build_authorization_success_redirect(
    redirect_uri: str,
    code: str,
    state: Optional[str],
) -> str:
    params = [("code", code)]
    if state:
        params.append(("state", state))
    return add_params_to_uri(redirect_uri, params)


def build_authorization_error_redirect(
    redirect_uri: str,
    error: str,
    description: str,
    state: Optional[str] = None,
) -> str:
    params = [("error", error), ("error_description", description)]
    if state:
        params.append(("state", state))
    return add_params_to_uri(redirect_uri, params)


def build_oauth2_error_body(error: str, description: str) -> dict[str, str]:
    return {
        "error": error,
        "error_description": description,
    }


def build_web_login_redirect_path(request: Request) -> str:
    cfg = config.get_startup_config()
    base = (cfg.web_base_path or "/sage").rstrip("/")
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return f"{base}/login?next={quote(next_path, safe='/?:#=&')}"


def _parse_form_encoded_body(body: bytes) -> dict[str, str]:
    decoded = body.decode("utf-8")
    from urllib.parse import parse_qsl

    return {key: value for key, value in parse_qsl(decoded, keep_blank_values=True)}


def _parse_client_basic_auth(header_value: str) -> tuple[str, str]:
    if not header_value or not header_value.lower().startswith("basic "):
        raise OAuth2ProtocolError(
            "invalid_client",
            "invalid client authentication",
            status_code=401,
        )
    encoded = header_value.split(" ", 1)[1].strip()
    try:
        raw = base64.b64decode(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise OAuth2ProtocolError(
            "invalid_client",
            "invalid basic authorization",
            status_code=401,
        ) from exc
    if ":" not in raw:
        raise OAuth2ProtocolError(
            "invalid_client",
            "invalid basic authorization",
            status_code=401,
        )
    client_id, client_secret = raw.split(":", 1)
    return client_id, client_secret


async def authenticate_token_endpoint_client(
    headers: Mapping[str, Any],
    params: Mapping[str, str],
) -> tuple[OAuth2Client, str]:
    auth_header = str(headers.get("Authorization") or "").strip()
    client_id = str(params.get("client_id") or "").strip()
    client_secret = str(params.get("client_secret") or "").strip()
    auth_method = "none"

    if auth_header:
        client_id, client_secret = _parse_client_basic_auth(auth_header)
        auth_method = "client_secret_basic"
    elif client_id and client_secret:
        auth_method = "client_secret_post"
    elif client_id:
        auth_method = "none"
    else:
        raise OAuth2ProtocolError(
            "invalid_client",
            "missing client authentication",
            status_code=401,
        )

    client = await get_oauth2_client(client_id)
    if not client:
        raise OAuth2ProtocolError(
            "invalid_client",
            "unknown oauth2 client",
            status_code=401,
        )

    if not client.check_endpoint_auth_method(auth_method, "token"):
        raise OAuth2ProtocolError(
            "invalid_client",
            "client authentication method mismatch",
            status_code=401,
        )

    if auth_method != "none" and not client.check_client_secret(client_secret):
        raise OAuth2ProtocolError(
            "invalid_client",
            "client secret mismatch",
            status_code=401,
        )

    return client, auth_method


def _pkce_challenge_from_verifier(code_verifier: str, method: str) -> str:
    if method == "plain":
        return code_verifier
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def _ensure_pkce_valid(
    authorization_code: OAuth2AuthorizationCode,
    code_verifier: str,
) -> None:
    if not authorization_code.code_challenge:
        return
    if not code_verifier:
        raise OAuth2ProtocolError("invalid_request", "missing code_verifier")
    method = authorization_code.code_challenge_method or "plain"
    if _pkce_challenge_from_verifier(code_verifier, method) != authorization_code.code_challenge:
        raise OAuth2ProtocolError("invalid_grant", "code_verifier mismatch")


def _build_token_generator() -> BearerTokenGenerator:
    def _access_token_generator(**kwargs):
        return generate_token(48)

    def _refresh_token_generator(**kwargs):
        return generate_token(48)

    def _expires_generator(client, grant_type):
        cfg = config.get_startup_config()
        value = int(cfg.oauth2_access_token_expires_in or 3600)
        return value if value > 0 else 3600

    return BearerTokenGenerator(
        access_token_generator=_access_token_generator,
        refresh_token_generator=_refresh_token_generator,
        expires_generator=_expires_generator,
    )


def _validate_bearer_token(token: OAuth2Token, request: Any = None) -> None:
    try:
        _BEARER_TOKEN_VALIDATOR.validate_token(token, [], request)
    except InvalidTokenError as exc:
        raise OAuth2ProtocolError(
            "invalid_token",
            str(exc) or "token is invalid",
            status_code=401,
        ) from exc


async def exchange_authorization_code_for_token(
    client: OAuth2Client,
    params: Mapping[str, str],
) -> tuple[dict[str, Any], User]:
    if not client.check_grant_type("authorization_code"):
        raise OAuth2ProtocolError(
            "unauthorized_client",
            "client does not allow authorization_code",
            status_code=403,
        )

    code = str(params.get("code") or "").strip()
    redirect_uri = str(params.get("redirect_uri") or "").strip()
    code_verifier = str(params.get("code_verifier") or "").strip()
    if not code:
        raise OAuth2ProtocolError("invalid_request", "missing code")
    if not redirect_uri:
        raise OAuth2ProtocolError("invalid_request", "missing redirect_uri")

    code_dao = OAuth2AuthorizationCodeDao()
    authorization_code = await code_dao.get_by_code(code)
    if not authorization_code or authorization_code.client_id != client.client_id:
        raise OAuth2ProtocolError("invalid_grant", "invalid authorization code")
    if authorization_code.is_expired():
        await code_dao.delete(authorization_code)
        raise OAuth2ProtocolError("invalid_grant", "authorization code expired")
    if authorization_code.get_redirect_uri() != redirect_uri:
        raise OAuth2ProtocolError("invalid_grant", "redirect_uri mismatch")

    _ensure_pkce_valid(authorization_code, code_verifier)

    user = await UserDao().get_by_id(authorization_code.user_id)
    if not user:
        await code_dao.delete(authorization_code)
        raise OAuth2ProtocolError("invalid_grant", "authorization code user not found")

    token_generator = _build_token_generator()
    include_refresh_token = client.check_grant_type("refresh_token")
    token_payload = token_generator.generate(
        grant_type="authorization_code",
        client=client,
        user=user,
        scope=authorization_code.get_scope(),
        include_refresh_token=include_refresh_token,
    )

    token = OAuth2Token(
        token_id=gen_id(),
        user_id=user.user_id,
        grant_type="authorization_code",
        token_metadata={
            "nonce": authorization_code.get_nonce(),
            "scope": authorization_code.get_scope(),
        },
    )
    token.client_id = client.client_id
    token.token_type = token_payload["token_type"]
    token.access_token = token_payload["access_token"]
    token.refresh_token = token_payload.get("refresh_token")
    token.scope = token_payload.get("scope", "")
    token.expires_in = int(token_payload.get("expires_in") or 0)
    token.issued_at = int(time.time())
    token.bind_entities(user=user, client=client)

    await OAuth2TokenDao().save(token)
    await code_dao.delete(authorization_code)
    return token_payload, user


def _is_scope_subset(requested_scope: str, original_scope: str) -> bool:
    requested = set(_normalize_string_list(requested_scope))
    original = set(_normalize_string_list(original_scope))
    return requested.issubset(original)


async def refresh_oauth2_access_token(
    client: OAuth2Client,
    params: Mapping[str, str],
) -> tuple[dict[str, Any], User]:
    if not client.check_grant_type("refresh_token"):
        raise OAuth2ProtocolError(
            "unauthorized_client",
            "client does not allow refresh_token",
            status_code=403,
        )

    refresh_token = str(params.get("refresh_token") or "").strip()
    requested_scope = str(params.get("scope") or "").strip()
    if not refresh_token:
        raise OAuth2ProtocolError("invalid_request", "missing refresh_token")

    token_dao = OAuth2TokenDao()
    existing_token = await token_dao.get_by_refresh_token(refresh_token)
    if not existing_token or not existing_token.check_client(client):
        raise OAuth2ProtocolError("invalid_grant", "invalid refresh_token")
    if existing_token.is_revoked():
        raise OAuth2ProtocolError("invalid_grant", "refresh_token revoked")
    if not existing_token.refresh_token:
        raise OAuth2ProtocolError("invalid_grant", "refresh_token not found")

    user = await UserDao().get_by_id(existing_token.user_id)
    if not user:
        raise OAuth2ProtocolError("invalid_grant", "refresh_token user not found")

    scope = existing_token.get_scope()
    if requested_scope:
        allowed_scope = client.get_allowed_scope(requested_scope)
        if not allowed_scope or not _is_scope_subset(allowed_scope, scope):
            raise OAuth2ProtocolError(
                "invalid_scope",
                "requested scope exceeds original scope",
            )
        scope = allowed_scope

    now = int(time.time())
    existing_token.refresh_token_revoked_at = now
    await token_dao.save(existing_token)

    token_generator = _build_token_generator()
    token_payload = token_generator.generate(
        grant_type="refresh_token",
        client=client,
        user=user,
        scope=scope,
        include_refresh_token=True,
    )

    new_token = OAuth2Token(
        token_id=gen_id(),
        user_id=user.user_id,
        grant_type="refresh_token",
        token_metadata={
            "refreshed_from": existing_token.token_id,
            "scope": scope,
        },
    )
    new_token.client_id = client.client_id
    new_token.token_type = token_payload["token_type"]
    new_token.access_token = token_payload["access_token"]
    new_token.refresh_token = token_payload.get("refresh_token")
    new_token.scope = token_payload.get("scope", "")
    new_token.expires_in = int(token_payload.get("expires_in") or 0)
    new_token.issued_at = now
    new_token.bind_entities(user=user, client=client)

    await token_dao.save(new_token)
    return token_payload, user


def _extract_bearer_token(authorization_header: str) -> str:
    auth = str(authorization_header or "").strip()
    if not auth.lower().startswith("bearer "):
        raise OAuth2ProtocolError(
            "invalid_token",
            "missing bearer access token",
            status_code=401,
        )
    token = auth.split(" ", 1)[1].strip()
    if not token:
        raise OAuth2ProtocolError(
            "invalid_token",
            "missing bearer access token",
            status_code=401,
        )
    return token


async def authenticate_access_token(
    request: Request,
) -> tuple[OAuth2Token, User, OAuth2Client]:
    access_token = _extract_bearer_token(request.headers.get("Authorization") or "")
    token = await OAuth2TokenDao().get_by_access_token(access_token)
    if not token:
        raise OAuth2ProtocolError("invalid_token", "access token not found", status_code=401)

    client = await get_oauth2_client(token.client_id)
    user = await UserDao().get_by_id(token.user_id)
    if not client or not user:
        raise OAuth2ProtocolError(
            "invalid_token",
            "access token subject not found",
            status_code=401,
        )

    token.bind_entities(user=user, client=client)
    _validate_bearer_token(token, request)
    return token, user, client


def get_oauth2_issuer(request: Request) -> str:
    cfg = config.get_startup_config()
    issuer = str(cfg.oauth2_issuer or "").strip()
    if issuer:
        return issuer.rstrip("/")
    return f"{str(request.base_url).rstrip('/')}/oauth2"


def build_oauth2_metadata(request: Request) -> dict[str, Any]:
    issuer = get_oauth2_issuer(request)
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "userinfo_endpoint": f"{issuer}/userinfo",
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "response_types_supported": ["code"],
        "scopes_supported": ["openid", "profile", "email"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
            "none",
        ],
        "code_challenge_methods_supported": ["plain", "S256"],
    }


def build_userinfo_payload(
    request: Request,
    user: User,
    token: OAuth2Token,
) -> dict[str, Any]:
    scope_set = set(_normalize_string_list(token.scope))
    payload: dict[str, Any] = {
        "sub": user.user_id,
        "iss": get_oauth2_issuer(request),
        "preferred_username": user.username,
        "role": user.role,
    }
    if "profile" in scope_set or not scope_set:
        payload["name"] = user.nickname or user.username
        if user.avatar_url:
            payload["picture"] = user.avatar_url
            payload["avatar_url"] = user.avatar_url
    if "email" in scope_set and user.email:
        payload["email"] = user.email
        payload["email_verified"] = True
    return payload


async def parse_token_endpoint_params(request: Request) -> dict[str, str]:
    body = await request.body()
    return _parse_form_encoded_body(body)


__all__ = [
    "AuthorizationRequestContext",
    "OAuth2ProtocolError",
    "authenticate_access_token",
    "authenticate_token_endpoint_client",
    "build_authorization_context",
    "build_authorization_error_redirect",
    "build_authorization_success_redirect",
    "build_oauth2_error_body",
    "build_oauth2_metadata",
    "build_userinfo_payload",
    "build_web_login_redirect_path",
    "create_authorization_code",
    "exchange_authorization_code_for_token",
    "get_oauth2_client",
    "get_oauth2_client_configs",
    "get_oauth2_issuer",
    "parse_token_endpoint_params",
    "refresh_oauth2_access_token",
    "sync_oauth2_clients",
]
