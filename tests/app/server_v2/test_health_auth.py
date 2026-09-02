from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.server_v2.app import create_app
from app.server_v2.core.settings import DEFAULT_JWT_SECRET, ServerV2Settings
from app.server_v2.main import ENV_FILE, load_env_file
from app.server_v2.repositories import DatabaseUserStore
from tests.app.server_v2.conftest import make_test_service, register_and_login


def test_default_jwt_secret_meets_hmac_minimum():
    assert len(DEFAULT_JWT_SECRET.encode()) >= 32


def test_from_env_requires_mysql_and_redis(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SAGE_SERVER_MYSQL_URL", raising=False)
    monkeypatch.delenv("SAGE_SERVER_REDIS_URL", raising=False)
    with pytest.raises(ValueError, match="MYSQL"):
        ServerV2Settings.from_env(data_root=tmp_path)
    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://sage@127.0.0.1/sage")
    with pytest.raises(ValueError, match="REDIS"):
        ServerV2Settings.from_env(data_root=tmp_path)


def test_settings_read_mysql_redis_jaeger_from_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://sage@127.0.0.1/sage")
    monkeypatch.setenv("SAGE_SERVER_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("SAGE_SERVER_JAEGER_URL", "http://sage-jaeger:4317")
    monkeypatch.setenv(
        "SAGE_SERVER_JAEGER_PUBLIC_URL", "http://127.0.0.1:16686/jaeger"
    )
    settings = ServerV2Settings.from_env(data_root=tmp_path)
    assert settings.mysql_url == "mysql://sage@127.0.0.1/sage"
    assert settings.database_url() == "mysql+aiomysql://sage@127.0.0.1/sage"
    assert settings.redis_url == "redis://127.0.0.1:6379/0"
    assert settings.jaeger_url == "http://sage-jaeger:4317"
    assert settings.jaeger_public_url == "http://127.0.0.1:16686/jaeger"


def test_main_loads_dotenv_from_package_root(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "SAGE_SERVER_MYSQL_URL=mysql://sage@127.0.0.1/sage",
                "SAGE_SERVER_REDIS_URL=redis://127.0.0.1:6379/0",
                "",
            )
        ),
        encoding="utf-8",
    )
    for name in (
        "SAGE_SERVER_MYSQL_URL",
        "SAGE_SERVER_REDIS_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    assert load_env_file(env_file) == env_file
    settings = ServerV2Settings.from_env(data_root=tmp_path)
    assert settings.redis_url == "redis://127.0.0.1:6379/0"
    assert ENV_FILE.name == ".env"
    assert ENV_FILE.parent.name == "server_v2"


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["protocol"] == "ag-ui"
    assert payload["status"] == "ok"
    assert payload["backends"] == {
        "host_store": "memory",
        "session_store": "filesystem",
        "agui_replay": "memory",
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


def test_create_app_wires_required_clients(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(
        "SAGE_SERVER_MYSQL_URL", "mysql://root:sage@127.0.0.1:3306/sage_v2"
    )
    monkeypatch.setenv("SAGE_SERVER_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.delenv("SAGE_SERVER_JAEGER_URL", raising=False)
    app = create_app(settings=ServerV2Settings.from_env(data_root=tmp_path))
    runtime = app.state.service
    assert runtime.database is not None
    assert runtime.database.name == "database"
    assert runtime._redis is not None
    assert runtime._redis.name == "redis"
    assert runtime.settings.jaeger_url is None
    assert isinstance(runtime.users, DatabaseUserStore)


def test_jaeger_routes_absent_without_url(client: TestClient):
    spec = client.get("/openapi.json").json()
    assert "/api/observability/jaeger" not in spec["paths"]
    assert "/api/observability/jaeger/auth" not in spec["paths"]


def test_jaeger_auth_requires_admin(tmp_path: Path):
    service = make_test_service(
        tmp_path, jaeger_url="http://127.0.0.1:4317"
    )
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
            headers={
                "Authorization": f"Bearer {admin.json()['data']['access_token']}"
            },
        )
        assert allowed.status_code == 204
        cookie_only = client.get("/api/observability/jaeger/auth")
        assert cookie_only.status_code == 204
        redirect = client.get("/api/observability/jaeger", follow_redirects=False)
        assert redirect.status_code == 307
        assert redirect.headers["location"].startswith(
            "http://127.0.0.1:16686/jaeger"
        )


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
