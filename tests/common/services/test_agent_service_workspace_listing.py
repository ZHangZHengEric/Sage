import asyncio
import builtins
from pathlib import Path

import pytest
from starlette.requests import Request

from app.desktop.core.routers import agent as desktop_agent_router
from app.server.routers import agent as server_agent_router
from common.core.exceptions import SageHTTPException
from common.schemas.agent import FileWorkspaceStatRequest
from common.services import agent_service
from sagents.utils.sandbox.interface import FileInfo


def _names(result):
    return {item["path"] for item in result["files"]}


def _build_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "dir_a" / "dir_b").mkdir(parents=True)
    (workspace / "root.txt").write_text("root", encoding="utf-8")
    (workspace / "dir_a" / "a.txt").write_text("a", encoding="utf-8")
    (workspace / "dir_a" / "dir_b" / "b.txt").write_text("b", encoding="utf-8")
    (workspace / ".hidden_file").write_text("hidden", encoding="utf-8")
    (workspace / ".hidden_dir").mkdir()
    (workspace / ".hidden_dir" / "secret.txt").write_text("secret", encoding="utf-8")
    return workspace


def _fake_request(user_id: str = "user_a", role: str = "user") -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.user_claims = {"userid": user_id, "role": role}
    return request


def test_list_workspace_files_defaults_to_full_recursive_listing(tmp_path):
    workspace = _build_workspace(tmp_path)

    result = agent_service.list_workspace_files(workspace, "agent_demo")

    assert _names(result) == {
        "root.txt",
        "dir_a",
        "dir_a/a.txt",
        "dir_a/dir_b",
        "dir_a/dir_b/b.txt",
    }
    assert result["path"] == ""
    assert result["max_depth"] is None
    assert result["truncated_by_depth"] is False


def test_list_workspace_files_max_depth_zero_returns_direct_children(tmp_path):
    workspace = _build_workspace(tmp_path)

    result = agent_service.list_workspace_files(workspace, "agent_demo", max_depth=0)

    assert _names(result) == {"root.txt", "dir_a"}
    assert result["max_depth"] == 0
    assert result["truncated_by_depth"] is True


def test_list_workspace_files_subdir_depth_zero_uses_workspace_relative_paths(tmp_path):
    workspace = _build_workspace(tmp_path)

    result = agent_service.list_workspace_files(
        workspace,
        "agent_demo",
        path="dir_a",
        max_depth=0,
    )

    assert _names(result) == {"dir_a/a.txt", "dir_a/dir_b"}
    assert result["path"] == "dir_a"
    assert result["max_depth"] == 0
    assert result["truncated_by_depth"] is True


@pytest.mark.parametrize("unsafe_path", ["../outside", "/tmp/outside"])
def test_list_workspace_files_rejects_paths_outside_workspace(tmp_path, unsafe_path):
    workspace = _build_workspace(tmp_path)

    with pytest.raises(SageHTTPException):
        agent_service.list_workspace_files(workspace, "agent_demo", path=unsafe_path)


def test_stat_workspace_files_returns_metadata_without_reading_content(
    tmp_path, monkeypatch
):
    workspace = _build_workspace(tmp_path)
    original_open = builtins.open

    def fail_open(*args, **kwargs):
        target = Path(args[0]) if args else None
        if target and workspace in target.parents:
            raise AssertionError("stat endpoint must not read file content")
        return original_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail_open)

    result = agent_service.stat_workspace_files(
        workspace,
        ["root.txt", str(workspace / "dir_a" / "a.txt")],
    )

    assert len(result["files"]) == 2
    for item in result["files"]:
        assert item["exists"] is True
        assert item["is_directory"] is False
        assert item["size"] > 0
        assert item["modified_time"] > 0
        assert item["content_type"] == "text/plain"


def test_stat_workspace_files_reports_missing_file_per_item(tmp_path):
    workspace = _build_workspace(tmp_path)

    result = agent_service.stat_workspace_files(workspace, ["missing.html"])

    assert result["files"] == [
        {
            "path": "missing.html",
            "exists": False,
            "is_directory": False,
            "error_code": "FILE_NOT_FOUND",
            "message": "文件不存在: missing.html",
        }
    ]


def test_stat_workspace_files_reports_directory_without_zipping(tmp_path, monkeypatch):
    workspace = _build_workspace(tmp_path)

    def fail_zip(*args, **kwargs):
        raise AssertionError("stat endpoint must not zip directories")

    monkeypatch.setattr(agent_service.zipfile, "ZipFile", fail_zip)

    result = agent_service.stat_workspace_files(workspace, ["dir_a"])

    assert result["files"][0]["path"] == "dir_a"
    assert result["files"][0]["exists"] is True
    assert result["files"][0]["is_directory"] is True
    assert result["files"][0]["content_type"] == "inode/directory"


@pytest.mark.parametrize("unsafe_path", ["../outside", "/tmp/outside"])
def test_stat_workspace_files_reports_access_denied_per_item(tmp_path, unsafe_path):
    workspace = _build_workspace(tmp_path)

    result = agent_service.stat_workspace_files(workspace, [unsafe_path])

    assert result["files"][0]["path"] == unsafe_path
    assert result["files"][0]["exists"] is False
    assert result["files"][0]["is_directory"] is False
    assert result["files"][0]["error_code"] == "ACCESS_DENIED"


class FakeSandbox:
    def __init__(self):
        self.calls = []

    async def list_directory(self, path, include_hidden=False):
        self.calls.append((path, include_hidden))
        if path != "/sage-workspace/reports":
            raise FileNotFoundError(path)
        return [
            FileInfo(
                path="/sage-workspace/reports/demo.html",
                is_file=True,
                is_dir=False,
                size=12345,
                modified_time=1710000000.0,
            ),
            FileInfo(
                path="/sage-workspace/reports/archive",
                is_file=False,
                is_dir=True,
                size=0,
                modified_time=1710000010.0,
            ),
        ]

    async def file_exists(self, path):
        raise AssertionError("stat endpoint must not read via file_exists")

    async def read_file(self, path, encoding="utf-8"):
        raise AssertionError("stat endpoint must not read file content")


def test_stat_sandbox_workspace_files_uses_sandbox_metadata():
    sandbox = FakeSandbox()

    result = asyncio.run(
        agent_service.stat_sandbox_workspace_files(
            sandbox,
            "/sage-workspace",
            [
                "reports/demo.html",
                "/sage-workspace/reports/archive",
                "reports/missing.html",
                "../outside",
            ],
        )
    )

    assert result["files"][0] == {
        "path": "reports/demo.html",
        "exists": True,
        "is_directory": False,
        "size": 12345,
        "modified_time": 1710000000.0,
        "content_type": "text/html",
    }
    assert result["files"][1]["exists"] is True
    assert result["files"][1]["is_directory"] is True
    assert result["files"][1]["content_type"] == "inode/directory"
    assert result["files"][2]["exists"] is False
    assert result["files"][2]["error_code"] == "FILE_NOT_FOUND"
    assert result["files"][3]["exists"] is False
    assert result["files"][3]["error_code"] == "ACCESS_DENIED"
    assert sandbox.calls == [
        ("/sage-workspace/reports", True),
        ("/sage-workspace/reports", True),
        ("/sage-workspace/reports", True),
    ]


def test_server_workspace_route_passes_listing_depth_params(monkeypatch):
    calls = {}

    async def fake_get_server_file_workspace(
        agent_id,
        user_id,
        *,
        path=None,
        max_depth=None,
    ):
        calls.update(
            {
                "agent_id": agent_id,
                "user_id": user_id,
                "path": path,
                "max_depth": max_depth,
            }
        )
        return {"agent_id": agent_id, "files": [], "message": "ok"}

    monkeypatch.setattr(
        server_agent_router.agent_service,
        "get_server_file_workspace",
        fake_get_server_file_workspace,
    )

    response = asyncio.run(
        server_agent_router.get_workspace(
            "agent_demo",
            _fake_request(),
            path="dir_a",
            max_depth=0,
        )
    )

    assert response.message == "ok"
    assert calls == {
        "agent_id": "agent_demo",
        "user_id": "user_a",
        "path": "dir_a",
        "max_depth": 0,
    }


def test_desktop_workspace_route_passes_listing_depth_params(monkeypatch):
    calls = {}

    async def fake_get_desktop_file_workspace(agent_id, *, path=None, max_depth=None):
        calls.update({"agent_id": agent_id, "path": path, "max_depth": max_depth})
        return {"agent_id": agent_id, "files": [], "message": "ok"}

    monkeypatch.setattr(
        desktop_agent_router.agent_service,
        "get_desktop_file_workspace",
        fake_get_desktop_file_workspace,
    )

    response = asyncio.run(
        desktop_agent_router.get_workspace(
            "agent_demo",
            _fake_request(),
            path="dir_a",
            max_depth=0,
        )
    )

    assert response.message == "ok"
    assert calls == {"agent_id": "agent_demo", "path": "dir_a", "max_depth": 0}


def test_server_workspace_stat_route_passes_user_and_paths(monkeypatch):
    calls = {}

    async def fake_stat_server_agent_files(
        agent_id, user_id, paths, *, session_id=None
    ):
        calls.update(
            {
                "agent_id": agent_id,
                "user_id": user_id,
                "paths": paths,
                "session_id": session_id,
            }
        )
        return {"files": [{"path": "root.txt", "exists": True}]}

    monkeypatch.setattr(
        server_agent_router.agent_service,
        "stat_server_agent_files",
        fake_stat_server_agent_files,
    )

    response = asyncio.run(
        server_agent_router.stat_files(
            "agent_demo",
            FileWorkspaceStatRequest(paths=["root.txt"]),
            _fake_request(),
            session_id="session_demo",
        )
    )

    assert response.data == {"files": [{"path": "root.txt", "exists": True}]}
    assert calls == {
        "agent_id": "agent_demo",
        "user_id": "user_a",
        "paths": ["root.txt"],
        "session_id": "session_demo",
    }


def test_desktop_workspace_stat_route_passes_paths(monkeypatch):
    calls = {}

    async def fake_stat_desktop_agent_files(agent_id, paths, *, session_id=None):
        calls.update({"agent_id": agent_id, "paths": paths, "session_id": session_id})
        return {"files": [{"path": "root.txt", "exists": True}]}

    monkeypatch.setattr(
        desktop_agent_router.agent_service,
        "stat_desktop_agent_files",
        fake_stat_desktop_agent_files,
    )

    response = asyncio.run(
        desktop_agent_router.stat_files(
            "agent_demo",
            FileWorkspaceStatRequest(paths=["root.txt"]),
            _fake_request(),
            session_id="session_demo",
        )
    )

    assert response.data == {"files": [{"path": "root.txt", "exists": True}]}
    assert calls == {
        "agent_id": "agent_demo",
        "paths": ["root.txt"],
        "session_id": "session_demo",
    }
