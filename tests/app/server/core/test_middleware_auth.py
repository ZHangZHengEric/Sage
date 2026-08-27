from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from common.core import config
from app.server.core.middleware import register_middlewares


def _build_app() -> FastAPI:
    app = FastAPI()
    register_middlewares(app)

    @app.get("/api/protected")
    async def protected(request: Request):
        return {"user_claims": getattr(request.state, "user_claims", None)}

    return app


def test_internal_user_header_authenticates_request():
    config._GLOBAL_STARTUP_CONFIG = config.StartupConfig()
    app = _build_app()

    with TestClient(app, client=("203.0.113.10", 50000)) as client:  # pyright: ignore[reportCallIssue]
        response = client.get(
            "/api/protected",
            headers={"X-Sage-Internal-UserId": "internal-user"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "user_claims": {
            "userid": "internal-user",
            "username": "internal-user",
            "nickname": "internal-user",
            "role": "user",
        }
    }


def test_blank_internal_user_header_is_rejected():
    config._GLOBAL_STARTUP_CONFIG = config.StartupConfig()
    app = _build_app()

    with TestClient(app, client=("203.0.113.10", 50000)) as client:  # pyright: ignore[reportCallIssue]
        response = client.get(
            "/api/protected",
            headers={"X-Sage-Internal-UserId": "   "},
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
