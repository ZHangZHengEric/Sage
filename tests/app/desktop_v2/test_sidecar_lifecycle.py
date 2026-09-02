from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.desktop_v2.backend.app import create_app
from app.desktop_v2.backend.sidecar_lifecycle import SidecarClientLeases
from sagents.v2.runtime.observability import NoopLogSink, StructuredLogger


AUTH_TOKEN = "test-desktop-capability"
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}


class _SessionStore:
    close = AsyncMock()


class _Service:
    session_store = _SessionStore()
    initialize_agent_workspace = AsyncMock()
    log_sink = NoopLogSink()
    logger = StructuredLogger(log_sink, "test.desktop.sidecar")


@pytest.mark.asyncio
async def test_client_leases_close_only_after_the_final_client_detaches():
    leases = SidecarClientLeases(ttl_seconds=30)

    first = await leases.attach("desktop-client-one")
    second = await leases.attach("desktop-client-two")
    first_release = await leases.detach("desktop-client-one")
    final_release = await leases.detach("desktop-client-two")

    assert first.active_clients == 1
    assert second.active_clients == 2
    assert not first_release.shutdown_requested
    assert final_release.shutdown_requested
    with pytest.raises(RuntimeError, match="shutting down"):
        await leases.attach("desktop-client-three")


@pytest.mark.asyncio
async def test_expired_client_lease_requests_shutdown_after_a_crash():
    now = [100.0]
    leases = SidecarClientLeases(ttl_seconds=10, monotonic=lambda: now[0])
    await leases.attach("desktop-client-one")

    now[0] = 109.9
    assert not (await leases.expire()).shutdown_requested
    now[0] = 110.0
    expired = await leases.expire()

    assert expired.active_clients == 0
    assert expired.shutdown_requested


@pytest.mark.asyncio
async def test_unclaimed_sidecar_expires_if_host_crashes_before_attach():
    now = [100.0]
    leases = SidecarClientLeases(ttl_seconds=10, monotonic=lambda: now[0])

    now[0] = 109.9
    assert not (await leases.expire()).shutdown_requested
    now[0] = 110.0
    expired = await leases.expire()

    assert expired.active_clients == 0
    assert expired.shutdown_requested


def test_sidecar_api_tracks_shared_clients_and_schedules_idle_shutdown():
    shutdown_requests: list[bool] = []
    app = create_app(
        service=_Service(),
        auth_token=AUTH_TOKEN,
        shutdown_requested=lambda: shutdown_requests.append(True),
    )

    with TestClient(app) as client:
        for client_id in ("desktop-client-one", "desktop-client-two"):
            response = client.put(
                f"/api/v2/runtime/clients/{client_id}", headers=AUTH_HEADERS
            )
            assert response.status_code == 200
        first = client.delete(
            "/api/v2/runtime/clients/desktop-client-one", headers=AUTH_HEADERS
        )
        final = client.delete(
            "/api/v2/runtime/clients/desktop-client-two", headers=AUTH_HEADERS
        )

    assert first.json()["data"] == {
        "active_clients": 1,
        "shutdown_requested": False,
    }
    assert final.json()["data"] == {
        "active_clients": 0,
        "shutdown_requested": True,
    }
    assert shutdown_requests == [True]


def test_shutdown_if_idle_refuses_to_interrupt_an_attached_client():
    shutdown_requests: list[bool] = []
    app = create_app(
        service=_Service(),
        auth_token=AUTH_TOKEN,
        shutdown_requested=lambda: shutdown_requests.append(True),
    )

    with TestClient(app) as client:
        client.put(
            "/api/v2/runtime/clients/desktop-client-one", headers=AUTH_HEADERS
        )
        response = client.post(
            "/api/v2/runtime/shutdown-if-idle", headers=AUTH_HEADERS
        )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "active_clients": 1,
        "shutdown_requested": False,
    }
    assert shutdown_requests == []
