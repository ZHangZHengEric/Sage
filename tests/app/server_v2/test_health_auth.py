from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.server_v2.core.settings import DEFAULT_JWT_SECRET, ServerSettings
from app.server_v2.main import create_app, main
from app.server_v2.infrastructure.persistence import DatabaseUserStore
from tests.app.server_v2.conftest import make_test_service, register_and_login


def test_default_jwt_secret_meets_hmac_minimum():
    assert len(DEFAULT_JWT_SECRET.encode()) >= 32


def test_from_env_requires_mysql(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SAGE_SERVER_MYSQL_URL", raising=False)
    with pytest.raises(ValueError, match="MYSQL"):
        ServerSettings.from_env(data_root=tmp_path)
    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://sage@127.0.0.1/sage")
    assert ServerSettings.from_env(data_root=tmp_path).mysql_url


def test_settings_read_mysql_jaeger_from_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://sage@127.0.0.1/sage")
    monkeypatch.setenv("SAGE_SERVER_JAEGER_URL", "http://sage-jaeger:4317")
    monkeypatch.setenv("SAGE_SERVER_JAEGER_PUBLIC_URL", "http://127.0.0.1:16686/jaeger")
    monkeypatch.setenv("SAGE_SERVER_LOG_LEVEL", "warning")
    monkeypatch.setenv("SAGE_SERVER_LOG_FORMAT", "json")
    settings = ServerSettings.from_env(data_root=tmp_path)
    assert settings.mysql_url == "mysql://sage@127.0.0.1/sage"
    assert settings.database_url() == "mysql+aiomysql://sage@127.0.0.1/sage"
    assert settings.jaeger_url == "http://sage-jaeger:4317"
    assert settings.jaeger_public_url == "http://127.0.0.1:16686/jaeger"
    assert settings.log_level == "warning"
    assert settings.log_format == "json"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SAGE_SERVER_LOG_LEVEL", "verbose"),
        ("SAGE_SERVER_LOG_FORMAT", "yaml"),
    ],
)
def test_settings_reject_invalid_logging_choices(
    tmp_path: Path, monkeypatch, name, value
):
    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://sage@127.0.0.1/sage")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        ServerSettings.from_env(data_root=tmp_path)


def test_main_preserves_server_logging_configuration(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://sage@127.0.0.1/sage")
    monkeypatch.setenv("SAGE_SERVER_LOG_LEVEL", "warning")
    captured = {}
    monkeypatch.setattr("app.server_v2.main.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.server_v2.main.create_app", lambda service: object())

    def fake_run(application, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("app.server_v2.main.uvicorn.run", fake_run)

    assert main(["--data-root", str(tmp_path), "--host", "0.0.0.0", "--port", "9001"]) == 0
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9001
    assert captured["log_level"] == "warning"
    assert captured["log_config"] is None


def test_main_loads_dotenv_from_package_root(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "SAGE_SERVER_MYSQL_URL=mysql://sage@127.0.0.1/sage",
                "",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "temporary")
    monkeypatch.delenv("SAGE_SERVER_MYSQL_URL")
    monkeypatch.setattr("app.server_v2.main.__file__", str(tmp_path / "main.py"))
    captured = {}
    monkeypatch.setattr(
        "app.server_v2.main.create_app",
        lambda service: captured.setdefault("settings", service.settings),
    )
    monkeypatch.setattr("app.server_v2.main.uvicorn.run", lambda *args, **kwargs: None)

    assert main(["--data-root", str(tmp_path)]) == 0
    assert captured["settings"].mysql_url == "mysql://sage@127.0.0.1/sage"


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["protocol"] == "ag-ui"
    assert payload["status"] == "ok"
    assert payload["backends"] == {
        "host_store": "memory",
        "session_store": "filesystem",
        "agui_replay": "session-store",
        "log": "stdout",
        "run_ownership": "single-process",
    }
    assert response.json()["request_id"]
    assert response.headers["x-request-id"] == response.json()["request_id"]
    assert client.get("/livez").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_request_id_echoes_incoming_header(client: TestClient):
    response = client.get("/health", headers={"X-Request-ID": "req-test-12"})
    assert response.status_code == 200
    assert response.json()["request_id"] == "req-test-12"
    assert response.headers["x-request-id"] == "req-test-12"


def test_error_envelope_includes_request_id(client: TestClient):
    response = client.get("/api/threads")
    assert response.status_code == 401
    payload = response.json()
    assert payload["code"] == 401
    assert payload["data"] is None
    assert payload["request_id"]
    assert response.headers["x-request-id"] == payload["request_id"]


def test_validation_uses_server_v2_envelope(client: TestClient):
    response = client.post("/api/auth/login", json={})
    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == 422
    assert payload["message"] == "invalid request"
    assert payload["data"] is None
    assert payload["request_id"]


def test_register_login_and_session(client: TestClient):
    token = register_and_login(client)
    session = client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert session.status_code == 200
    assert session.json()["data"]["username"] == "alice"
    assert session.json()["data"]["role"] == "user"


def test_login_sets_session_cookie(client: TestClient):
    register_and_login(client)
    login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "secret1"},
    )
    token = login.json()["data"]["access_token"]
    assert login.cookies.get("sage_server_v2") == token
    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200


def test_create_app_wires_mysql_as_only_required_client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(
        "SAGE_SERVER_MYSQL_URL", "mysql://root:sage@127.0.0.1:3306/sage_v2"
    )
    monkeypatch.delenv("SAGE_SERVER_JAEGER_URL", raising=False)
    captured = {}
    monkeypatch.setattr(
        "app.server_v2.main.uvicorn.run",
        lambda app, **kwargs: captured.setdefault("app", app),
    )
    assert main(["--data-root", str(tmp_path)]) == 0
    app = captured["app"]
    runtime = app.state.service
    assert runtime.database is not None
    assert runtime.database.name == "database"
    assert runtime.settings.jaeger_url is None
    assert isinstance(runtime.users, DatabaseUserStore)
    assert len(app.state.resources._resources) == 1


def test_jaeger_routes_absent_without_url(client: TestClient):
    spec = client.get("/openapi.json").json()
    assert "/api/observability/jaeger" not in spec["paths"]
    assert "/api/observability/jaeger/auth" not in spec["paths"]


def test_jaeger_auth_requires_admin(tmp_path: Path):
    service = make_test_service(tmp_path, jaeger_url="http://127.0.0.1:4317")
    with TestClient(create_app(service=service)) as client:
        assert client.get("/api/observability/jaeger/auth").status_code == 401
        token = register_and_login(client)
        denied = client.get(
            "/api/observability/jaeger/auth",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert denied.status_code == 403
        admin = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin12345"},
        )
        allowed = client.get(
            "/api/observability/jaeger/auth",
            headers={"Authorization": f"Bearer {admin.json()['data']['access_token']}"},
        )
        assert allowed.status_code == 204
        cookie_only = client.get("/api/observability/jaeger/auth")
        assert cookie_only.status_code == 204
        redirect = client.get("/api/observability/jaeger", follow_redirects=False)
        assert redirect.status_code == 307
        assert redirect.headers["location"].startswith("http://127.0.0.1:16686/jaeger")


def test_protected_routes_require_auth(client: TestClient):
    assert client.get("/api/threads").status_code == 401
    assert client.get("/api/models").status_code == 401


def test_openapi_documents_response_models(client: TestClient):
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    assert "UserPublic" in schemas
    assert "TokenPayload" in schemas
    assert "ModelPublic" in schemas
    assert "ErrorBody" in schemas
    login = spec["paths"]["/api/auth/login"]["post"]
    assert "200" in login["responses"]
    agent = spec["paths"]["/api/agent"]["post"]["responses"]["200"]
    assert "text/event-stream" in agent["content"]
