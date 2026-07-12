import asyncio
import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from starlette.datastructures import UploadFile
from starlette.requests import Request

from app.server.routers import agent as server_agent_router
from common.core import config
from common.core.exceptions import SageHTTPException
from common.services import agent_service


def _build_cfg(tmp_path: Path) -> config.StartupConfig:
    root = tmp_path / "sage"
    cfg = config.StartupConfig(
        app_mode="server",
        logs_dir=str(root / "logs"),
        session_dir=str(root / "sessions"),
        agents_dir=str(root / "agents"),
        skill_dir=str(root / "skills"),
        user_dir=str(root / "users"),
    )
    Path(cfg.agents_dir).mkdir(parents=True, exist_ok=True)
    return cfg


def _fake_request(user_id: str = "user_a", role: str = "user") -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.user_claims = {"userid": user_id, "role": role}
    return request


def test_save_workspace_upload_writes_file_under_target_path(tmp_path):
    workspace = tmp_path / "workspace"

    result = agent_service.save_workspace_upload(
        workspace,
        "artifact.txt",
        BytesIO(b"hello"),
        "nested/reports",
    )

    assert result == {
        "filename": "artifact.txt",
        "path": "nested/reports/artifact.txt",
        "size": 5,
    }
    assert (workspace / "nested" / "reports" / "artifact.txt").read_bytes() == b"hello"


@pytest.mark.parametrize(
    ("filename", "target_path"),
    [
        ("../artifact.txt", ""),
        ("artifact.txt", "../outside"),
        ("artifact.txt", "/tmp/outside"),
    ],
)
def test_save_workspace_upload_rejects_paths_outside_workspace(
    tmp_path,
    filename,
    target_path,
):
    with pytest.raises(SageHTTPException):
        agent_service.save_workspace_upload(
            tmp_path / "workspace",
            filename,
            BytesIO(b"hello"),
            target_path,
        )


def test_upload_server_agent_file_uses_user_workspace(tmp_path, monkeypatch):
    cfg = _build_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)

    result = asyncio.run(
        agent_service.upload_server_agent_file(
            "agent_demo",
            "user_a",
            "note.txt",
            BytesIO(b"note"),
            "docs",
        )
    )

    workspace = Path(cfg.agents_dir) / "user_a" / "agent_demo"
    assert result["path"] == "docs/note.txt"
    assert (workspace / "docs" / "note.txt").read_bytes() == b"note"


def _workspace_archive(files: dict[str, bytes]) -> BytesIO:
    payload = BytesIO()
    manifest = {
        "schema_version": 1,
        "files": [
            {
                "path": path,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for path, content in sorted(files.items())
        ],
    }
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for path, content in files.items():
            archive.writestr(path, content)
    payload.seek(0)
    return payload


def test_import_workspace_archive_atomically_replaces_target_subtree(tmp_path):
    workspace = tmp_path / "workspace"
    old_file = workspace / "user_health_data" / "old.csv"
    old_file.parent.mkdir(parents=True)
    old_file.write_text("old")
    files = {
        "activity/README.md": b"activity",
        "activity/steps_hourly/2026-07-12.csv": b"hour,steps\n10,100\n",
    }

    result = agent_service.import_workspace_archive(
        workspace,
        _workspace_archive(files),
        "user_health_data",
        "import-1",
    )

    assert not old_file.exists()
    assert (workspace / "user_health_data" / "activity" / "README.md").read_bytes() == b"activity"
    assert len(result["files"]) == 2
    assert result["idempotency_key"] == "import-1"


def test_import_workspace_archive_rejects_path_traversal(tmp_path):
    content = b"escape"
    manifest = {
        "schema_version": 1,
        "files": [
            {
                "path": "../escape.txt",
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("../escape.txt", content)
    payload.seek(0)

    with pytest.raises(SageHTTPException):
        agent_service.import_workspace_archive(
            tmp_path / "workspace",
            payload,
            "user_health_data",
            "import-unsafe",
        )
    assert not (tmp_path / "escape.txt").exists()


def test_download_url_to_server_agent_file_uses_user_workspace(tmp_path, monkeypatch):
    cfg = _build_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)

    import httpx

    class FakeResponse:
        content = b"image"

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url):
            assert url == "https://cdn.example.com/photo.jpg"
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        agent_service.download_url_to_server_agent_file(
            "agent_demo",
            "user_a",
            "https://cdn.example.com/photo.jpg",
            "photo.jpg",
            "upload_files",
        )
    )

    workspace = Path(cfg.agents_dir) / "user_a" / "agent_demo"
    assert result["path"] == "upload_files/photo.jpg"
    assert (workspace / "upload_files" / "photo.jpg").read_bytes() == b"image"


def test_server_workspace_upload_route_forwards_file_and_target_path(monkeypatch):
    calls = {}
    upload = UploadFile(file=BytesIO(b"hello"), filename="hello.txt")

    async def fake_upload_server_agent_file(
        agent_id,
        user_id,
        filename,
        source_file,
        target_path="",
    ):
        calls.update(
            {
                "agent_id": agent_id,
                "user_id": user_id,
                "filename": filename,
                "content": source_file.read(),
                "target_path": target_path,
            }
        )
        return {"filename": filename, "path": "docs/hello.txt", "size": 5}

    monkeypatch.setattr(
        server_agent_router.agent_service,
        "upload_server_agent_file",
        fake_upload_server_agent_file,
    )

    response = asyncio.run(
        server_agent_router.upload_file(
            "agent_demo",
            _fake_request(),
            upload,  # pyright: ignore[reportArgumentType]
            target_path="docs",
        )
    )

    assert response.message == "文件 hello.txt 上传成功"
    assert response.data["path"] == "docs/hello.txt"  # pyright: ignore[reportOptionalSubscript]
    assert calls == {
        "agent_id": "agent_demo",
        "user_id": "user_a",
        "filename": "hello.txt",
        "content": b"hello",
        "target_path": "docs",
    }


def test_server_workspace_download_from_url_route_forwards_request(monkeypatch):
    calls = {}

    async def fake_download_url_to_server_agent_file(
        agent_id,
        user_id,
        source_url,
        filename,
        target_path="",
    ):
        calls.update(
            {
                "agent_id": agent_id,
                "user_id": user_id,
                "source_url": source_url,
                "filename": filename,
                "target_path": target_path,
            }
        )
        return {"filename": filename, "path": "upload_files/photo.jpg", "size": 5}

    monkeypatch.setattr(
        server_agent_router.agent_service,
        "download_url_to_server_agent_file",
        fake_download_url_to_server_agent_file,
    )

    response = asyncio.run(
        server_agent_router.download_file_from_url(
            "agent_demo",
            server_agent_router.FileWorkspaceDownloadFromUrlRequest(
                source_url="https://cdn.example.com/photo.jpg",
                filename="photo.jpg",
                target_path="upload_files",
            ),
            _fake_request(),
        )
    )

    assert response.message == "文件 photo.jpg 上传成功"
    assert response.data["path"] == "upload_files/photo.jpg"  # pyright: ignore[reportOptionalSubscript]
    assert calls == {
        "agent_id": "agent_demo",
        "user_id": "user_a",
        "source_url": "https://cdn.example.com/photo.jpg",
        "filename": "photo.jpg",
        "target_path": "upload_files",
    }
