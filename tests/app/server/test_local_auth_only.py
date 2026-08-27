from fastapi import FastAPI

from app.server.routers import register_routes


def test_only_local_account_auth_routes_are_registered():
    app = FastAPI()
    register_routes(app)
    paths = app.openapi()["paths"]

    assert "/api/auth/login" in paths
    assert "/api/auth/register" in paths
    assert "/api/auth/session" in paths

    removed_paths = {
        "/api/auth/providers",
        "/api/auth/upstream/login",
        "/api/auth/upstream/login/{provider_id}",
        "/api/auth/upstream/callback/{provider_id}",
        "/api/user/auth-providers",
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
