import os

import pytest

from app.v2.server.config.settings import ServerSettings
from app.v2.server.storage import paths as paths_module
from app.v2.server.storage.paths import prepare_server_v2_storage
from tests.app.v2.server.conftest import make_settings, make_test_service


async def test_execution_identity_reaches_host_provider_and_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://unused/unused")
    monkeypatch.setenv("SAGE_SERVER_LINUX_EXECUTION_UID", "10001")
    monkeypatch.setenv("SAGE_SERVER_LINUX_EXECUTION_GID", "10002")
    settings = ServerSettings.from_env(data_root=tmp_path)
    host = make_test_service(
        tmp_path,
        linux_execution_uid=settings.linux_execution_uid,
        linux_execution_gid=settings.linux_execution_gid,
    )
    await host.start()
    try:
        assert host.execution.sandbox_provider._boundary_options["execution_uid"] == 10001
        assert host.execution.sandbox_provider._boundary_options["execution_gid"] == 10002
    finally:
        await host.close()
    assert host.paths.linux_execution_uid == 10001
    assert host.paths.linux_execution_gid == 10002


@pytest.mark.parametrize("uid,gid", [(0, 1), (1, 0), (-1, 1), (1, None), (None, 1), (True, 1), (2**32 - 1, 1)])
def test_execution_identity_rejects_invalid_or_partial_ids(tmp_path, uid, gid):
    with pytest.raises(ValueError, match="positive non-root IDs"):
        make_settings(tmp_path, linux_execution_uid=uid, linux_execution_gid=gid)


def _linux_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(paths_module.sys, "platform", "linux")
    monkeypatch.setattr(paths_module.os, "geteuid", lambda: 0)
    return prepare_server_v2_storage(
        tmp_path, linux_execution_uid=10001, linux_execution_gid=10002
    )


def test_only_workspace_directories_change_owner(tmp_path, monkeypatch):
    paths = _linux_paths(tmp_path, monkeypatch)
    workspace = paths.workspace_path("user", "agent")
    workspace.mkdir(parents=True)
    existing = workspace / "existing.txt"
    existing.write_text("keep")
    changed = []
    monkeypatch.setattr(os, "fchown", lambda fd, uid, gid: changed.append((os.fstat(fd).st_ino, uid, gid)))
    child = paths.workspace_dir("user", "agent", private_run_id="run_1")
    assert changed == [
        (directory.stat().st_ino, 10001, 10002)
        for directory in (workspace, workspace / ".runs", child)
    ]
    assert existing.read_text() == "keep"


@pytest.mark.parametrize("component", ["workspace", ".runs", "child"])
def test_workspace_ownership_never_follows_symlinks(tmp_path, monkeypatch, component):
    paths = _linux_paths(tmp_path / "data", monkeypatch)
    monkeypatch.setattr(os, "fchown", lambda *_: None)
    outside = tmp_path / "outside"
    outside.mkdir()
    child = paths.workspace_dir("user", "agent", private_run_id="run_1")
    workspace = paths.workspace_path("user", "agent")
    target = {"workspace": workspace, ".runs": workspace / ".runs", "child": child}[component]
    child.rmdir()
    if component != "child":
        (workspace / ".runs").rmdir()
    if component == "workspace":
        workspace.rmdir()
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        paths.workspace_dir("user", "agent", private_run_id="run_1")
    assert list(outside.iterdir()) == []


def test_non_root_cannot_change_workspace_owner(tmp_path, monkeypatch):
    paths = _linux_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    with pytest.raises(PermissionError, match="workspace ownership"):
        paths.workspace_dir("user", "agent")


def test_workspace_identity_is_readable_and_isolated(tmp_path):
    paths = prepare_server_v2_storage(tmp_path)
    first = paths.workspace_dir("user_123", "agent_a")
    second = paths.workspace_dir("user_123", "agent_b")
    other = paths.workspace_dir("user_456", "agent_a")
    assert first == tmp_path / "tenants/user_123/agent_a/workspace"
    (first / "private.txt").write_text("private")
    assert not (second / "private.txt").exists()
    assert not (other / "private.txt").exists()
    assert paths.workspace_dir("user_123", "agent_a") == first
    escaped = paths.workspace_dir("../outside", "a/b")
    assert escaped == tmp_path / "tenants/..%2Foutside/a%2Fb/workspace"
