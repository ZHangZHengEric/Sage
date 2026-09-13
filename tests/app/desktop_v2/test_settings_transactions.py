from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.desktop_v2.backend.service import DesktopV2Service


@pytest.mark.asyncio
async def test_concurrent_project_updates_and_settings_patch_preserve_each_other(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path / "data")
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    try:
        first, second, _ = await asyncio.gather(
            service.add_project("A", str(a)),
            service.add_project("B", str(b)),
            service.patch_settings({"theme_mode": "dark"}),
        )
        settings = await service.get_settings()
        assert {project.id for project in settings.projects} == {first.id, second.id}
        assert settings.theme_mode == "dark"
        await asyncio.gather(
            service.remove_project(first.id),
            service.patch_settings({"language": "en"}),
        )
        settings = await service.get_settings()
        assert [project.id for project in settings.projects] == [second.id]
        assert settings.language == "en"
        assert settings.theme_mode == "dark"
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_invalid_settings_patch_leaves_persisted_settings_unchanged(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    try:
        await service.patch_settings({"theme_mode": "dark"})
        before = await service.get_settings()
        with pytest.raises(ValueError):
            await service.patch_settings({"theme_mode": "invalid"})
        with pytest.raises(ValueError, match="unknown settings"):
            await service.patch_settings({"surprise": True})
        assert await service.get_settings() == before
    finally:
        await service.close()


def test_settings_patch_http_changes_only_supplied_fields(tmp_path: Path):
    from fastapi.testclient import TestClient
    from app.desktop_v2.backend.app import create_app

    service = DesktopV2Service(tmp_path)
    with TestClient(create_app(service=service, auth_token="test-patch")) as client:
        headers = {"Authorization": "Bearer test-patch"}
        assert (
            client.patch(
                "/api/v2/settings", json={"theme_mode": "dark"}, headers=headers
            ).status_code
            == 200
        )
        result = client.patch(
            "/api/v2/settings", json={"language": "en"}, headers=headers
        )
        assert result.status_code == 200
        assert result.json()["data"]["theme_mode"] == "dark"
        assert result.json()["data"]["language"] == "en"
        assert (
            client.patch("/api/v2/settings", json={"theme_mode": "light"}).status_code
            == 401
        )


@pytest.mark.asyncio
async def test_cancelled_writer_holds_transaction_until_thread_finishes(
    tmp_path: Path, monkeypatch
):
    import threading

    service = DesktopV2Service(tmp_path)
    await service.patch_settings({"theme_mode": "system"})
    started, release = threading.Event(), threading.Event()
    original = service._write_settings_sync
    first_write = True

    def delayed(value):
        nonlocal first_write
        if first_write:
            first_write = False
            started.set()
            if not release.wait(5):
                raise RuntimeError("test writer not released")
        original(value)

    monkeypatch.setattr(service, "_write_settings_sync", delayed)
    first = asyncio.create_task(service.patch_settings({"theme_mode": "dark"}))
    second = None
    try:
        assert await asyncio.to_thread(started.wait, 5)
        first.cancel()
        await asyncio.sleep(0)
        assert not first.done()
        second = asyncio.create_task(service.patch_settings({"language": "en"}))
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second
        settings = await service.get_settings()
        assert settings.theme_mode == "dark"
        assert settings.language == "en"
    finally:
        release.set()
        await asyncio.gather(
            first, *([second] if second else []), return_exceptions=True
        )
        await service.close()
