import importlib.util
import asyncio

import pytest
from fastapi import FastAPI

from app.server.routers.auth import auth_router
from app.server.routers.user import user_router
from app.server.services import user as user_service
from common.core import config
from common.core.exceptions import SageHTTPException
from common.models import user as user_models
from common.models.base import Base
from common.schemas.base import LoginRequest, RegisterRequest


def test_only_local_account_auth_routes_are_registered():
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(user_router)
    paths = app.openapi()["paths"]

    assert "/api/auth/login" in paths
    assert "/api/auth/register" in paths
    assert "/api/auth/session" in paths

    removed_paths = {
        "/api/auth/providers",
        "/api/auth/register/send-code",
        "/api/auth/upstream/login",
        "/api/auth/upstream/login/{provider_id}",
        "/api/auth/upstream/callback/{provider_id}",
        "/api/user/auth-providers",
        "/api/user/register/send-code",
        "/api/user/oauth/login",
        "/api/user/oauth/login/{provider_id}",
        "/api/user/oauth/callback/{provider_id}",
        "/.well-known/oauth-authorization-server",
        "/api/oauth2/metadata",
        "/oauth2/metadata",
        "/api/oauth2/authorize",
        "/oauth2/authorize",
        "/api/oauth2/token",
        "/oauth2/token",
        "/api/oauth2/userinfo",
        "/oauth2/userinfo",
    }
    assert removed_paths.isdisjoint(paths)
    assert importlib.util.find_spec("app.server.routers.oauth2") is None


def test_login_request_accepts_username_not_email_alias():
    request = LoginRequest(username="alice", password="secret")

    assert request.username == "alice"
    assert "username_or_email" not in LoginRequest.model_fields


def test_registration_request_only_accepts_username_and_password():
    request = RegisterRequest(username="alice", password="secret")

    assert request.model_dump() == {"username": "alice", "password": "secret"}
    assert set(RegisterRequest.model_fields) == {"username", "password"}


def test_self_registration_creates_a_username_password_account(monkeypatch):
    saved_users = []

    class FakeSystemInfoDao:
        async def get_by_key(self, key):
            assert key == "allow_registration"
            return "true"

    class FakeUserDao:
        async def get_by_username(self, username):
            assert username == "alice"
            return None

        async def save(self, user):
            saved_users.append(user)

    monkeypatch.setattr(user_service, "SystemInfoDao", FakeSystemInfoDao)
    monkeypatch.setattr(user_service, "UserDao", FakeUserDao)
    monkeypatch.setattr(user_service, "gen_id", lambda: "user-1")
    monkeypatch.setattr(user_service, "_hash_password", lambda password: "hashed")

    user_id = asyncio.run(user_service.register_user("alice", "secret"))

    assert user_id == "user-1"
    assert len(saved_users) == 1
    assert saved_users[0].username == "alice"
    assert saved_users[0].password_hash == "hashed"
    assert saved_users[0].email is None


def test_email_address_is_not_used_as_login_identifier(monkeypatch):
    class FakeUserDao:
        async def get_by_username(self, username):
            assert username == "alice@example.com"
            return None

        async def get_by_email(self, email):
            pytest.fail("email lookup must not be used during login")

    monkeypatch.setattr(user_service, "UserDao", FakeUserDao)

    with pytest.raises(SageHTTPException):
        asyncio.run(user_service.authenticate_user("alice@example.com", "secret"))


def test_oauth_and_proxy_environment_settings_are_not_supported():
    startup_config = config.StartupConfig()

    assert not hasattr(startup_config, "auth_mode")
    assert not hasattr(startup_config, "auth_providers_json")
    assert not hasattr(startup_config, "trusted_identity_proxy_ips")
    assert not hasattr(startup_config, "oauth2_clients_json")
    assert not hasattr(startup_config, "oauth2_issuer")
    assert not hasattr(config.ENV, "AUTH_MODE")
    assert not hasattr(config.ENV, "AUTH_PROVIDERS")
    assert not hasattr(config.ENV, "TRUSTED_IDENTITY_PROXY_IPS")
    assert not hasattr(config.ENV, "OAUTH2_CLIENTS")
    assert not hasattr(startup_config, "eml_endpoint")
    assert not hasattr(startup_config, "eml_access_key_id")
    assert not hasattr(startup_config, "eml_template_id")
    assert not hasattr(config.ENV, "EML_ENDPOINT")
    assert not hasattr(config.ENV, "EML_ACCESS_KEY_ID")


def test_external_identity_storage_is_removed():
    assert not hasattr(user_models, "UserExternalIdentity")
    assert not hasattr(user_models, "UserExternalIdentityDao")
    assert "user_external_identities" not in Base.metadata.tables
