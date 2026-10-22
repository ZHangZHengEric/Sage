from __future__ import annotations

from typing import cast

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.v2.desktop.backend.runtime_protocol import SIDECAR_REVISION
from fastapi.testclient import TestClient

from app.v2.desktop.backend import app as app_module
from app.v2.desktop.backend.service import DesktopV2Service
from sagents.v2.runtime.observability import StructuredLogger
from sagents.v2.runtime.observability.plugins.logging_noop import NoopLogSink

AUTH_TOKEN = "test-desktop-capability"
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}


class _SessionStore:
    close = AsyncMock()


class _Service:
    session_store = _SessionStore()
    initialize_agent_workspace = AsyncMock()
    log_sink = NoopLogSink()
    logger = StructuredLogger(log_sink, "test.desktop")


@pytest.mark.asyncio
async def test_v2_lifespan_initializes_and_closes_only_owned_components():
    service = _Service()
    app = app_module.create_app(service=cast('DesktopV2Service | None', service), auth_token=AUTH_TOKEN)

    async with app.router.lifespan_context(app):
        pass

    service.initialize_agent_workspace.assert_awaited_once()
    service.session_store.close.assert_awaited_once()


def test_api_validation_failures_include_details_in_structured_log(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    app = app_module.create_app(service=service, auth_token=AUTH_TOKEN)

    with TestClient(app) as client:
        response = client.post(
            "/api/v2/projects",
            json={},
            headers={
                **AUTH_HEADERS,
                "X-Request-Id": "request_validation_test",
            },
        )

    assert response.status_code == 422
    rows = [
        json.loads(line)
        for line in (tmp_path / "runtime/logs/sage.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    failed = next(
        value for value in rows if value["event"] == "api.request.validation_failed"
    )
    assert failed["level"] == "warning"
    assert failed["request_id"] == "request_validation_test"
    assert failed["attributes"]["status_code"] == 422
    assert failed["attributes"]["errors"]


def test_health_identifies_the_exact_sidecar_build():
    service = _Service()
    app = app_module.create_app(
        service=cast('DesktopV2Service | None', service),
        build_id="source-test-build",
        auth_token=AUTH_TOKEN,
    )

    with TestClient(app) as client:
        response = client.get("/health", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "ok",
        "protocol": "sage.runtime/v2",
        "revision": SIDECAR_REVISION,
        "build_id": "source-test-build",
    }


def test_delete_skill_route_forwards_the_authenticated_desktop_user():
    service = _Service()
    setattr(service, 'delete_skill', AsyncMock(
        return_value={"deleted_name": "review"},
    ))
    app = app_module.create_app(service=cast('DesktopV2Service | None', service), auth_token=AUTH_TOKEN)

    with TestClient(app) as client:
        response = client.delete("/api/v2/skills/review", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["data"] == {"deleted_name": "review"}
    getattr(service, 'delete_skill').assert_awaited_once_with("review", "default_user")


def test_sidecar_rejects_missing_or_incorrect_launch_capability():
    service = _Service()
    app = app_module.create_app(service=cast('DesktopV2Service | None', service), auth_token=AUTH_TOKEN)

    with TestClient(app) as client:
        missing = client.get("/health")
        incorrect = client.get(
            "/health",
            headers={"Authorization": "Bearer incorrect"},
        )

    assert missing.status_code == 401
    assert incorrect.status_code == 401


def test_sidecar_ignores_caller_supplied_user_identity():
    service = _Service()
    setattr(service, 'delete_skill', AsyncMock(return_value={"deleted_name": "review"}))
    app = app_module.create_app(service=cast('DesktopV2Service | None', service), auth_token=AUTH_TOKEN)

    with TestClient(app) as client:
        response = client.delete(
            "/api/v2/skills/review",
            headers={
                **AUTH_HEADERS,
                "X-Sage-Internal-UserId": "spoofed-user",
            },
        )

    assert response.status_code == 200
    getattr(service, 'delete_skill').assert_awaited_once_with("review", "default_user")


def test_run_preflight_returns_typed_http_error_without_a_placeholder_run(tmp_path):
    service = DesktopV2Service(tmp_path)
    app = app_module.create_app(service=service, auth_token=AUTH_TOKEN)
    with TestClient(app) as client:
        response = client.post("/api/v2/runs/stream", headers=AUTH_HEADERS, json={
            "agent_id": "missing_agent", "messages": [{"role": "user", "text": "开始"}],
            "response_language": "zh-CN",
        })
        assert response.status_code == 400, response.text
        error = response.json()["detail"]
        assert error["code"] == "desktop.run_start_failed"
        assert error["metadata"]["response_language"] == "zh"
        assert client.get("/api/v2/sessions", headers=AUTH_HEADERS).json()["data"] == []
