import asyncio
from pathlib import Path

import pytest
from starlette.requests import Request

from app.desktop.core.routers import agent as desktop_agent_router
from app.server.routers import agent as server_agent_router
from common.core.exceptions import SageHTTPException
from common.services import agent_service


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
