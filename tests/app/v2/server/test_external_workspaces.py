"""Workspace imports must stay within the bound Agent and tenant directory."""

import base64

import pytest

from app.v2.server.storage.external_workspaces import (
    ensure_workspace_directory, import_workspace_files, workspace_parts,
)
from app.v2.server.storage.paths import prepare_server_v2_storage


def test_workspace_import_is_scoped_idempotent_and_rejects_conflicts(tmp_path):
    paths = prepare_server_v2_storage(tmp_path)
    files = {"src/index.html": base64.b64encode(b"<html></html>").decode()}
    assert import_workspace_files(paths, "tenant-a", "agent-a", "projects/site", files) == 1
    assert import_workspace_files(paths, "tenant-a", "agent-a", "projects/site", files) == 1
    root = paths.workspace_path("tenant-a", "agent-a")
    assert (root / "projects/site/src/index.html").read_bytes() == b"<html></html>"
    assert not (paths.workspace_path("tenant-b", "agent-a") / "projects/site/src/index.html").exists()
    assert not (paths.workspace_path("tenant-a", "agent-b") / "projects/site/src/index.html").exists()
    with pytest.raises(FileExistsError):
        import_workspace_files(paths, "tenant-a", "agent-a", "projects/site",
                               {"src/index.html": base64.b64encode(b"changed").decode()})
    assert (root / "projects/site/src/index.html").read_bytes() == b"<html></html>"


@pytest.mark.parametrize("value", ["", "/tmp/outside", "../outside", "a/../b", "a//b",
                                      "a\\b", ".runs/item", "a/./b", "a/", "a\0b"])
def test_workspace_path_rejects_escape_and_ambiguous_forms(value):
    with pytest.raises(ValueError):
        workspace_parts(value)


def test_workspace_import_rejects_symlinks_and_bad_data(tmp_path):
    paths = prepare_server_v2_storage(tmp_path)
    root = paths.workspace_dir("tenant", "agent")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "projects").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        ensure_workspace_directory(paths, "tenant", "agent", "projects/site")
    assert not (outside / "site").exists()
    with pytest.raises(ValueError):
        import_workspace_files(paths, "tenant", "agent", "safe", {"file.txt": "not base64"})
    with pytest.raises(ValueError):
        import_workspace_files(paths, "tenant", "agent", "safe", {"../escape": "YQ=="})
    assert not (root / "safe").exists()


def test_workspace_import_enforces_total_limit_before_writing(tmp_path):
    paths = prepare_server_v2_storage(tmp_path)
    encoded = base64.b64encode(b"x" * (4 << 20)).decode()
    with pytest.raises(ValueError):
        import_workspace_files(paths, "tenant", "agent", "project",
                               {f"{index}.txt": encoded for index in range(5)})
    assert not (paths.workspace_path("tenant", "agent") / "project").exists()
