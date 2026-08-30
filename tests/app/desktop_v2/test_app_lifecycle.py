from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.desktop_v2.backend import app as app_module
from app.desktop_v2.backend.service import DesktopV2Service
from sagents.v2.runtime.observability import NoopLogSink, StructuredLogger


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
    app = app_module.create_app(service=service)

    async with app.router.lifespan_context(app):
        pass

    service.initialize_agent_workspace.assert_awaited_once()
    service.session_store.close.assert_awaited_once()


def test_api_validation_failures_include_details_in_structured_log(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    app = app_module.create_app(service=service)

    with TestClient(app) as client:
        response = client.post(
            "/api/v2/projects",
            json={},
            headers={"X-Request-Id": "request_validation_test"},
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
    app = app_module.create_app(service=service, build_id="source-test-build")

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "ok",
        "protocol": "sage.runtime/v2",
        "revision": 3,
        "build_id": "source-test-build",
    }
