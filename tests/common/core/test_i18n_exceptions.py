from fastapi import FastAPI
from fastapi.testclient import TestClient

from common.core.exceptions import SageHTTPException, register_exception_handlers
from common.core.i18n import locale_from_accept_language
from common.core.middleware import register_request_logging_middleware
from common.core.render import Response


def _build_app() -> FastAPI:
    app = FastAPI()
    register_request_logging_middleware(app)
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise SageHTTPException(status_code=401, message_key="auth.unauthorized")

    @app.get("/response-error")
    async def response_error():
        return await Response.error(code=401, message="auth.unauthorized")

    @app.get("/response-template")
    async def response_template():
        return await Response.succ(
            message="conversation.title_updated",
            message_params={"session_id": "abc"},
        )

    return app


def test_sage_http_exception_uses_chinese_by_default():
    with TestClient(_build_app()) as client:
        response = client.get("/boom")

    assert response.status_code == 401
    assert response.json()["message"] == "未授权"


def test_sage_http_exception_uses_accept_language_english():
    with TestClient(_build_app()) as client:
        response = client.get("/boom", headers={"Accept-Language": "en-US,en;q=0.9"})

    assert response.status_code == 401
    assert response.json()["message"] == "Unauthorized"


def test_accept_language_skips_unsupported_locales():
    assert locale_from_accept_language("fr-FR, en-US;q=0.9") == "en-US"


def test_response_error_uses_request_locale_for_message_key():
    with TestClient(_build_app()) as client:
        response = client.get(
            "/response-error", headers={"Accept-Language": "en-US,en;q=0.9"}
        )

    assert response.json()["message"] == "Unauthorized"


def test_response_message_key_supports_template_params():
    with TestClient(_build_app()) as client:
        response = client.get(
            "/response-template", headers={"Accept-Language": "en-US,en;q=0.9"}
        )

    assert response.json()["message"] == "Conversation abc title updated"
