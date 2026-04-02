from fastapi import FastAPI
from fastapi.testclient import TestClient

from common.core import config
from app.server.core.middleware import register_middlewares


def _build_app() -> FastAPI:
    app = FastAPI()
    register_middlewares(app)

    @app.get("/api/protected")
    async def protected():
        return {"ok": True}

    return app


def test_public_request_cannot_forge_internal_user_header():
    config._GLOBAL_STARTUP_CONFIG = config.StartupConfig()
    app = _build_app()

    with TestClient(app, client=("203.0.113.10", 50000)) as client:
        response = client.get(
            "/api/protected",
            headers={"X-Sage-Internal-UserId": "attacker"},
        )

    assert response.status_code == 401
    assert response.json()["message"] == "未授权"


def test_whitelisted_proxy_request_can_use_internal_user_header():
    config._GLOBAL_STARTUP_CONFIG = config.StartupConfig(
        trusted_identity_proxy_ips=["10.0.0.0/8", "127.0.0.1/32"]
    )
    app = _build_app()

    with TestClient(app, client=("10.1.2.3", 50000)) as client:
        response = client.get(
            "/api/protected",
            headers={"X-Sage-Internal-UserId": "internal-user"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_trusted_proxy_mode_allows_whitelisted_proxy_without_auth():
    config._GLOBAL_STARTUP_CONFIG = config.StartupConfig(
        auth_mode="trusted_proxy",
        trusted_identity_proxy_ips=["10.0.0.0/8"],
    )
    app = _build_app()

    with TestClient(app, client=("10.1.2.3", 50000)) as client:
        response = client.get("/api/protected")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_non_whitelisted_proxy_request_is_rejected():
    config._GLOBAL_STARTUP_CONFIG = config.StartupConfig(
        trusted_identity_proxy_ips=["10.0.0.0/8"]
    )
    app = _build_app()

    with TestClient(app, client=("203.0.113.10", 50000)) as client:
        response = client.get(
            "/api/protected",
            headers={"X-Sage-Internal-UserId": "internal-user"},
        )

    assert response.status_code == 401
    assert response.json()["message"] == "未授权"
