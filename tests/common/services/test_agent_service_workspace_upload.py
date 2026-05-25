import asyncio
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
            upload,
            target_path="docs",
        )
    )

    assert response.message == "文件 hello.txt 上传成功"
    assert response.data["path"] == "docs/hello.txt"
    assert calls == {
        "agent_id": "agent_demo",
        "user_id": "user_a",
        "filename": "hello.txt",
        "content": b"hello",
        "target_path": "docs",
    }
