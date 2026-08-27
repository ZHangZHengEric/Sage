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

    with TestClient(app, client=("203.0.113.10", 50000)) as client:  # pyright: ignore[reportCallIssue]
        response = client.get(
            "/api/protected",
            headers={"X-Sage-Internal-UserId": "attacker"},
        )

    assert response.status_code == 401
    assert response.json()["message"] == "未授权"


def test_unauthorized_response_uses_accept_language_english():
    config._GLOBAL_STARTUP_CONFIG = config.StartupConfig()
    app = _build_app()

    with TestClient(app, client=("203.0.113.10", 50000)) as client:  # pyright: ignore[reportCallIssue]
        response = client.get(
            "/api/protected",
            headers={"Accept-Language": "en-US,en;q=0.9"},
        )

    assert response.status_code == 401
    assert response.json()["message"] == "Unauthorized"


def test_invalid_bearer_token_uses_accept_language_english():
    config._GLOBAL_STARTUP_CONFIG = config.StartupConfig()
    app = _build_app()

    with TestClient(app, client=("203.0.113.10", 50000)) as client:  # pyright: ignore[reportCallIssue]
        response = client.get(
            "/api/protected",
            headers={
                "Authorization": "Bearer definitely.invalid",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    assert response.status_code == 401
    assert response.json()["message"] == "Invalid token"
